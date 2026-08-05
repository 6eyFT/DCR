import random
import unittest

from catalog_loader import Ad, AdIntro, Intro, Outro, Song
from playback_events import PlaybackPlanner
from station_scheduler import (
    AdvertisementBlock,
    AdvertisementPlaybackOutcome,
    SongBlock,
    SongPlaybackOutcome,
)
from streaming_adapter import StreamingResult, StreamingResultStatus
from streaming_block_player import StreamingBlockPlayer


def song_block():
    song = Song(id=1, track="song.wav", artist="Artist")
    return SongBlock(
        song=song,
        intro=Intro(artist=song.artist, song=song.track, intro="intro.wav"),
        outro=Outro(artist=song.artist, song=song.track, outro="outro.wav"),
        initial=False,
    )


def advertisement_block():
    return AdvertisementBlock(
        intro=AdIntro(ad_intro="ad-intro.wav"),
        advertisement=Ad(ad="ad.wav"),
    )


class ResultAdapter:
    def __init__(self, statuses):
        self._statuses = iter(statuses)
        self.events = []

    def play(self, event):
        self.events.append(event)
        status = next(self._statuses)
        return StreamingResult(
            event_id=f"test-{len(self.events)}",
            status=status,
        )

    def close(self):
        pass


def player(statuses):
    adapter = ResultAdapter(statuses)
    planner = PlaybackPlanner(lambda _path: 100.0, random.Random(1))
    return StreamingBlockPlayer(planner, adapter), adapter


class SongOutcomeMappingTests(unittest.TestCase):
    def test_intro_failure_continues_to_song(self):
        block_player, adapter = player(
            [
                StreamingResultStatus.START_FAILED,
                StreamingResultStatus.COMPLETED,
                StreamingResultStatus.COMPLETED,
            ]
        )

        outcome = block_player.play(song_block())

        self.assertEqual(
            outcome,
            SongPlaybackOutcome(False, True, True),
        )
        self.assertEqual([event.media_path for event in adapter.events], ["intro.wav", "song.wav", "outro.wav"])

    def test_song_failure_skips_outro_and_does_not_count_as_completed(self):
        block_player, adapter = player(
            [
                StreamingResultStatus.COMPLETED,
                StreamingResultStatus.INTERRUPTED,
            ]
        )

        outcome = block_player.play(song_block())

        self.assertEqual(outcome, SongPlaybackOutcome(True, False, None))
        self.assertEqual([event.media_path for event in adapter.events], ["intro.wav", "song.wav"])

    def test_outro_failure_leaves_song_completed(self):
        block_player, _adapter = player(
            [
                StreamingResultStatus.COMPLETED,
                StreamingResultStatus.COMPLETED,
                StreamingResultStatus.CONNECTION_LOST,
            ]
        )

        outcome = block_player.play(song_block())

        self.assertEqual(outcome, SongPlaybackOutcome(True, True, False))


class AdvertisementOutcomeMappingTests(unittest.TestCase):
    def test_advertisement_intro_failure_skips_advertisement(self):
        block_player, adapter = player([StreamingResultStatus.START_FAILED])

        outcome = block_player.play(advertisement_block())

        self.assertEqual(outcome, AdvertisementPlaybackOutcome(False, None))
        self.assertEqual([event.media_path for event in adapter.events], ["ad-intro.wav"])

    def test_advertisement_failure_does_not_complete_rotation_item(self):
        block_player, adapter = player(
            [
                StreamingResultStatus.COMPLETED,
                StreamingResultStatus.INTERRUPTED,
            ]
        )

        outcome = block_player.play(advertisement_block())

        self.assertEqual(outcome, AdvertisementPlaybackOutcome(True, False))
        self.assertEqual(
            [event.media_path for event in adapter.events],
            ["ad-intro.wav", "ad.wav"],
        )


if __name__ == "__main__":
    unittest.main()
