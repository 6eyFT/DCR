"""Audio-backend-independent playback events and block planning."""

import math
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from pathlib import PurePath
from random import Random
from typing import Protocol

from station_scheduler import AdvertisementBlock, ScheduledBlock, SongBlock


STATION_NAME = "Diamond City Radio"


class MediaType(str, Enum):
    INTRO = "Intro"
    SONG = "Song"
    OUTRO = "Outro"
    ADVERTISEMENT_INTRO = "Advertisement intro"
    ADVERTISEMENT = "Advertisement"


@dataclass(frozen=True)
class PlaybackEvent:
    media_path: str
    media_type: MediaType
    display_title: str
    station_name: str = STATION_NAME
    artist: str | None = None
    associated_song_title: str | None = None
    start_offset: float = 0.0


class DurationProvider(Protocol):
    def __call__(self, media_path: str) -> float:
        """Return the media duration in seconds."""


class InvalidMediaDurationError(ValueError):
    """Raised when an initial-song duration cannot produce a valid offset."""


def filename_title(media_path: str) -> str:
    """Return the final path component without its last extension."""

    return PurePath(media_path).stem


class PlaybackPlanner:
    """Convert selected scheduler blocks into ordered playback events."""

    def __init__(self, duration_provider: DurationProvider, random_source: Random):
        self._duration_provider = duration_provider
        self._random = random_source

    def plan(self, block: ScheduledBlock) -> tuple[PlaybackEvent, ...]:
        if isinstance(block, SongBlock):
            return self._plan_song_block(block)
        if isinstance(block, AdvertisementBlock):
            return self._plan_advertisement_block(block)
        raise TypeError(f"unsupported scheduled block: {type(block).__name__}")

    def _plan_song_block(self, block):
        song_title = filename_title(block.song.track)
        events = []

        if not block.initial and block.intro is not None:
            events.append(
                self._event(
                    block.intro.intro,
                    MediaType.INTRO,
                    artist=block.song.artist,
                    associated_song_title=song_title,
                )
            )

        offset = self._initial_offset(block.song.track) if block.initial else 0.0
        events.append(
            self._event(
                block.song.track,
                MediaType.SONG,
                artist=block.song.artist,
                associated_song_title=song_title,
                start_offset=offset,
            )
        )

        if block.outro is not None:
            events.append(
                self._event(
                    block.outro.outro,
                    MediaType.OUTRO,
                    artist=block.song.artist,
                    associated_song_title=song_title,
                )
            )

        return tuple(events)

    def _plan_advertisement_block(self, block):
        return (
            self._event(
                block.intro.ad_intro,
                MediaType.ADVERTISEMENT_INTRO,
            ),
            self._event(
                block.advertisement.ad,
                MediaType.ADVERTISEMENT,
            ),
        )

    def _initial_offset(self, media_path):
        duration = self._duration_provider(media_path)
        if (
            not isinstance(duration, Real)
            or isinstance(duration, bool)
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise InvalidMediaDurationError(
                f"invalid duration for initial song '{media_path}': {duration!r}; "
                "expected a finite positive number of seconds"
            )
        return self._random.random() * float(duration)

    @staticmethod
    def _event(
        media_path,
        media_type,
        *,
        artist=None,
        associated_song_title=None,
        start_offset=0.0,
    ):
        return PlaybackEvent(
            media_path=media_path,
            media_type=media_type,
            display_title=filename_title(media_path),
            artist=artist,
            associated_song_title=associated_song_title,
            start_offset=start_offset,
        )
