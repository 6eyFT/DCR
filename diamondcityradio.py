import random
import time

import pygame

from load_data import asset_exists, load_data, resolve_project_path


class RadioApp:
    def __init__(self):
        pygame.mixer.init()

        self.songs = load_data("data/songs.json")
        self.intros = load_data("data/intros.json")
        self.outros = load_data("data/outros.json")
        self.ads = load_data("data/ads.json")
        self.ad_intros = load_data("data/ad_intros.json")

        self.ad_interval = 5
        self.cycle_count = 0
        self.loop_count = 0
        self.song_history = []
        self.ad_history = []

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

    def play_ad(self):
        available_ads = [
            ad["ad"] for ad in self.ads if asset_exists(ad["ad"]) and ad["ad"] not in self.ad_history
        ]
        if not available_ads:
            self.ad_history.clear()
            available_ads = [ad["ad"] for ad in self.ads if asset_exists(ad["ad"])]

        if not available_ads:
            print("No ads available to play.")
            return False

        ad_to_play = random.choice(available_ads)
        print(f"--- Playing Ad: '{ad_to_play}' ---")
        played = self.play_audio(ad_to_play)
        if played:
            self.ad_history.insert(0, ad_to_play)
            if len(self.ad_history) > 10:
                self.ad_history.pop()
        return played

    def play_ad_intro(self):
        available_ad_intros = [entry["ad_intro"] for entry in self.ad_intros if asset_exists(entry["ad_intro"])]
        if not available_ad_intros:
            print("No ad intros available to play.")
            return False

        ad_intro_to_play = random.choice(available_ad_intros)
        print(f"Now playing ad intro: '{ad_intro_to_play}'")
        return self.play_audio(ad_intro_to_play)

    def play_intro(self, song):
        artist = song["artist"]
        song_track = song["track"]

        intros_for_song = [
            intro["intro"]
            for intro in self.intros
            if intro.get("song") == song_track and asset_exists(intro["intro"])
        ]
        intros_for_artist = [
            intro["intro"]
            for intro in self.intros
            if intro["artist"] == artist and "song" not in intro and asset_exists(intro["intro"])
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
        artist = song["artist"]
        song_track = song["track"]

        outros_for_song = [
            outro["outro"]
            for outro in self.outros
            if outro.get("song") == song_track and asset_exists(outro["outro"])
        ]
        outros_for_artist = [
            outro["outro"]
            for outro in self.outros
            if outro.get("artist") == artist and "song" not in outro and asset_exists(outro["outro"])
        ]

        if outros_for_song and outros_for_artist:
            choices = random.choice([outros_for_song, outros_for_artist])
        elif outros_for_song:
            choices = outros_for_song
        elif outros_for_artist:
            choices = outros_for_artist
        else:
            print(f"No outro found for song '{song_track}' or artist '{artist}'")
            return False

        return self.play_audio(random.choice(choices))

    def get_next_song(self):
        available_songs_to_play = [
            song
            for song in self.songs
            if asset_exists(song["track"]) and song["track"] not in self.song_history
        ]

        if not available_songs_to_play:
            self.song_history = self.song_history[:1]
            available_songs_to_play = [
                song
                for song in self.songs
                if asset_exists(song["track"]) and song["track"] not in self.song_history
            ]

        if not available_songs_to_play:
            raise RuntimeError("No playable songs found in data/songs.json.")

        return random.choice(available_songs_to_play)

    def record_song(self, song):
        self.song_history.insert(0, song["track"])
        if len(self.song_history) > 10:
            self.song_history.pop()

    def autoplay(self):
        print("Radio is now simulating...")

        first_song = self.get_next_song()
        print(f"Starting with a random song: {first_song['track']}")
        self.play_audio(first_song["track"])
        self.play_outro(first_song)
        self.record_song(first_song)

        while True:
            if self.cycle_count >= self.ad_interval:
                self.play_ad_intro()
                self.play_ad()
                self.cycle_count = 0

            current_song = self.get_next_song()
            self.play_intro(current_song)
            self.play_audio(current_song["track"])
            self.play_outro(current_song)
            self.record_song(current_song)

            self.cycle_count += 1
            self.loop_count += 1


def main():
    radio_app = RadioApp()
    radio_app.autoplay()


if __name__ == "__main__":
    main()
