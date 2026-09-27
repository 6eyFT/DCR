"""Opt-in real decoder/encoder/HTTP proof, using only generated media."""

from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from demo_station import make_demo
from station_web import Station, StationServer


@unittest.skipUnless(
    os.environ.get("DCR_RUN_STATION_TESTS") == "1" and shutil.which("liquidsoap"),
    "set DCR_RUN_STATION_TESTS=1 with Liquidsoap/FFmpeg installed",
)
class LiveStationTests(unittest.TestCase):
    def test_shared_stream_late_join_zero_listeners_privacy_and_source_loss(self):
        with TemporaryDirectory(prefix="dcr-live-test-") as tmp:
            root = Path(tmp)
            media = root / "demo"
            media.mkdir()
            make_demo(media, song_seconds=3)
            station = Station(media, root, demo=True, seed=7)
            server = StationServer(0, station)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(worker.join, 3)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            self.addCleanup(station.close)
            captures = {}
            errors = []

            def get(path, *, port=server.server_port):
                connection = HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("GET", path)
                response = connection.getresponse()
                result = response.status, response.read()
                connection.close()
                return result

            def wait_for(predicate, timeout=35):
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    if predicate():
                        return
                    time.sleep(0.05)
                self.fail("Timed out waiting for live station condition")

            def capture(name, size):
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=8)
                try:
                    connection.request("GET", "/stream")
                    response = connection.getresponse()
                    if response.status != 200:
                        raise AssertionError(f"Stream returned {response.status}")
                    captures[name] = response.read(size)
                except Exception as error:
                    errors.append(error)
                finally:
                    connection.close()

            station.start()
            try:
                wait_for(lambda: station.snapshot()["now"] is not None)
                first_id = station.snapshot()["now"]["event_id"]
                # No stream clients: the broadcast must still advance.
                wait_for(lambda: station.snapshot()["now"] is not None and
                         station.snapshot()["now"]["event_id"] != first_id)
                self.assertEqual(get("/radio.mp3", port=station.stream_port)[0], 401)
                a = threading.Thread(target=capture, args=("early", 160000))
                a.start()
                time.sleep(3)
                b = threading.Thread(target=capture, args=("late", 64000))
                b.start()
                a.join(15)
                b.join(10)
                self.assertFalse(a.is_alive() or b.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(len(captures["early"]), 160000)
                self.assertEqual(len(captures["late"]), 64000)
                # Compare encoded bytes, not just metadata or matching titles.
                overlap = captures["late"][4096:45056]
                matched_at = captures["early"].find(overlap)
                self.assertGreater(matched_at, 16000)
                print(f"LIVE PROOF: late listener shares {len(overlap)} exact MP3 bytes at offset {matched_at}", flush=True)
                encoded = root / "capture.mp3"
                encoded.write_bytes(captures["early"])
                decoded = subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", str(encoded), "-f", "s16le", "-ac", "1", "-ar", "8000", "-"],
                    capture_output=True, check=True, timeout=15,
                ).stdout
                self.assertGreater(len(decoded), 80000)
                self.assertGreater(sum(value != 0 for value in decoded), len(decoded) // 4)
                log = root / "liquidsoap.log"
                wait_for(lambda: "media_type=Advertisement path=" in log.read_text())
                starts = re.findall(r"START event_id=\S+ media_type=(.*?) path=", log.read_text())
                self.assertEqual(starts[0], "Song")
                before_ad = starts[:starts.index("Advertisement intro")]
                self.assertEqual(before_ad.count("Song"), 5)
                self.assertEqual(starts[starts.index("Advertisement intro") + 1], "Advertisement")
                self.assertEqual(before_ad, ["Song", "Outro"] + ["Intro", "Song", "Outro"] * 4)
                self.assertNotIn("media_path", json.loads(get("/api/now")[1])["now"])
                # Reconnecting after every listener leaves must not reset the station.
                prior = station.snapshot()["now"]["event_id"]
                wait_for(lambda: station.snapshot()["now"] is not None and
                         station.snapshot()["now"]["event_id"] != prior)
                capture("rejoined", 8192)
                self.assertEqual(len(captures["rejoined"]), 8192)
                self.assertEqual(errors, [])
                station.process.terminate()
                wait_for(lambda: station.stop.is_set())
                self.assertEqual(json.loads(get("/api/now")[1])["status"], "offline")
                self.assertEqual(get("/stream")[0], 503)
                print("LIVE PROOF: audible MP3, zero-listener progress, 5-song ad cadence, rejoin, authentication and source-loss handling passed", flush=True)
            finally:
                station.close()
                server.shutdown()
                server.server_close()
                worker.join(3)


if __name__ == "__main__":
    unittest.main()
