import random
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import pygame
from PIL import Image, ImageTk

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
        root,
        dummy_audio_requested=False,
        random_source=None,
        playback_random_source=None,
        duration_provider=None,
    ):
        initialize_audio("Diamond City Radio GUI", dummy_audio_requested=dummy_audio_requested)

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
        self.playing = False
        self.current_track_length = 0

        self.root = root
        self.root.title("Diamond City Radio Player")
        self.root.geometry("600x425")

        self.gif_frames = self.load_gif_frames("assets/lofi.gif")
        self.current_frame_index = 0

        self.gif_label = tk.Label(root)
        self.gif_label.pack()
        self.update_gif()

        bottom_frame = tk.Frame(root)
        bottom_frame.pack(side="bottom", fill="x", padx=10, pady=10)

        self.volume_slider = ttk.Scale(
            bottom_frame,
            from_=0,
            to=1,
            orient="horizontal",
            command=self.set_volume,
        )
        self.volume_slider.set(0.5)
        self.volume_slider.pack(side="left")

        self.current_track_label = ttk.Label(root, text="Current Track: None", font=("Helvetica", 14))
        self.current_track_label.pack(pady=10)

        self.current_time_label = ttk.Label(bottom_frame, text="0:00 / 0:00", font=("Helvetica", 10))
        self.current_time_label.pack(side="right")

        self.play_button = ttk.Button(root, text="Tune In", command=self.play_radio)
        self.play_button.pack(pady=10)

        pygame.mixer.music.set_volume(0.5)

    def load_gif_frames(self, gif_path, target_size=(240, 240)):
        resolved_gif_path = resolve_project_path(gif_path)
        if not resolved_gif_path.exists():
            print(f"Missing GIF asset: {resolved_gif_path}")
            return []

        frames = []
        gif = Image.open(resolved_gif_path)
        try:
            while True:
                resized_frame = gif.resize(target_size, Image.Resampling.LANCZOS)
                frames.append(ImageTk.PhotoImage(resized_frame))
                gif.seek(len(frames))
        except EOFError:
            pass
        return frames

    def update_gif(self):
        if self.gif_frames:
            frame = self.gif_frames[self.current_frame_index]
            self.gif_label.config(image=frame)
            self.current_frame_index = (self.current_frame_index + 1) % len(self.gif_frames)
            self.root.after(100, self.update_gif)

    def set_volume(self, volume):
        pygame.mixer.music.set_volume(float(volume))

    def update_current_track(self, display_title):
        self.root.after(
            0,
            lambda: self.current_track_label.config(
                text=f"Current Track: {display_title}"
            ),
        )

    def update_track_time(self):
        if self.playing:
            if pygame.mixer.music.get_busy():
                current_time = pygame.mixer.music.get_pos() / 1000
                minutes, seconds = divmod(int(current_time), 60)
                current_time_str = f"{minutes}:{seconds:02}"

                total_minutes, total_seconds = divmod(int(self.current_track_length), 60)
                total_time_str = f"{total_minutes}:{total_seconds:02}"
                self.current_time_label.config(text=f"{current_time_str} / {total_time_str}")
            self.root.after(500, self.update_track_time)

    def play_radio(self):
        if not self.playing:
            self.playing = True
            self.radio_thread = threading.Thread(target=self.radio_loop, daemon=True)
            self.radio_thread.start()
            self.update_track_time()

    def radio_loop(self):
        try:
            while self.playing:
                self.play_scheduled_block(self.scheduler.next_block())
        except Exception as error:
            self.playing = False
            print(f"Error: {error}")

    def play_event(self, event):
        self.update_current_track(event.display_title)
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
            self.current_track_length = pygame.mixer.Sound(str(resolved_track)).get_length()
            while pygame.mixer.music.get_busy() and self.playing:
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


def main(argv=None):
    dummy_audio_requested, remaining_args = consume_dummy_audio_request(argv)
    if argv is None:
        sys.argv = [sys.argv[0], *remaining_args]

    root = None
    try:
        initialize_audio("Diamond City Radio GUI", dummy_audio_requested=dummy_audio_requested)
        root = tk.Tk()
        radio_app = RadioApp(root, dummy_audio_requested=dummy_audio_requested)
    except (AudioInitializationError, CatalogValidationError) as error:
        if root is not None:
            root.destroy()
        print(error, file=sys.stderr)
        return 1

    radio_app.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
