import random
import sys
import time

import pygame

from audio_runtime import AudioInitializationError, consume_dummy_audio_request, initialize_audio
from catalog_loader import CatalogValidationError, load_catalogs, resolve_project_path
from playback_events import MediaType, PlaybackPlanner
from pygame_duration import PygameDurationProvider
from station_scheduler import (
    AdvertisementBlock,
    AdvertisementPlaybackOutcome,
    SongPlaybackOutcome,
    StationScheduler,
)


class RadioApp:
    def __init__(
        self,
        dummy_audio_requested=False,
        random_source=None,
        playback_random_source=None,
        duration_provider=None,
    ):
        initialize_audio("Diamond City Radio", dummy_audio_requested=dummy_audio_requested)

        catalogs = load_catalogs()
        self.scheduler = StationScheduler(
            catalogs,
            random_source if random_source is not None else random.Random(),
        )
        self.playback_planner = PlaybackPlanner(
            duration_provider
            if duration_provider is not None
            else PygameDurationProvider(),
            playback_random_source
            if playback_random_source is not None
            else random.Random(),
        )

    def play_event(self, event):
        offset_suffix = (
            f" from {event.start_offset:.3f}s" if event.start_offset else ""
        )
        print(
            f"Now attempting {event.media_type.value}: "
            f"{event.display_title}{offset_suffix}"
        )
        resolved_track = resolve_project_path(event.media_path)

        if not resolved_track.exists():
            print(f"Missing audio file: {resolved_track}")
            return False

        try:
            pygame.mixer.music.load(str(resolved_track))
            if event.start_offset:
                pygame.mixer.music.play(start=event.start_offset)
            else:
                pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(1)
        except pygame.error as error:
            print(
                f"Could not play {event.media_type.value.lower()} "
                f"'{event.display_title}' from {event.start_offset:.3f}s: {error}"
            )
            return False

        return True

    def play_scheduled_block(self, block):
        if isinstance(block, AdvertisementBlock):
            self._play_advertisement_block(block)
        else:
            self._play_song_block(block)

    def _play_song_block(self, block):
        events = self.playback_planner.plan(block)
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
            intro_completed = self.play_event(intro_event)

        song_completed = self.play_event(song_event)
        outro_completed = None
        if song_completed and outro_event is not None:
            outro_completed = self.play_event(outro_event)

        self.scheduler.report_outcome(
            block,
            SongPlaybackOutcome(
                intro_completed=intro_completed,
                song_completed=song_completed,
                outro_completed=outro_completed,
            ),
        )

    def _play_advertisement_block(self, block):
        intro_event, advertisement_event = self.playback_planner.plan(block)
        intro_completed = self.play_event(intro_event)
        if not intro_completed:
            self.scheduler.report_outcome(
                block,
                AdvertisementPlaybackOutcome(
                    intro_completed=False,
                    advertisement_completed=None,
                ),
            )
            return

        advertisement_completed = self.play_event(advertisement_event)
        self.scheduler.report_outcome(
            block,
            AdvertisementPlaybackOutcome(
                intro_completed=True,
                advertisement_completed=advertisement_completed,
            ),
        )

    def autoplay(self):
        print("Radio is now simulating...")

        while True:
            self.play_scheduled_block(self.scheduler.next_block())


def main(argv=None):
    dummy_audio_requested, remaining_args = consume_dummy_audio_request(argv)
    if argv is None:
        sys.argv = [sys.argv[0], *remaining_args]

    try:
        radio_app = RadioApp(dummy_audio_requested=dummy_audio_requested)
    except (AudioInitializationError, CatalogValidationError) as error:
        print(error, file=sys.stderr)
        return 1

    radio_app.autoplay()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
