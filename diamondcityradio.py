import time
import random
import pygame
from load_data import load_data

class RadioApp:
    def __init__(self):
        pygame.mixer.init()

        self.songs = load_data("data/songs.json")
        self.intros = load_data("data/intros.json")
        self.outros = load_data("data/outros.json")
        self.ads = load_data("data/ads.json")
        self.ad_intros = load_data("data/ad_intros.json")

        self.ad_interval = 5  # Number of songs before an ad plays
        self.song_index = 0  # To keep track of the current song
        self.cycle_count = 0  # To count song cycles between ads
        self.loop_count = 0
        self.history = []
        self.cooldown_length = 5

    def play_audio(self, track):
        print(f"Now playing: {track}")
        try:
            pygame.mixer.music.load(track)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(1)
        except pygame.error as e:
            print(f"Could not play {track}: {e}")

    def play_ad(self):
        available_ads = [ad for ad in self.ads if ad not in self.history]
        ad_to_play = random.choice(available_ads)
        print(f"--- Playing Ad: '{ad_to_play}' ---")
        self.play_audio(ad_to_play)
        self.history.insert(0, ad_to_play)
        if len(self.history) > 10:
            self.history.pop()

    def play_ad_intro(self):
        ad_intro_to_play = random.choice(self.ad_intros)
        print(f"Now playing ad intro: '{ad_intro_to_play}'")
        self.play_audio(ad_intro_to_play)

    def play_intro(self, song):
        artist = song["artist"]
        song_track = song["track"]

        # Find intros specifically for this song and artist
        intros_for_song = [intro for intro in self.intros if intro.get('song') == song_track]
        intros_for_artist = [intro for intro in self.intros if intro['artist'] == artist and 'song' not in intro]

        # Prioritize song-specific intros, fallback to artist intros if none are found
        if intros_for_song:
            result = intros_for_song
        elif intros_for_artist:
            result = intros_for_artist
        else:
            print(f"No intro found for song '{song_track}' or artist '{artist}'")
            return

        random_intro = random.choice(result)
        self.play_audio(random_intro['intro'])

    def play_outro(self, song):
        artist = song["artist"]
        song_track = song["track"]

        # Find outros for the song and artist
        outros_for_song = [outro for outro in self.outros if outro.get('song') == song_track]
        outros_for_artist = [outro for outro in self.outros if outro.get('artist') == artist and 'song' not in outro]

        # If both song and artist outros exist, randomly choose one to play
        if outros_for_song and outros_for_artist:
            result = random.choice([outros_for_song, outros_for_artist])
        elif outros_for_song:
            result = outros_for_song
        elif outros_for_artist:
            result = outros_for_artist
        else:
            print(f"No outro found for song or artist '{song_track}'")
            return

        random_outro = random.choice(result)
        self.play_audio(random_outro['outro'])

    def get_next_song(self):
        available_songs_to_play = [song for song in self.songs if song not in self.history]
    
        # If all songs have been played, reset the history (except the most recent one)
        if len(available_songs_to_play) == 0:
            self.history.pop()  # Keep the most recent song in the history
            available_songs_to_play = self.songs  # Re-allow all songs to play again
    
        return random.choice(available_songs_to_play)

    def autoplay(self):
        print("Radio is now simulating...")

        # Pick a random song to start with and play without an intro
        first_song = random.choice(self.songs)
        print(f"Starting with a random song: {first_song['track']}")
        self.play_audio(first_song["track"])
        self.play_outro(first_song)

        # Add the first song to history and manage its size
        self.history.insert(0, first_song)
        if len(self.history) > 10:
            self.history.pop()

        next_song = self.get_next_song()
        self.song_index = self.songs.index(next_song)

        while True:
            self.cycle_count += 1

            # Check if it's time to play an ad
            if self.cycle_count >= self.ad_interval:
                self.play_ad_intro()
                self.play_ad()
                self.cycle_count = 0

                # After the ad, play the next song (with its intro if available)
                next_song = self.get_next_song()
                self.song_index = self.songs.index(next_song)

                self.play_intro(next_song)
                self.play_audio(next_song["track"])
                self.play_outro(next_song)

            else:
                current_song = self.songs[self.song_index]

                self.play_intro(current_song)
                self.play_audio(current_song["track"])
                self.play_outro(current_song)

                next_song = self.get_next_song()
                self.song_index = self.songs.index(next_song)

            self.history.insert(0, current_song)
            if len(self.history) > 10:
                self.history.pop()

            self.loop_count += 1


radio_app = RadioApp()

radio_app.autoplay()