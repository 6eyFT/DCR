import random
import sys
import time

import pygame

from audio_runtime import AudioInitializationError, consume_dummy_audio_request, initialize_audio
from catalog_loader import CatalogValidationError, load_catalogs, resolve_project_path
from station_scheduler import (
    AdvertisementBlock,
    AdvertisementPlaybackOutcome,
    SongPlaybackOutcome,
    StationScheduler,
)


class RadioApp:
    def __init__(self, dummy_audio_requested=False, random_source=None):
        initialize_audio("Diamond City Radio", dummy_audio_requested=dummy_audio_requested)

        catalogs = load_catalogs()
        self.scheduler = StationScheduler(
            catalogs,
            random_source if random_source is not None else random.Random(),
        )

    def play_audio(self, track):
        print(f"Now playing: {track}")
        resolved_track = resolve_project_path(track)

        if not resolved_track.exists():
            print(f"Missing audio file: {resolved_track}")
            return False

        try:
            pygame.mixer.music.load(str(resolved_track))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(1)
        except pygame.error as error:
            print(f"Could not play {resolved_track}: {error}")
            return False

        return True

    def play_scheduled_block(self, block):
        if isinstance(block, AdvertisementBlock):
            self._play_advertisement_block(block)
        else:
            self._play_song_block(block)

    def _play_song_block(self, block):
        if block.initial:
            print(f"Starting with a random song: {block.song.track}")

        intro_completed = None
        if block.intro is not None:
            intro_completed = self.play_audio(block.intro.intro)

        song_completed = self.play_audio(block.song.track)
        outro_completed = None
        if song_completed and block.outro is not None:
            outro_completed = self.play_audio(block.outro.outro)

        self.scheduler.report_outcome(
            block,
            SongPlaybackOutcome(
                intro_completed=intro_completed,
                song_completed=song_completed,
                outro_completed=outro_completed,
            ),
        )

    def _play_advertisement_block(self, block):
        print(f"Now playing ad intro: '{block.intro.ad_intro}'")
        intro_completed = self.play_audio(block.intro.ad_intro)
        if not intro_completed:
            self.scheduler.report_outcome(
                block,
                AdvertisementPlaybackOutcome(
                    intro_completed=False,
                    advertisement_completed=None,
                ),
            )
            return

        print(f"--- Playing Ad: '{block.advertisement.ad}' ---")
        advertisement_completed = self.play_audio(block.advertisement.ad)
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
