"""Map streaming event results to existing scheduler playback outcomes."""

from playback_events import MediaType, PlaybackPlanner
from station_scheduler import (
    AdvertisementBlock,
    AdvertisementPlaybackOutcome,
    SongBlock,
    SongPlaybackOutcome,
)
from streaming_adapter import StreamingAdapter


class StreamingBlockPlayer:
    """Execute planned events without selecting or counting station content."""

    def __init__(self, planner: PlaybackPlanner, adapter: StreamingAdapter):
        self._planner = planner
        self._adapter = adapter

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
            intro_completed = self._adapter.play(intro_event).completed

        song_completed = self._adapter.play(song_event).completed
        outro_completed = None
        if song_completed and outro_event is not None:
            outro_completed = self._adapter.play(outro_event).completed

        return SongPlaybackOutcome(
            intro_completed=intro_completed,
            song_completed=song_completed,
            outro_completed=outro_completed,
        )

    def _play_advertisement(self, block):
        intro_event, advertisement_event = self._planner.plan(block)
        intro_completed = self._adapter.play(intro_event).completed
        if not intro_completed:
            return AdvertisementPlaybackOutcome(
                intro_completed=False,
                advertisement_completed=None,
            )

        return AdvertisementPlaybackOutcome(
            intro_completed=True,
            advertisement_completed=self._adapter.play(
                advertisement_event
            ).completed,
        )
