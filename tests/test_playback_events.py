import math
import random
import unittest
from dataclasses import FrozenInstanceError
from unittest import mock

from catalog_loader import Ad, AdIntro, Intro, Outro, Song
from playback_events import (
    STATION_NAME,
    InvalidMediaDurationError,
    MediaType,
    PlaybackEvent,
    PlaybackPlanner,
    filename_title,
)
from pygame_duration import PygameDurationProvider
from station_scheduler import AdvertisementBlock, SongBlock


class FakeDurationProvider:
    def __init__(self, duration):
        self.duration = duration
        self.requests = []

    def __call__(self, media_path):
        self.requests.append(media_path)
        return self.duration


def song_block(*, initial=False, intro=True, outro=True):
    song = Song(
        id=1,
        track="assets/songs/Example Song.mp3",
        artist="Example Artist",
    )
    return SongBlock(
        song=song,
        intro=(
            Intro(
                artist=song.artist,
                song=song.track,
                intro="assets/intros/Example Intro.WAV",
            )
            if intro
            else None
        ),
        outro=(
            Outro(
                artist=song.artist,
                song=song.track,
                outro="assets/outros/Example Outro.wav",
            )
            if outro
            else None
        ),
        initial=initial,
    )


def advertisement_block():
    return AdvertisementBlock(
        intro=AdIntro(ad_intro="assets/ads/Example Ad Intro.wav"),
        advertisement=Ad(ad="assets/ads/Example Advertisement.mp3"),
    )


class PlaybackMetadataTests(unittest.TestCase):
    def test_event_metadata_is_immutable(self):
        event = PlaybackEvent(
            media_path="example.wav",
            media_type=MediaType.SONG,
            display_title="example",
        )

        with self.assertRaises(FrozenInstanceError):
            event.display_title = "changed"

    def test_filename_extension_is_removed_without_file_access(self):
        self.assertEqual(
            filename_title("missing/path/Example.Track.MP3"),
            "Example.Track",
        )

    def test_station_name_and_song_metadata_are_preserved(self):
        planner = PlaybackPlanner(FakeDurationProvider(120.0), random.Random(1))

        events = planner.plan(song_block(initial=False))

        for event in events:
            self.assertEqual(event.station_name, STATION_NAME)
            self.assertEqual(event.artist, "Example Artist")
            self.assertEqual(event.associated_song_title, "Example Song")

    def test_each_media_category_has_its_own_type_and_title(self):
        planner = PlaybackPlanner(FakeDurationProvider(120.0), random.Random(2))

        song_events = planner.plan(song_block(initial=False))
        ad_events = planner.plan(advertisement_block())

        self.assertEqual(
            [(event.media_type, event.display_title) for event in song_events],
            [
                (MediaType.INTRO, "Example Intro"),
                (MediaType.SONG, "Example Song"),
                (MediaType.OUTRO, "Example Outro"),
            ],
        )
        self.assertEqual(
            [(event.media_type, event.display_title) for event in ad_events],
            [
                (MediaType.ADVERTISEMENT_INTRO, "Example Ad Intro"),
                (MediaType.ADVERTISEMENT, "Example Advertisement"),
            ],
        )
        self.assertTrue(all(event.artist is None for event in ad_events))
        self.assertTrue(
            all(event.associated_song_title is None for event in ad_events)
        )


class PlaybackPlanningTests(unittest.TestCase):
    def test_initial_block_order_is_song_then_optional_outro(self):
        planner = PlaybackPlanner(FakeDurationProvider(120.0), random.Random(3))

        events = planner.plan(song_block(initial=True))

        self.assertEqual(
            [event.media_type for event in events],
            [MediaType.SONG, MediaType.OUTRO],
        )

    def test_normal_block_order_is_intro_song_outro(self):
        planner = PlaybackPlanner(FakeDurationProvider(120.0), random.Random(4))

        events = planner.plan(song_block(initial=False))

        self.assertEqual(
            [event.media_type for event in events],
            [MediaType.INTRO, MediaType.SONG, MediaType.OUTRO],
        )

    def test_advertisement_order_is_intro_then_advertisement(self):
        planner = PlaybackPlanner(FakeDurationProvider(120.0), random.Random(5))

        events = planner.plan(advertisement_block())

        self.assertEqual(
            [event.media_type for event in events],
            [MediaType.ADVERTISEMENT_INTRO, MediaType.ADVERTISEMENT],
        )

    def test_missing_optional_clips_produce_no_placeholder_events(self):
        planner = PlaybackPlanner(FakeDurationProvider(120.0), random.Random(6))

        events = planner.plan(song_block(initial=False, intro=False, outro=False))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].media_type, MediaType.SONG)


class InitialOffsetTests(unittest.TestCase):
    def test_initial_song_receives_valid_random_offset(self):
        planner = PlaybackPlanner(FakeDurationProvider(100.0), random.Random(7))

        song_event = planner.plan(song_block(initial=True))[0]

        self.assertGreaterEqual(song_event.start_offset, 0.0)
        self.assertLess(song_event.start_offset, 100.0)
        self.assertNotEqual(song_event.start_offset, 0.0)

    def test_seeded_offset_selection_is_repeatable(self):
        first = PlaybackPlanner(
            FakeDurationProvider(100.0),
            random.Random(8),
        ).plan(song_block(initial=True))[0]
        second = PlaybackPlanner(
            FakeDurationProvider(100.0),
            random.Random(8),
        ).plan(song_block(initial=True))[0]

        self.assertEqual(first.start_offset, second.start_offset)

    def test_only_initial_song_receives_random_offset(self):
        provider = FakeDurationProvider(100.0)
        planner = PlaybackPlanner(provider, random.Random(9))

        initial_events = planner.plan(song_block(initial=True))
        normal_events = planner.plan(song_block(initial=False))
        ad_events = planner.plan(advertisement_block())

        self.assertGreater(initial_events[0].start_offset, 0.0)
        self.assertTrue(
            all(event.start_offset == 0.0 for event in initial_events[1:])
        )
        self.assertTrue(all(event.start_offset == 0.0 for event in normal_events))
        self.assertTrue(all(event.start_offset == 0.0 for event in ad_events))

    def test_duration_is_requested_only_for_initial_song(self):
        provider = FakeDurationProvider(100.0)
        planner = PlaybackPlanner(provider, random.Random(10))

        planner.plan(song_block(initial=False))
        planner.plan(advertisement_block())
        self.assertEqual(provider.requests, [])

        planner.plan(song_block(initial=True))
        self.assertEqual(provider.requests, ["assets/songs/Example Song.mp3"])

    def test_invalid_duration_values_fail_clearly(self):
        invalid_values = (
            None,
            "100",
            True,
            0,
            -1,
            math.inf,
            -math.inf,
            math.nan,
        )

        for value in invalid_values:
            with self.subTest(duration=value):
                planner = PlaybackPlanner(
                    FakeDurationProvider(value),
                    random.Random(11),
                )
                with self.assertRaises(InvalidMediaDurationError) as context:
                    planner.plan(song_block(initial=True))
                self.assertIn("Example Song.mp3", str(context.exception))
                self.assertIn("finite positive number", str(context.exception))


class PygameDurationProviderTests(unittest.TestCase):
    def test_production_provider_resolves_and_caches_duration(self):
        sound = mock.Mock()
        sound.get_length.return_value = 42.5

        with (
            mock.patch("pygame_duration.resolve_project_path", return_value="resolved.wav"),
            mock.patch("pygame_duration.pygame.mixer.Sound", return_value=sound) as load_sound,
        ):
            provider = PygameDurationProvider()
            first = provider("assets/songs/Example.wav")
            second = provider("assets/songs/Example.wav")

        self.assertEqual((first, second), (42.5, 42.5))
        load_sound.assert_called_once_with("resolved.wav")


if __name__ == "__main__":
    unittest.main()
