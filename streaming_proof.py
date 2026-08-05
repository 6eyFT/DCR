"""Deterministic transport-only proof for the Phase 4A streaming boundary."""

from __future__ import annotations

import argparse
from dataclasses import replace
import math
import os
import random
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

from catalog_loader import Ad, AdIntro, Intro, Outro, Song
from playback_events import PlaybackEvent, PlaybackPlanner
from station_scheduler import AdvertisementBlock, SongBlock
from streaming_adapter import (
    LiquidsoapStreamingAdapter,
    StreamingResultStatus,
    deserialize_event,
    send_bridge_command,
)


PROOF_EVENT_COUNT = 7


def generate_wav(path: Path, *, duration: float = 0.2, frequency: float = 440.0) -> None:
    """Generate a small mono PCM fixture without external dependencies."""

    sample_rate = 8_000
    frame_count = int(sample_rate * duration)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        for frame in range(frame_count):
            sample = int(8_000 * math.sin(2 * math.pi * frequency * frame / sample_rate))
            output.writeframesraw(struct.pack("<h", sample))


def build_proof_events(fixture_root: Path) -> tuple[PlaybackEvent, ...]:
    """Build the required fixed sequence through the Phase 3 planner."""

    names = (
        "initial song.wav",
        "initial outro.wav",
        "normal intro.wav",
        "normal song.wav",
        "normal outro.wav",
        "advertisement intro.wav",
        "advertisement.wav",
    )
    paths = {name: fixture_root / name for name in names}
    for index, path in enumerate(paths.values(), start=1):
        generate_wav(path, frequency=220.0 + index * 30.0)

    initial_song = Song(
        id=1,
        track=str(paths["initial song.wav"]),
        artist="Initial Artist",
    )
    normal_song = Song(
        id=2,
        track=str(paths["normal song.wav"]),
        artist="Normal Artist",
    )
    planner = PlaybackPlanner(lambda _path: 0.2, random.Random(19))

    initial = SongBlock(
        song=initial_song,
        intro=None,
        outro=Outro(
            artist=initial_song.artist,
            song=initial_song.track,
            outro=str(paths["initial outro.wav"]),
        ),
        initial=True,
    )
    normal = SongBlock(
        song=normal_song,
        intro=Intro(
            artist=normal_song.artist,
            song=normal_song.track,
            intro=str(paths["normal intro.wav"]),
        ),
        outro=Outro(
            artist=normal_song.artist,
            song=normal_song.track,
            outro=str(paths["normal outro.wav"]),
        ),
        initial=False,
    )
    advertisement = AdvertisementBlock(
        intro=AdIntro(ad_intro=str(paths["advertisement intro.wav"])),
        advertisement=Ad(ad=str(paths["advertisement.wav"])),
    )
    return (
        *planner.plan(initial),
        *planner.plan(normal),
        *planner.plan(advertisement),
    )


def run_loopback_engine(socket_path: Path, received: list[PlaybackEvent]) -> None:
    """Exercise the real socket protocol without pretending to decode audio."""

    for _index in range(PROOF_EVENT_COUNT):
        response = send_bridge_command(
            socket_path,
            {"command": "next"},
            timeout=5.0,
        )
        if response.get("type") != "event":
            raise RuntimeError(f"expected event, got {response!r}")
        event_id = response["event_id"]
        event = deserialize_event(response["event"])
        received.append(event)

        if not Path(event.media_path).is_file():
            send_bridge_command(
                socket_path,
                {
                    "command": "result",
                    "event_id": event_id,
                    "status": StreamingResultStatus.START_FAILED.value,
                    "detail": "fixture media is missing",
                },
            )
            continue

        send_bridge_command(
            socket_path,
            {"command": "started", "event_id": event_id},
        )
        send_bridge_command(
            socket_path,
            {
                "command": "result",
                "event_id": event_id,
                "status": StreamingResultStatus.COMPLETED.value,
                "detail": "transport-only loopback completion",
            },
        )


def run_proof() -> int:
    with tempfile.TemporaryDirectory(prefix="dcr-streaming-proof-") as temp:
        root = Path(temp)
        socket_path = root / "station.sock"
        events = build_proof_events(root)
        received: list[PlaybackEvent] = []

        with LiquidsoapStreamingAdapter(
            socket_path,
            start_timeout=5.0,
            result_timeout=5.0,
            event_wait_timeout=5.0,
        ) as adapter:
            engine = threading.Thread(
                target=run_loopback_engine,
                args=(socket_path, received),
                daemon=True,
            )
            engine.start()
            results = [adapter.play(event) for event in events]
            engine.join(timeout=5.0)

        if engine.is_alive():
            raise RuntimeError("loopback engine did not finish")
        if received != list(events):
            raise RuntimeError("event order or transport fields changed")
        if not all(result.completed for result in results):
            raise RuntimeError(f"proof event failed: {results!r}")

        for event, result in zip(events, results, strict=True):
            print(
                f"{result.event_id} {event.media_type.value}: "
                f"{event.display_title} offset={event.start_offset:.6f}s completed"
            )
    return 0


def run_liquidsoap_proof(output_path: Path) -> int:
    """Run the generated mixed-format sequence through Liquidsoap when installed."""

    liquidsoap = shutil.which("liquidsoap")
    ffmpeg = shutil.which("ffmpeg")
    if liquidsoap is None:
        raise RuntimeError("liquidsoap is required for the encoded-output proof")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to generate the temporary MP3 fixture")

    with tempfile.TemporaryDirectory(prefix="dcr-liquidsoap-proof-") as temp:
        root = Path(temp)
        socket_path = root / "station.sock"
        events = list(build_proof_events(root))

        mp3_path = root / "normal song.mp3"
        conversion = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                events[3].media_path,
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "128k",
                str(mp3_path),
            ],
            check=False,
        )
        if conversion.returncode != 0 or not mp3_path.is_file():
            raise RuntimeError("ffmpeg could not generate the temporary MP3 fixture")
        events[3] = replace(events[3], media_path=str(mp3_path))

        bridge_command = " ".join(
            (
                shlex.quote(sys.executable),
                shlex.quote(str(Path(__file__).with_name("streaming_bridge.py"))),
            )
        )
        environment = {
            **os.environ,
            "DCR_STREAM_SOCKET": str(socket_path),
            "DCR_STREAM_BRIDGE": bridge_command,
            "DCR_STREAM_OUTPUT": str(output_path.resolve()),
        }
        config = Path(__file__).with_name("liquidsoap") / "dcr-proof.liq"

        with LiquidsoapStreamingAdapter(
            socket_path,
            start_timeout=15.0,
            result_timeout=300.0,
            event_wait_timeout=5.0,
        ) as adapter:
            process = subprocess.Popen([liquidsoap, str(config)], env=environment)
            try:
                results = [adapter.play(event) for event in events]
                if not all(result.completed for result in results):
                    raise RuntimeError(f"Liquidsoap proof event failed: {results!r}")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError("Liquidsoap did not create a non-empty encoded output")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--liquidsoap",
        action="store_true",
        help="run the real mixed WAV/MP3 encoded-output proof",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/dcr-streaming-proof.mp3"),
        help="encoded proof output path",
    )
    args = parser.parse_args(argv)
    try:
        if args.liquidsoap:
            return run_liquidsoap_proof(args.output)
        return run_proof()
    except RuntimeError as error:
        print(f"streaming proof failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
