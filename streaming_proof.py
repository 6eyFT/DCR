"""Deterministic transport and real Liquidsoap runtime validation proof."""

from __future__ import annotations

import argparse
from array import array
from dataclasses import dataclass, replace
import json
import math
import os
import random
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable

from catalog_loader import Ad, AdIntro, Intro, Outro, Song
from playback_events import MediaType, PlaybackEvent, PlaybackPlanner
from station_scheduler import AdvertisementBlock, SongBlock
from streaming_adapter import (
    LiquidsoapStreamingAdapter,
    StreamingResult,
    StreamingResultStatus,
    deserialize_event,
    send_bridge_command,
)
from streaming_block_player import StreamingBlockPlayer


PROOF_EVENT_COUNT = 7
SAMPLE_RATE = 8_000
CUE_DURATION = 3.0
LOW_FREQUENCY = 220.0
HIGH_FREQUENCY = 880.0


def generate_wav(
    path: Path,
    *,
    duration: float = 0.5,
    frequency: float = 440.0,
) -> None:
    """Generate a deterministic mono PCM fixture without private media."""

    generate_segmented_wav(path, ((duration, frequency),))


def generate_segmented_wav(
    path: Path,
    segments: tuple[tuple[float, float], ...],
) -> None:
    """Generate audible regions whose frequencies make cueing observable."""

    frames = bytearray()
    phase_frame = 0
    for duration, frequency in segments:
        for _index in range(int(SAMPLE_RATE * duration)):
            sample = int(
                12_000
                * math.sin(2 * math.pi * frequency * phase_frame / SAMPLE_RATE)
            )
            frames.extend(struct.pack("<h", sample))
            phase_frame += 1

    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(frames)


def convert_to_mp3(source: Path, target: Path, ffmpeg: str) -> None:
    conversion = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(target),
        ],
        check=False,
    )
    if conversion.returncode != 0 or not target.is_file():
        raise RuntimeError(f"ffmpeg could not generate fixture: {target}")


def build_proof_events(
    fixture_root: Path,
    *,
    initial_format: str = "wav",
    ffmpeg: str | None = None,
) -> tuple[PlaybackEvent, ...]:
    """Build the required fixed sequence through the Phase 3 planner."""

    names = (
        "initial song.wav",
        "initial outro.wav",
        "normal intro.wav",
        "normal song.wav",
        'normal #1, "quoted" ☢ outro.wav',
        "advertisement intro.wav",
        "advertisement.wav",
    )
    paths = {name: fixture_root / name for name in names}
    generate_segmented_wav(
        paths["initial song.wav"],
        ((CUE_DURATION / 2, LOW_FREQUENCY), (CUE_DURATION / 2, HIGH_FREQUENCY)),
    )
    for index, name in enumerate(names[1:], start=1):
        generate_wav(paths[name], frequency=300.0 + index * 50.0)

    initial_song = Song(
        id=1,
        track=str(paths["initial song.wav"]),
        artist='Initial Artist "Six" ☢',
    )
    normal_song = Song(
        id=2,
        track=str(paths["normal song.wav"]),
        artist="Normal Artist",
    )
    planner = PlaybackPlanner(lambda _path: CUE_DURATION, random.Random(19))

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
            outro=str(paths['normal #1, "quoted" ☢ outro.wav']),
        ),
        initial=False,
    )
    advertisement = AdvertisementBlock(
        intro=AdIntro(ad_intro=str(paths["advertisement intro.wav"])),
        advertisement=Ad(ad=str(paths["advertisement.wav"])),
    )
    events = [
        *planner.plan(initial),
        *planner.plan(normal),
        *planner.plan(advertisement),
    ]

    if ffmpeg is not None:
        normal_mp3 = fixture_root / "normal song.mp3"
        convert_to_mp3(paths["normal song.wav"], normal_mp3, ffmpeg)
        events[3] = replace(events[3], media_path=str(normal_mp3))

    if initial_format == "mp3":
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required for the MP3 cue fixture")
        initial_mp3 = fixture_root / "initial song.mp3"
        convert_to_mp3(paths["initial song.wav"], initial_mp3, ffmpeg)
        events[0] = replace(events[0], media_path=str(initial_mp3))
    elif initial_format != "wav":
        raise ValueError(f"unsupported initial fixture format: {initial_format}")

    return tuple(events)


def run_loopback_engine(socket_path: Path, received: list[PlaybackEvent]) -> None:
    """Exercise the real socket protocol without pretending to decode audio."""

    for _index in range(PROOF_EVENT_COUNT):
        response = send_bridge_command(socket_path, {"command": "next"}, timeout=5.0)
        if response.get("type") != "event":
            raise RuntimeError(f"expected event, got {response!r}")
        event_id = response["event_id"]
        event = deserialize_event(response["event"])
        received.append(event)
        send_bridge_command(socket_path, {"command": "started", "event_id": event_id})
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
            "tcp:127.0.0.1:0" if os.environ.get("DCR_PROOF_TCP") == "1" else socket_path,
            start_timeout=5.0,
            result_timeout=5.0,
            event_wait_timeout=1.0,
        ) as adapter:
            socket_path = adapter.socket_path
            engine = threading.Thread(
                target=run_loopback_engine,
                args=(socket_path, received),
                daemon=True,
            )
            engine.start()
            results = []
            for event in events:
                results.append(adapter.play(event))
                time.sleep(0.2)
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


@dataclass
class LiquidsoapProcess:
    process: subprocess.Popen[bytes]
    log_path: Path
    log_file: object
    watcher: threading.Thread

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5.0)
        self.watcher.join(timeout=2.0)
        self.log_file.close()


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float,
    reason: str,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {reason}")


def start_liquidsoap(
    adapter: LiquidsoapStreamingAdapter,
    socket_path: Path,
    output_path: Path,
    log_path: Path,
    liquidsoap: str,
) -> LiquidsoapProcess:
    output_path.unlink(missing_ok=True)
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
    log_file = log_path.open("wb")
    process = subprocess.Popen(
        [liquidsoap, str(config)],
        env=environment,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    def watch_source() -> None:
        return_code = process.wait()
        adapter.source_lost(f"Liquidsoap exited with status {return_code}")

    watcher = threading.Thread(target=watch_source, daemon=True)
    watcher.start()
    runtime = LiquidsoapProcess(process, log_path, log_file, watcher)
    try:
        wait_until(
            lambda: output_path.is_file() and output_path.stat().st_size > 0,
            timeout=15.0,
            reason="Liquidsoap encoded fallback output",
        )
    except RuntimeError:
        runtime.stop()
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(f"Liquidsoap did not start:\n{log_text[-4000:]}")
    return runtime


def assert_result_timing(result: StreamingResult) -> None:
    timestamps = (
        result.submitted_at,
        result.delivered_at,
        result.started_at,
        result.finished_at,
    )
    if any(value is None for value in timestamps):
        raise RuntimeError(f"missing lifecycle timestamp: {result!r}")
    if list(timestamps) != sorted(timestamps):
        raise RuntimeError(f"out-of-order lifecycle timestamps: {result!r}")


def decode_frequency(output_path: Path, ffmpeg: str) -> tuple[float, float]:
    decoded = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(output_path),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        check=False,
    )
    if decoded.returncode != 0 or not decoded.stdout:
        raise RuntimeError(f"ffmpeg could not decode proof output: {output_path}")
    samples = array("h")
    samples.frombytes(decoded.stdout)
    if sys.byteorder != "little":
        samples.byteswap()

    window_size = SAMPLE_RATE // 4
    candidates = []
    for start in range(0, max(1, len(samples) - window_size), SAMPLE_RATE // 20):
        window = samples[start : start + window_size]
        rms = math.sqrt(sum(sample * sample for sample in window) / len(window))
        if rms > 5_000:
            crossings = sum(
                1
                for previous, current in zip(window, window[1:])
                if (previous < 0 <= current) or (previous >= 0 > current)
            )
            candidates.append(
                (start, crossings / (2 * (len(window) / SAMPLE_RATE)))
            )
    stable = None
    for index in range(len(candidates) - 2):
        run = candidates[index : index + 3]
        starts = [item[0] for item in run]
        frequencies = [item[1] for item in run]
        if (
            starts[1] - starts[0] == SAMPLE_RATE // 20
            and starts[2] - starts[1] == SAMPLE_RATE // 20
            and max(frequencies) - min(frequencies) <= 80.0
        ):
            stable = run[0]
            break
    if stable is None:
        raise RuntimeError("proof output contains no objectively audible fixture region")
    audible_start, frequency = stable
    return frequency, audible_start / SAMPLE_RATE


def ffprobe_output(output_path: Path, ffprobe: str) -> dict[str, object]:
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,bit_rate:format=duration,bit_rate",
            "-of",
            "json",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise RuntimeError(f"ffprobe rejected proof output: {probe.stdout}")
    return json.loads(probe.stdout)


def verify_metadata_log(
    log_text: str,
    events: tuple[PlaybackEvent, ...],
    results: list[StreamingResult],
) -> list[float]:
    start_lines = [line for line in log_text.splitlines() if "START event_id=" in line]
    end_lines = [line for line in log_text.splitlines() if "END event_id=" in line]
    if len(start_lines) != len(events) or len(end_lines) != len(events):
        raise RuntimeError("Liquidsoap did not log one start and end for every event")

    applied_offsets = []
    for event, result, line in zip(events, results, start_lines, strict=True):
        required = (
            f"event_id={result.event_id}",
            f"media_type={event.media_type.value}",
            f"path={Path(event.media_path).resolve()}",
            f"title={event.display_title}",
            f"station={event.station_name}",
            f"artist={event.artist or ''}",
            f"associated_song={event.associated_song_title or ''}",
        )
        if not all(value in line for value in required):
            raise RuntimeError(f"Liquidsoap metadata log mismatch: {line}")
        offset_match = re.search(
            r" requested_offset=([0-9.eE+-]+) applied_offset=([0-9.eE+-]+)$",
            line,
        )
        if offset_match is None:
            raise RuntimeError(f"Liquidsoap offset log is malformed: {line}")
        requested_offset, applied_offset = map(float, offset_match.groups())
        if not math.isclose(requested_offset, event.start_offset, abs_tol=0.001):
            raise RuntimeError(f"Liquidsoap received the wrong offset: {line}")
        if not math.isclose(applied_offset, event.start_offset, abs_tol=0.05):
            raise RuntimeError(f"Liquidsoap applied the wrong offset: {line}")
        applied_offsets.append(applied_offset)
    return applied_offsets


def run_sequence_probe(
    root: Path,
    output_path: Path,
    *,
    initial_format: str,
    liquidsoap: str,
    ffmpeg: str,
    ffprobe: str,
) -> dict[str, object]:
    fixture_root = root / f"fixtures-{initial_format}"
    fixture_root.mkdir()
    events = build_proof_events(
        fixture_root,
        initial_format=initial_format,
        ffmpeg=ffmpeg,
    )
    if events[0].start_offset <= CUE_DURATION / 2:
        raise RuntimeError("seeded cue did not select the distinguishable high-tone region")
    if any(event.start_offset != 0.0 for event in events[1:]):
        raise RuntimeError("a later proof event unexpectedly has a cue offset")

    socket_path = root / f"sequence-{initial_format}.sock"
    log_path = root / f"sequence-{initial_format}.log"
    with LiquidsoapStreamingAdapter(
        "tcp:127.0.0.1:0" if os.environ.get("DCR_PROOF_TCP") == "1" else socket_path,
        start_timeout=10.0,
        result_timeout=10.0,
        event_wait_timeout=0.25,
    ) as adapter:
        socket_path = adapter.socket_path
        runtime = start_liquidsoap(
            adapter, socket_path, output_path, log_path, liquidsoap
        )
        pre_event_size = output_path.stat().st_size
        try:
            results = [adapter.play(event) for event in events]
            if not all(result.completed for result in results):
                raise RuntimeError(f"Liquidsoap sequence failed: {results!r}")
            for result in results:
                assert_result_timing(result)

            size_after_events = output_path.stat().st_size
            time.sleep(0.75)
            if runtime.process.poll() is not None:
                raise RuntimeError("Liquidsoap output stopped after the event sequence")
            size_after_fallback = output_path.stat().st_size
            if pre_event_size <= 0:
                raise RuntimeError("encoded fallback did not start before submission")
        finally:
            runtime.stop()

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    applied_offsets = verify_metadata_log(log_text, events, results)
    frequency, audible_start = decode_frequency(output_path, ffmpeg)
    if not 780.0 <= frequency <= 980.0:
        raise RuntimeError(
            f"{initial_format.upper()} cue output began near {frequency:.1f} Hz, "
            f"not the expected {HIGH_FREQUENCY:.0f} Hz region"
        )
    probe = ffprobe_output(output_path, ffprobe)
    initial_elapsed = results[0].finished_at - results[0].started_at
    expected_remaining = CUE_DURATION - events[0].start_offset
    output_duration = float(probe["format"]["duration"])
    expected_media_duration = expected_remaining + 6 * 0.5
    if output_duration <= expected_media_duration + 1.0:
        raise RuntimeError(
            f"encoded duration {output_duration:.3f}s does not include the "
            "deliberate fallback intervals around and between events"
        )
    if not 0.5 <= initial_elapsed <= expected_remaining + 0.75:
        raise RuntimeError(
            f"completion timing {initial_elapsed:.3f}s is inconsistent with "
            f"the cued media duration {expected_remaining:.3f}s"
        )

    return {
        "format": initial_format,
        "event_ids": [result.event_id for result in results],
        "event_types": [event.media_type.value for event in events],
        "cue_seconds": events[0].start_offset,
        "applied_cue_seconds": applied_offsets[0],
        "cue_frequency_hz": frequency,
        "first_audible_output_second": audible_start,
        "initial_completion_seconds": initial_elapsed,
        "expected_cued_media_seconds": expected_remaining,
        "initial_lifecycle_monotonic": {
            "submitted": results[0].submitted_at,
            "delivered": results[0].delivered_at,
            "started": results[0].started_at,
            "finished": results[0].finished_at,
        },
        "initial_delivery_to_start_seconds": (
            results[0].started_at - results[0].delivered_at
        ),
        "pre_event_bytes": pre_event_size,
        "post_sequence_bytes": size_after_events,
        "post_fallback_bytes": size_after_fallback,
        "ffprobe": probe,
    }


def make_song_block(
    song_path: Path,
    intro_path: Path,
    outro_path: Path,
) -> SongBlock:
    song = Song(id=10, track=str(song_path), artist="Runtime Artist")
    return SongBlock(
        song=song,
        intro=Intro(artist=song.artist, song=song.track, intro=str(intro_path)),
        outro=Outro(artist=song.artist, song=song.track, outro=str(outro_path)),
        initial=False,
    )


def make_ad_block(intro_path: Path, ad_path: Path) -> AdvertisementBlock:
    return AdvertisementBlock(
        intro=AdIntro(ad_intro=str(intro_path)),
        advertisement=Ad(ad=str(ad_path)),
    )


def run_failure_probe(
    root: Path,
    *,
    liquidsoap: str,
) -> dict[str, object]:
    valid = root / "failure-valid.wav"
    generate_wav(valid, duration=0.4, frequency=510.0)
    missing = root / "intentionally-missing.wav"
    invalid = root / "invalid-audio.wav"
    invalid.write_text("not an audio stream", encoding="utf-8")
    output = root / "failure-output.mp3"
    log = root / "failure.log"
    socket_path = root / "failure.sock"

    with LiquidsoapStreamingAdapter(
        "tcp:127.0.0.1:0" if os.environ.get("DCR_PROOF_TCP") == "1" else socket_path,
        start_timeout=8.0,
        result_timeout=8.0,
        event_wait_timeout=0.25,
    ) as adapter:
        socket_path = adapter.socket_path
        runtime = start_liquidsoap(adapter, socket_path, output, log, liquidsoap)
        try:
            missing_result = adapter.play(
                PlaybackEvent(str(missing), MediaType.SONG, "missing")
            )
            invalid_result = adapter.play(
                PlaybackEvent(str(invalid), MediaType.SONG, "invalid")
            )
            planner = PlaybackPlanner(lambda _path: 1.0, random.Random(1))
            player = StreamingBlockPlayer(planner, adapter)
            intro_failure = player.play(make_song_block(valid, missing, valid))
            song_failure = player.play(make_song_block(missing, valid, valid))
            outro_failure = player.play(make_song_block(valid, valid, invalid))
            ad_intro_failure = player.play(make_ad_block(missing, valid))
            ad_failure = player.play(make_ad_block(valid, invalid))
        finally:
            runtime.stop()

    if missing_result.status is not StreamingResultStatus.START_FAILED:
        raise RuntimeError(f"missing media result was {missing_result.status.value}")
    if invalid_result.status is not StreamingResultStatus.START_FAILED:
        raise RuntimeError(f"invalid media result was {invalid_result.status.value}")
    expected = {
        "intro_failure": (False, True, True),
        "song_failure": (True, False, None),
        "outro_failure": (True, True, False),
        "ad_intro_failure": (False, None),
        "ad_failure": (True, False),
    }
    actual = {
        "intro_failure": tuple(intro_failure.__dict__.values()),
        "song_failure": tuple(song_failure.__dict__.values()),
        "outro_failure": tuple(outro_failure.__dict__.values()),
        "ad_intro_failure": tuple(ad_intro_failure.__dict__.values()),
        "ad_failure": tuple(ad_failure.__dict__.values()),
    }
    if actual != expected:
        raise RuntimeError(f"runtime outcome mapping mismatch: {actual!r}")
    return {
        "missing_media": missing_result.status.value,
        "invalid_media": invalid_result.status.value,
        **actual,
    }


def run_restart_probe(root: Path, *, liquidsoap: str) -> dict[str, object]:
    long_media = root / "interrupted.wav"
    recovered_media = root / "recovered.wav"
    generate_wav(long_media, duration=3.0, frequency=600.0)
    generate_wav(recovered_media, duration=0.5, frequency=700.0)
    socket_path = root / "restart.sock"

    with LiquidsoapStreamingAdapter(
        "tcp:127.0.0.1:0" if os.environ.get("DCR_PROOF_TCP") == "1" else socket_path,
        start_timeout=10.0,
        result_timeout=10.0,
        event_wait_timeout=0.25,
    ) as adapter:
        socket_path = adapter.socket_path
        first_log = root / "restart-first.log"
        first_runtime = start_liquidsoap(
            adapter,
            socket_path,
            root / "restart-first.mp3",
            first_log,
            liquidsoap,
        )
        holder: dict[str, StreamingResult] = {}

        def play_interrupted() -> None:
            holder["result"] = adapter.play(
                PlaybackEvent(str(long_media), MediaType.SONG, "interrupted")
            )

        playback = threading.Thread(target=play_interrupted, daemon=True)
        playback.start()
        wait_until(
            lambda: first_log.exists()
            and "START event_id="
            in first_log.read_text(encoding="utf-8", errors="replace"),
            timeout=10.0,
            reason="the interrupted event to start",
        )
        first_runtime.stop()
        playback.join(timeout=5.0)
        if playback.is_alive():
            raise RuntimeError("source termination did not wake Python playback")
        interrupted = holder["result"]
        if interrupted.status is not StreamingResultStatus.CONNECTION_LOST:
            raise RuntimeError(f"termination result was {interrupted.status.value}")

        second_runtime = start_liquidsoap(
            adapter,
            socket_path,
            root / "restart-second.mp3",
            root / "restart-second.log",
            liquidsoap,
        )
        try:
            recovered = adapter.play(
                PlaybackEvent(str(recovered_media), MediaType.SONG, "recovered")
            )
        finally:
            second_runtime.stop()
        if not recovered.completed:
            raise RuntimeError(f"restarted Liquidsoap result was {recovered.status.value}")

    return {
        "termination": interrupted.status.value,
        "restart": recovered.status.value,
    }


def run_liquidsoap_proof(output_path: Path) -> int:
    liquidsoap = shutil.which("liquidsoap")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if liquidsoap is None or ffmpeg is None or ffprobe is None:
        raise RuntimeError("liquidsoap, ffmpeg, and ffprobe are required")

    output_path = output_path.resolve()
    mp3_cue_output = output_path.with_name(f"{output_path.stem}-mp3-cue.mp3")
    with tempfile.TemporaryDirectory(prefix="dcr-liquidsoap-runtime-") as temp:
        root = Path(temp)
        wav_report = run_sequence_probe(
            root,
            output_path,
            initial_format="wav",
            liquidsoap=liquidsoap,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        mp3_report = run_sequence_probe(
            root,
            mp3_cue_output,
            initial_format="mp3",
            liquidsoap=liquidsoap,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        failure_report = run_failure_probe(root, liquidsoap=liquidsoap)
        restart_report = run_restart_probe(root, liquidsoap=liquidsoap)

    print(
        json.dumps(
            {
                "wav_sequence": wav_report,
                "mp3_sequence": mp3_report,
                "failures": failure_report,
                "restart": restart_report,
                "outputs": [str(output_path), str(mp3_cue_output)],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--liquidsoap",
        action="store_true",
        help="run WAV/MP3 cue, metadata, fallback, failure, and restart proofs",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/dcr-streaming-proof.mp3"),
        help="persistent encoded WAV-cue proof output path",
    )
    args = parser.parse_args(argv)
    try:
        if args.liquidsoap:
            return run_liquidsoap_proof(args.output)
        return run_proof()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"streaming proof failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
