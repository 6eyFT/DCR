"""One audio-independent executor for all station blocks and backends."""

from collections.abc import Callable

from playback_events import MediaType, PlaybackEvent, PlaybackPlanner
from station_scheduler import (
    AdvertisementBlock,
    AdvertisementPlaybackOutcome,
    SongBlock,
    SongPlaybackOutcome,
)


class BlockPlayer:
    """Execute planned events without selecting or counting station content."""

    def __init__(self, planner: PlaybackPlanner, play_event: Callable[[PlaybackEvent], bool]):
        self._planner = planner
        self._play_event = play_event

    def play(self, block):
        if isinstance(block, SongBlock):
            return self._play_song(block)
        if isinstance(block, AdvertisementBlock):
            return self._play_advertisement(block)
        raise TypeError(f"unsupported scheduled block: {type(block).__name__}")

    def _play_song(self, block):
        events = self._planner.plan(block)
        intro_event = next(
            (event for event in events if event.media_type is MediaType.INTRO),
            None,
        )
        song_event = next(
            event for event in events if event.media_type is MediaType.SONG
        )
        outro_event = next(
            (event for event in events if event.media_type is MediaType.OUTRO),
            None,
        )

        intro_completed = None
        if intro_event is not None:
            intro_completed = self._play_event(intro_event)

        song_completed = self._play_event(song_event)
        outro_completed = None
        if song_completed and outro_event is not None:
            outro_completed = self._play_event(outro_event)

        return SongPlaybackOutcome(
            intro_completed=intro_completed,
            song_completed=song_completed,
            outro_completed=outro_completed,
        )

    def _play_advertisement(self, block):
        intro_event, advertisement_event = self._planner.plan(block)
        intro_completed = self._play_event(intro_event)
        if not intro_completed:
            return AdvertisementPlaybackOutcome(
                intro_completed=False,
                advertisement_completed=None,
            )

        return AdvertisementPlaybackOutcome(
            intro_completed=True,
            advertisement_completed=self._play_event(advertisement_event),
        )
