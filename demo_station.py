"""Explicit synthetic demo media, generated only in a fresh temporary root."""

import json
import math
import struct
import wave
from pathlib import Path


def make_demo(root: Path, song_seconds=12.0):
    """Write a small valid catalog without reading or changing private assets."""
    (root / "data").mkdir()
    (root / "assets").mkdir()

    def tone(name, seconds, frequency):
        path = root / "assets" / f"{name}.wav"
        rate = 16000
        frames = bytearray()
        for index in range(int(rate * seconds)):
            t = index / rate
            beat = t % 0.4
            pitch = frequency * (1, 1.25, 1.5, 2)[int(t / 0.4) % 4]
            envelope = min(t / 0.02, (seconds - t) / 0.04, 1) * math.exp(-beat * 8)
            value = int(5500 * envelope * math.sin(2 * math.pi * pitch * t))
            frames.extend(struct.pack("<h", value))
        with wave.open(str(path), "wb") as output:
            output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            output.writeframes(frames)
        return str(path.relative_to(root))

    songs, intros, outros = [], [], []
    for index in range(12):
        track = tone(f"Test Signal {index + 1:02}", song_seconds, 160 + index * 25)
        songs.append({"id": index + 1, "track": track, "artist": "Synthetic demo"})
        intros.append({"artist": "Synthetic demo", "song": track,
                       "intro": tone(f"Intro {index + 1:02}", 0.7, 600)})
        outros.append({"artist": "Synthetic demo", "song": track,
                       "outro": tone(f"Outro {index + 1:02}", 0.7, 440)})
    catalogs = {
        "songs": songs, "intros": intros, "outros": outros,
        "ads": [{"ad": tone(f"Test Advertisement {i}", 2, 700 + i * 100)} for i in range(1, 4)],
        "ad_intros": [{"ad_intro": tone("Advertisement Introduction", 0.7, 1000)}],
    }
    for name, records in catalogs.items():
        (root / "data" / f"{name}.json").write_text(json.dumps(records), encoding="utf-8")
