import json
from http.client import HTTPConnection
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import unittest

from demo_station import make_demo
from playback_events import MediaType, PlaybackEvent
from station_web import Station, StationServer
from streaming_adapter import LiquidsoapStreamingAdapter, send_bridge_command
from tests.test_streaming_adapter import AsyncSubmission


class PrivateControlTests(unittest.TestCase):
    def test_control_authentication_and_confirmed_metadata(self):
        with LiquidsoapStreamingAdapter("tcp:127.0.0.1:0", token="test-secret") as adapter:
            endpoint = adapter.socket_path
            self.assertEqual(send_bridge_command(endpoint, {"command": "next"})["type"], "error")
            event = PlaybackEvent("/private/secret.wav", MediaType.SONG, "Test", artist="Artist")
            submission = AsyncSubmission(adapter, event)
            self.assertIsNone(adapter.now_playing())
            response = send_bridge_command(endpoint, {"command": "next"}, token="test-secret")
            self.assertIsNone(adapter.now_playing())
            send_bridge_command(endpoint, {"command": "started", "event_id": response["event_id"]}, token="test-secret")
            snapshot = adapter.now_playing()
            self.assertEqual(snapshot["title"], "Test")
            self.assertNotIn("private", json.dumps(snapshot))
            self.assertNotIn("media_path", snapshot)
            send_bridge_command(endpoint, {"command": "result", "event_id": response["event_id"], "status": "completed"}, token="test-secret")
            self.assertTrue(submission.finish().completed)
            self.assertIsNone(adapter.now_playing())

    def test_control_refuses_non_loopback_address(self):
        with self.assertRaises(ValueError):
            LiquidsoapStreamingAdapter("tcp:0.0.0.0:4000")

    def test_unix_transport_remains_supported_where_available(self):
        try:
            probe = socket.socket(socket.AF_UNIX)
        except PermissionError:
            self.skipTest("Execution environment disallows AF_UNIX")
        probe.close()
        with TemporaryDirectory() as root:
            path = Path(root) / "control.sock"
            with LiquidsoapStreamingAdapter(path):
                self.assertTrue(path.exists())
            self.assertFalse(path.exists())


class PrivateRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        media = root / "demo"
        media.mkdir()
        make_demo(media, song_seconds=0.2)
        self.station = Station(media, root, demo=True, seed=7)
        self.server = StationServer(0, self.station)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()
        self.station.close()
        self.temp.cleanup()

    def request(self, path, headers=None):
        client = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        client.request("GET", path, headers=headers or {})
        response = client.getresponse()
        result = response.status, response.read(), dict(response.headers)
        client.close()
        return result

    def test_allowlist_does_not_serve_catalogs_assets_or_paths(self):
        for path in ("/assets/lofi.gif", "/data/songs.json", "/../station_web.py",
                     "/%2e%2e/station_web.py", "/streaming_bridge.py", "/admin"):
            self.assertEqual(self.request(path)[0], 404, path)
        status, body, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Tune In", body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_rebinding_and_cross_site_requests_are_rejected(self):
        self.assertEqual(self.request("/", {"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("/stream", {"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_listener_requests_do_not_select_or_complete_blocks(self):
        for _ in range(3):
            status, body, _ = self.request("/api/now")
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["demo"])
        first = self.station.scheduler.next_block()
        self.assertTrue(first.initial)

    def test_stopped_station_rejects_listening(self):
        self.station.stop.set()
        self.assertEqual(self.request("/stream")[0], 503)


if __name__ == "__main__":
    unittest.main()
