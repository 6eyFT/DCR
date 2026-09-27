"""Loopback-only shared station. Run with Poetry; no web framework required."""

from __future__ import annotations

import argparse
import base64
from dataclasses import replace
from functools import lru_cache
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
from random import Random
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
from urllib.parse import urlsplit

from catalog_loader import PROJECT_ROOT, load_catalogs, resolve_project_path
from demo_station import make_demo
from playback_events import PlaybackPlanner, STATION_NAME
from station_scheduler import StationScheduler
from streaming_adapter import LiquidsoapStreamingAdapter
from streaming_block_player import StreamingBlockPlayer


@lru_cache(maxsize=256)
def media_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=15, check=True,
    )
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Invalid audio duration: {path}")
    return duration


def available_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Station:
    """Own exactly one scheduler and source process, independent of listeners."""

    def __init__(self, root: Path, runtime_dir: Path, *, demo=False, seed=None):
        self.root = root.resolve()
        self.runtime_dir = runtime_dir
        self.demo = demo
        self.station_id = secrets.token_hex(8)
        self.stop = threading.Event()
        self.error = None
        self.process = None
        self.worker = None
        self.adapter = None
        self.log = None
        self.stream_port = available_port()
        self.password = secrets.token_urlsafe(32)
        self.control_token = secrets.token_urlsafe(32)
        catalogs = load_catalogs(project_root=self.root)
        self.scheduler = StationScheduler(catalogs, Random(seed))
        self.planner = PlaybackPlanner(self.duration, Random(seed))

    def duration(self, path):
        return media_duration(str(resolve_project_path(path, project_root=self.root)))

    def start(self):
        # Explicit authenticated TCP also works where AF_UNIX is unavailable.
        self.adapter = LiquidsoapStreamingAdapter(
            "tcp:127.0.0.1:0", token=self.control_token, start_timeout=30,
        )
        bridge = " ".join(shlex.quote(part) for part in
                          (sys.executable, str(PROJECT_ROOT / "streaming_bridge.py")))
        environment = {
            **os.environ,
            "DCR_STREAM_SOCKET": str(self.adapter.socket_path),
            "DCR_CONTROL_TOKEN": self.control_token,
            "DCR_STREAM_BRIDGE": bridge,
            "DCR_STREAM_PORT": str(self.stream_port),
            "DCR_STREAM_PASSWORD": self.password,
        }
        self.log = (self.runtime_dir / "liquidsoap.log").open("wb")
        self.process = subprocess.Popen(
            ["liquidsoap", str(PROJECT_ROOT / "liquidsoap/dcr-station.liq")],
            env=environment, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Liquidsoap startup failed:\n" +
                                   (self.runtime_dir / "liquidsoap.log").read_text()[-3000:])
            try:
                with socket.create_connection(("127.0.0.1", self.stream_port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Liquidsoap stream did not become ready within 25 seconds")
        self.worker = threading.Thread(target=self._broadcast, name="dcr-station", daemon=True)
        self.worker.start()
        threading.Thread(target=self._watch_source, name="dcr-source-watch", daemon=True).start()

    def _watch_source(self):
        code = self.process.wait()
        if not self.stop.is_set():
            self.error = f"Audio source stopped (exit {code}). Restart the station."
            self.stop.set()
            self.adapter.source_lost(self.error)

    def play(self, event):
        absolute = replace(event, media_path=str(resolve_project_path(event.media_path, self.root)))
        result = self.adapter.play(absolute)
        if not result.completed and not self.stop.is_set():
            print(f"Playback failed: {event.display_title}: {result.status.value}", file=sys.stderr)
        return result

    def _broadcast(self):
        player = StreamingBlockPlayer(self.planner, self)
        failures = 0
        try:
            while not self.stop.is_set():
                block = self.scheduler.next_block()
                outcome = player.play(block)
                self.scheduler.report_outcome(block, outcome)
                completed = getattr(outcome, "song_completed",
                                    getattr(outcome, "advertisement_completed", False))
                failures = 0 if completed else failures + 1
                if failures >= 3:
                    raise RuntimeError("Three blocks failed consecutively. Check local media and restart.")
                if not completed:
                    self.stop.wait(0.5)
        except Exception as error:
            if not self.stop.is_set():
                self.error = str(error)
                self.stop.set()
                if self.process.poll() is None:
                    self.process.terminate()

    def snapshot(self):
        return {
            "station": STATION_NAME,
            "station_id": self.station_id,
            "demo": self.demo,
            "status": "offline" if self.stop.is_set() else "live",
            "error": self.error,
            "now": self.adapter.now_playing() if self.adapter else None,
        }

    def close(self):
        self.stop.set()
        if self.adapter:
            self.adapter.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.worker:
            self.worker.join(timeout=5)
        if self.log:
            self.log.close()


class StationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, station):
        self.station = station
        self.stream_slots = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", port), StationHandler)


class StationHandler(BaseHTTPRequestHandler):
    """Exact-route allowlist: catalogs, media files, and control are never served."""

    def log_message(self, *_args):
        pass

    def send_content(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Reject DNS rebinding and cross-site embedding of a local private station.
        try:
            authority = urlsplit("//" + self.headers.get("Host", "")).hostname
        except ValueError:
            authority = None
        if authority not in {"127.0.0.1", "localhost"} or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send_content(403, b'{"error":"Loopback access only"}')
            return
        path = urlsplit(self.path).path
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/player.js": ("player.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/favicon.svg": ("favicon.svg", "image/svg+xml")}
        if path in static:
            name, mime = static[path]
            self.send_content(200, (PROJECT_ROOT / "web" / name).read_bytes(), mime)
        elif path == "/api/now":
            self.send_content(200, json.dumps(self.server.station.snapshot()).encode())
        elif path == "/stream":
            self._stream()
        else:
            self.send_content(404, b'{"error":"Not found"}')

    def _stream(self):
        station = self.server.station
        if station.stop.is_set():
            self.send_content(503, b'{"error":"Station offline"}')
            return
        if not self.server.stream_slots.acquire(blocking=False):
            self.send_content(503, b'{"error":"Listener limit reached"}')
            return
        upstream = HTTPConnection("127.0.0.1", station.stream_port, timeout=5)
        sent_headers = False
        try:
            credential = base64.b64encode(f"listener:{station.password}".encode()).decode()
            upstream.request("GET", "/radio.mp3", headers={"Authorization": f"Basic {credential}"})
            response = upstream.getresponse()
            if response.status != 200:
                self.send_content(503, b'{"error":"Stream unavailable"}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            sent_headers = True
            self.connection.settimeout(5)
            while not station.stop.is_set():
                chunk = response.read(1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, HTTPException):
            if not sent_headers:
                self.send_content(503, b'{"error":"Stream unavailable"}')
        finally:
            upstream.close()
            self.server.stream_slots.release()
            self.close_connection = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Use generated test signals instead of private media")
    parser.add_argument("--media-root", type=Path, default=PROJECT_ROOT,
                        help="Existing root containing unchanged data/ and assets/ directories")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--seed", type=int, help="Optional reproducible station selection")
    args = parser.parse_args(argv)
    for command in ("liquidsoap", "ffprobe"):
        if shutil.which(command) is None:
            parser.error(f"Missing {command}. Install liquidsoap and ffmpeg system packages.")
    station = None
    server = None
    with TemporaryDirectory(prefix="dcr-station-") as temporary:
        runtime = Path(temporary)
        try:
            root = args.media_root
            if args.demo:
                root = runtime / "demo"
                root.mkdir()
                make_demo(root)
            station = Station(root, runtime, demo=args.demo, seed=args.seed)
            # Bind before starting playback so a duplicate launch on this port fails early.
            server = StationServer(args.port, station)
            station.start()
            print(f"Private local player: http://127.0.0.1:{server.server_port}", flush=True)
            if args.demo:
                print("DEMO: generated test signals; private audio is not loaded.", flush=True)
            def terminate(_signum, _frame):
                raise KeyboardInterrupt

            signal.signal(signal.SIGTERM, terminate)
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            return 0
        except Exception as error:
            print(f"Station could not run: {error}", file=sys.stderr)
            return 1
        finally:
            if station:
                station.close()
            if server:
                server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
