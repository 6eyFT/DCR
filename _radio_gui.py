import os
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import pygame
from PIL import Image, ImageTk

from audio_runtime import AudioInitializationError, consume_dummy_audio_request, initialize_audio
from catalog_loader import CatalogValidationError, asset_exists, load_catalogs, resolve_project_path


class RadioApp:
    def __init__(self, root, dummy_audio_requested=False):
        initialize_audio("Diamond City Radio GUI", dummy_audio_requested=dummy_audio_requested)

        catalogs = load_catalogs()
        self.songs = catalogs.songs
        self.intros = catalogs.intros
        self.outros = catalogs.outros
        self.ads = catalogs.ads
        self.ad_intros = catalogs.ad_intros

        self.ad_interval = 10
        self.cycle_count = 0
        self.song_history = []
        self.ad_history = []
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

    def update_current_track(self, track_name):
        display_name = os.path.splitext(os.path.basename(track_name))[0]
        self.root.after(0, lambda: self.current_track_label.config(text=f"Current Track: {display_name}"))

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
                next_song = self.get_next_song()
                self.update_current_track(next_song.track)
                self.play_intro(next_song)
                self.play_audio(next_song.track)
                self.play_outro(next_song)
                self.cycle_count += 1

                if self.cycle_count >= self.ad_interval:
                    self.play_ad_intro()
                    self.play_ad_break()
                    self.cycle_count = 0
        except Exception as error:
            self.playing = False
            print(f"Error: {error}")

    def play_audio(self, track):
        resolved_track = resolve_project_path(track)
        if not resolved_track.exists():
            print(f"Missing audio file: {resolved_track}")
            return False

        try:
            pygame.mixer.music.load(str(resolved_track))
            pygame.mixer.music.play()
            self.current_track_length = pygame.mixer.Sound(str(resolved_track)).get_length()
            while pygame.mixer.music.get_busy() and self.playing:
                time.sleep(1)
        except pygame.error as error:
            print(f"Could not play {resolved_track}: {error}")
            return False

        return True

    def play_ad_break(self):
        for _ in range(3):
            self.play_ad()

    def play_ad(self):
        available_ads = [
            ad.ad for ad in self.ads if asset_exists(ad.ad) and ad.ad not in self.ad_history
        ]
        if not available_ads:
            self.ad_history = []
            available_ads = [ad.ad for ad in self.ads if asset_exists(ad.ad)]

        if not available_ads:
            print("No ads available to play.")
            return False

        ad_to_play = random.choice(available_ads)
        print(f"--- Playing Ad: '{ad_to_play}' ---")
        played = self.play_audio(ad_to_play)
        if played:
            self.ad_history.insert(0, ad_to_play)
            if len(self.ad_history) > 8:
                self.ad_history.pop()
        return played

    def play_ad_intro(self):
        available_ad_intros = [entry.ad_intro for entry in self.ad_intros if asset_exists(entry.ad_intro)]
        if not available_ad_intros:
            print("No ad intros available to play.")
            return False

        ad_intro_to_play = random.choice(available_ad_intros)
        print(f"Now playing ad intro: '{ad_intro_to_play}'")
        return self.play_audio(ad_intro_to_play)

    def play_intro(self, song):
        artist = song.artist
        song_track = song.track

        intros_for_song = [
            intro.intro
            for intro in self.intros
            if intro.song == song_track and asset_exists(intro.intro)
        ]
        intros_for_artist = [
            intro.intro
            for intro in self.intros
            if intro.artist == artist and intro.song is None and asset_exists(intro.intro)
        ]

        if intros_for_song:
            choices = intros_for_song
        elif intros_for_artist:
            choices = intros_for_artist
        else:
            print(f"No intro found for song '{song_track}' or artist '{artist}'")
            return False

        return self.play_audio(random.choice(choices))

    def play_outro(self, song):
        artist = song.artist
        song_track = song.track

        outros_for_song = [
            outro.outro
            for outro in self.outros
            if outro.song == song_track and asset_exists(outro.outro)
        ]
        outros_for_artist = [
            outro.outro
            for outro in self.outros
            if outro.artist == artist and outro.song is None and asset_exists(outro.outro)
        ]

        if outros_for_song and outros_for_artist:
            choices = random.choice([outros_for_song, outros_for_artist])
        elif outros_for_song:
            choices = outros_for_song
        elif outros_for_artist:
            choices = outros_for_artist
        else:
            print(f"No outro found for song '{song_track}'")
            return False

        return self.play_audio(random.choice(choices))

    def get_next_song(self):
        available_songs_to_play = [
            song
            for song in self.songs
            if asset_exists(song.track) and song.track not in self.song_history
        ]

        if not available_songs_to_play:
            self.song_history = self.song_history[:1]
            available_songs_to_play = [
                song
                for song in self.songs
                if asset_exists(song.track) and song.track not in self.song_history
            ]

        if not available_songs_to_play:
            raise RuntimeError("No playable songs found in data/songs.json.")

        next_song = random.choice(available_songs_to_play)
        self.song_history.insert(0, next_song.track)
        if len(self.song_history) > 20:
            self.song_history.pop()

        return next_song


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
