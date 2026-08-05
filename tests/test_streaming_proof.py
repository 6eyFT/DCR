import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from playback_events import MediaType, STATION_NAME
from streaming_proof import build_proof_events, run_proof


class DeterministicProofSequenceTests(unittest.TestCase):
    def test_generated_fixture_sequence_has_required_order_metadata_and_offsets(self):
        with TemporaryDirectory() as temp:
            events = build_proof_events(Path(temp))

            self.assertEqual(
                [event.media_type for event in events],
                [
                    MediaType.SONG,
                    MediaType.OUTRO,
                    MediaType.INTRO,
                    MediaType.SONG,
                    MediaType.OUTRO,
                    MediaType.ADVERTISEMENT_INTRO,
                    MediaType.ADVERTISEMENT,
                ],
            )
            self.assertTrue(all(Path(event.media_path).is_file() for event in events))
            self.assertTrue(all(event.station_name == STATION_NAME for event in events))
            self.assertGreater(events[0].start_offset, 0.0)
            self.assertLess(events[0].start_offset, 0.2)
            self.assertTrue(all(event.start_offset == 0.0 for event in events[1:]))
            self.assertEqual(events[0].artist, "Initial Artist")
            self.assertEqual(events[0].associated_song_title, "initial song")
            self.assertIsNone(events[-1].artist)
            self.assertIsNone(events[-1].associated_song_title)

    def test_fixture_sequence_is_deterministic(self):
        with TemporaryDirectory() as first_temp, TemporaryDirectory() as second_temp:
            first = build_proof_events(Path(first_temp))
            second = build_proof_events(Path(second_temp))

            self.assertEqual(
                [event.start_offset for event in first],
                [event.start_offset for event in second],
            )
            self.assertEqual(
                [event.display_title for event in first],
                [event.display_title for event in second],
            )

    def test_transport_only_proof_completes_without_private_audio(self):
        self.assertEqual(run_proof(), 0)


if __name__ == "__main__":
    unittest.main()
