import random
import sys
import time

import pygame

from audio_runtime import AudioInitializationError, consume_dummy_audio_request, initialize_audio
from catalog_loader import CatalogValidationError, load_catalogs, resolve_project_path
from playback_events import PlaybackPlanner
from block_player import BlockPlayer
from pygame_duration import PygameDurationProvider
from station_scheduler import StationScheduler


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
        outcome = BlockPlayer(self.playback_planner, self.play_event).play(block)
        self.scheduler.report_outcome(block, outcome)

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
