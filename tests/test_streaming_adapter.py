import ast
import socket
import threading
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory

import streaming_adapter
from playback_events import MediaType, PlaybackEvent
from streaming_adapter import (
    LiquidsoapStreamingAdapter,
    control_address,
    StreamingResultStatus,
    deserialize_event,
    send_bridge_command,
    serialize_event,
)
from streaming_bridge import liquidsoap_request_uri


def event(
    path="assets/songs/Example Song.wav",
    *,
    media_type=MediaType.SONG,
    title="Example Song",
    offset=0.0,
):
    return PlaybackEvent(
        media_path=path,
        media_type=media_type,
        display_title=title,
        station_name="Diamond City Radio",
        artist='Artist "Six" \\ Radio ☢',
        associated_song_title="Song, Part: One\nLive",
        start_offset=offset,
    )


class AsyncSubmission:
    def __init__(self, adapter, playback_event):
        self.result = None
        self.error = None

        def submit():
            try:
                self.result = adapter.play(playback_event)
            except Exception as error:  # captured for the test thread
                self.error = error

        self.thread = threading.Thread(target=submit, daemon=True)
        self.thread.start()

    def finish(self):
        self.thread.join(timeout=2.0)
        if self.thread.is_alive():
            raise AssertionError("adapter submission did not finish")
        if self.error is not None:
            raise self.error
        return self.result


class EventSerializationTests(unittest.TestCase):
    def test_every_playback_event_field_round_trips(self):
        original = event(
            'assets/songs/Space #1, "quoted" ☢.MP3',
            title='Space #1, "quoted" ☢',
            offset=12.75,
        )

        restored = deserialize_event(serialize_event(original))

        self.assertEqual(restored, original)

    def test_serialized_event_metadata_is_immutable_after_reconstruction(self):
        restored = deserialize_event(serialize_event(event()))

        with self.assertRaises(FrozenInstanceError):
            restored.display_title = "changed"

    def test_liquidsoap_request_uri_escapes_path_and_metadata(self):
        original = event(
            'assets/songs/Space #1, "quoted" ☢.MP3',
            title='A "quoted" title \\ with ☢',
            offset=9.25,
        )

        uri = liquidsoap_request_uri(
            "dcr-00000001",
            serialize_event(original),
            project_root="/tmp/Diamond City Radio",
        )

        self.assertTrue(uri.startswith("annotate:"))
        self.assertIn('dcr_event_id="dcr-00000001"', uri)
        self.assertIn('dcr_media_path="/tmp/Diamond City Radio/assets/songs/', uri)
        self.assertIn('dcr_start_offset="9.25"', uri)
        self.assertIn('title="A \\"quoted\\" title \\\\ with ☢"', uri)
        self.assertIn('Space #1, "quoted" ☢.MP3', uri)
        self.assertNotIn("\nLive\n", uri)

    def test_nonzero_and_zero_offsets_are_transmitted_without_change(self):
        self.assertEqual(
            deserialize_event(serialize_event(event(offset=41.125))).start_offset,
            41.125,
        )
        self.assertEqual(
            deserialize_event(serialize_event(event(offset=0.0))).start_offset,
            0.0,
        )


class SocketBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.socket_path = Path(self.temp.name) / "station.sock"
        self.adapter = LiquidsoapStreamingAdapter(
            "tcp:127.0.0.1:0",
            start_timeout=0.25,
            result_timeout=0.25,
            event_wait_timeout=0.25,
        )
        self.socket_path = self.adapter.socket_path

    def tearDown(self):
        self.adapter.close()
        self.temp.cleanup()

    def fetch(self):
        response = send_bridge_command(
            self.socket_path,
            {"command": "next"},
            timeout=1.0,
        )
        self.assertEqual(response["type"], "event")
        return response

    def start(self, event_id):
        return send_bridge_command(
            self.socket_path,
            {"command": "started", "event_id": event_id},
        )

    def result(self, event_id, status, detail=None):
        return send_bridge_command(
            self.socket_path,
            {
                "command": "result",
                "event_id": event_id,
                "status": status.value,
                "detail": detail,
            },
        )

    def test_completion_response_returns_to_python(self):
        submission = AsyncSubmission(self.adapter, event())
        fetched = self.fetch()
        self.start(fetched["event_id"])
        self.result(fetched["event_id"], StreamingResultStatus.COMPLETED)

        result = submission.finish()

        self.assertEqual(result.status, StreamingResultStatus.COMPLETED)
        self.assertTrue(result.completed)
        self.assertLessEqual(result.submitted_at, result.delivered_at)
        self.assertLessEqual(result.delivered_at, result.started_at)
        self.assertLessEqual(result.started_at, result.finished_at)

    def test_long_poll_does_not_block_lifecycle_callback(self):
        submission = AsyncSubmission(self.adapter, event())
        fetched = self.fetch()
        self.start(fetched["event_id"])

        waiting_response = {}

        def wait_for_next():
            waiting_response.update(
                send_bridge_command(
                    self.socket_path,
                    {"command": "next"},
                    timeout=1.0,
                )
            )

        long_poll = threading.Thread(target=wait_for_next, daemon=True)
        long_poll.start()
        time.sleep(0.02)
        self.result(fetched["event_id"], StreamingResultStatus.COMPLETED)

        self.assertTrue(submission.finish().completed)
        long_poll.join(timeout=1.0)
        self.assertEqual(waiting_response["type"], "no_event")

    def test_start_failure_returns_to_python(self):
        submission = AsyncSubmission(self.adapter, event())
        fetched = self.fetch()
        self.result(
            fetched["event_id"],
            StreamingResultStatus.START_FAILED,
            "decoder rejected media",
        )

        result = submission.finish()

        self.assertEqual(result.status, StreamingResultStatus.START_FAILED)
        self.assertEqual(result.detail, "decoder rejected media")

    def test_delivered_event_without_started_callback_times_out_as_start_failure(self):
        submission = AsyncSubmission(self.adapter, event())
        self.fetch()

        result = submission.finish()

        self.assertEqual(result.status, StreamingResultStatus.START_FAILED)

    def test_interrupted_playback_returns_to_python(self):
        submission = AsyncSubmission(self.adapter, event())
        fetched = self.fetch()
        self.start(fetched["event_id"])
        self.result(
            fetched["event_id"],
            StreamingResultStatus.INTERRUPTED,
            "source skipped the track",
        )

        result = submission.finish()

        self.assertEqual(result.status, StreamingResultStatus.INTERRUPTED)

    def test_explicit_source_connection_loss_returns_to_python(self):
        submission = AsyncSubmission(self.adapter, event())
        fetched = self.fetch()
        self.start(fetched["event_id"])
        send_bridge_command(
            self.socket_path,
            {"command": "source_lost", "detail": "control channel closed"},
        )

        result = submission.finish()

        self.assertEqual(result.status, StreamingResultStatus.CONNECTION_LOST)
        self.assertEqual(result.detail, "control channel closed")

    def test_next_event_can_complete_after_reported_source_loss(self):
        lost_submission = AsyncSubmission(self.adapter, event(title="Lost event"))
        lost = self.fetch()
        self.start(lost["event_id"])
        send_bridge_command(
            self.socket_path,
            {"command": "source_lost", "detail": "engine restarted"},
        )
        self.assertEqual(
            lost_submission.finish().status,
            StreamingResultStatus.CONNECTION_LOST,
        )

        recovered_submission = AsyncSubmission(
            self.adapter,
            event(title="Recovered event"),
        )
        recovered = self.fetch()
        self.start(recovered["event_id"])
        self.result(recovered["event_id"], StreamingResultStatus.COMPLETED)

        self.assertTrue(recovered_submission.finish().completed)

    def test_source_that_stops_reporting_does_not_block_forever(self):
        submission = AsyncSubmission(self.adapter, event())
        fetched = self.fetch()
        self.start(fetched["event_id"])

        result = submission.finish()

        self.assertEqual(result.status, StreamingResultStatus.CONNECTION_LOST)
        self.assertIn("stopped reporting", result.detail)

    def test_broker_accepts_reconnection_after_dropped_control_client(self):
        family, address = control_address(self.socket_path)
        with socket.socket(family, socket.SOCK_STREAM) as dropped:
            dropped.connect(address)
            dropped.sendall(b'{"protocol_version": 1, "command":')

        submission = AsyncSubmission(self.adapter, event())
        fetched = self.fetch()
        self.start(fetched["event_id"])
        self.result(fetched["event_id"], StreamingResultStatus.COMPLETED)

        self.assertTrue(submission.finish().completed)

    def test_absent_source_times_out_as_connection_loss(self):
        result = self.adapter.play(event())

        self.assertEqual(result.status, StreamingResultStatus.CONNECTION_LOST)

    def test_missing_media_can_be_returned_as_start_failure(self):
        missing = str(Path(self.temp.name) / "missing.wav")
        submission = AsyncSubmission(self.adapter, event(missing))
        fetched = self.fetch()
        received = deserialize_event(fetched["event"])
        self.assertFalse(Path(received.media_path).exists())
        self.result(
            fetched["event_id"],
            StreamingResultStatus.START_FAILED,
            "file does not exist",
        )

        result = submission.finish()

        self.assertEqual(result.status, StreamingResultStatus.START_FAILED)
        self.assertIn("does not exist", result.detail)

    def test_order_is_preserved_across_multiple_real_socket_exchanges(self):
        expected = [
            event(f"/tmp/{index}.wav", title=f"Event {index}")
            for index in range(4)
        ]
        received = []

        for expected_event in expected:
            submission = AsyncSubmission(self.adapter, expected_event)
            fetched = self.fetch()
            received.append(deserialize_event(fetched["event"]))
            self.start(fetched["event_id"])
            self.result(fetched["event_id"], StreamingResultStatus.COMPLETED)
            submission.finish()

        self.assertEqual(received, expected)

    def test_clean_shutdown_interrupts_active_event_and_removes_socket(self):
        submission = AsyncSubmission(self.adapter, event())
        fetched = self.fetch()
        self.start(fetched["event_id"])

        self.adapter.close()
        result = submission.finish()

        self.assertEqual(result.status, StreamingResultStatus.INTERRUPTED)
        with self.assertRaises(OSError):
            send_bridge_command(self.socket_path, {"command": "next"})


class SeparationTests(unittest.TestCase):
    def test_adapter_has_no_scheduling_policy_dependency(self):
        tree = ast.parse(Path(streaming_adapter.__file__).read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }

        self.assertNotIn("station_scheduler", imported_modules)
        self.assertFalse(
            any(
                isinstance(node, ast.Import)
                and any(alias.name == "station_scheduler" for alias in node.names)
                for node in ast.walk(tree)
            )
        )


if __name__ == "__main__":
    unittest.main()
