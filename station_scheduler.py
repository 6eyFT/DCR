"""Deterministic, audio-independent station scheduling policy."""

from collections import deque
from dataclasses import dataclass
from random import Random
from typing import TypeAlias

from catalog_loader import Ad, AdIntro, Catalogs, Intro, Outro, Song


ADVERTISEMENT_INTERVAL = 5
SONG_HISTORY_LIMIT = 10


@dataclass(frozen=True)
class SongBlock:
    song: Song
    intro: Intro | None
    outro: Outro | None
    initial: bool


@dataclass(frozen=True)
class AdvertisementBlock:
    intro: AdIntro
    advertisement: Ad


ScheduledBlock: TypeAlias = SongBlock | AdvertisementBlock


@dataclass(frozen=True)
class SongPlaybackOutcome:
    intro_completed: bool | None
    song_completed: bool
    outro_completed: bool | None


@dataclass(frozen=True)
class AdvertisementPlaybackOutcome:
    intro_completed: bool
    advertisement_completed: bool | None


PlaybackOutcome: TypeAlias = SongPlaybackOutcome | AdvertisementPlaybackOutcome


class SchedulerStateError(RuntimeError):
    """Raised when selection and outcome reporting are used out of order."""


class ScheduleUnavailableError(RuntimeError):
    """Raised when a required block cannot be built from the catalogs."""


class StationScheduler:
    """Select station blocks and update policy state from playback outcomes."""

    def __init__(self, catalogs: Catalogs, random_source: Random):
        self._songs = catalogs.songs
        self._intros = catalogs.intros
        self._outros = catalogs.outros
        self._advertisements = catalogs.ads
        self._advertisement_intros = catalogs.ad_intros
        self._random = random_source

        self._completed_songs = deque(maxlen=SONG_HISTORY_LIMIT)
        self._completed_song_count = 0
        self._next_advertisement_at = ADVERTISEMENT_INTERVAL
        self._advertisement_bag = []
        self._last_completed_advertisement = None
        self._last_selected_song = None
        self._initial_block_scheduled = False
        self._pending_block = None

    def next_block(self) -> ScheduledBlock:
        """Select the next block without treating it as completed."""

        if self._pending_block is not None:
            raise SchedulerStateError(
                "the previous scheduled block needs a playback outcome"
            )

        if not self._initial_block_scheduled:
            block = self._build_song_block(initial=True)
            self._initial_block_scheduled = True
        elif self._completed_song_count >= self._next_advertisement_at:
            block = self._build_advertisement_block()
        else:
            block = self._build_song_block(initial=False)

        self._pending_block = block
        return block

    def report_outcome(
        self,
        block: ScheduledBlock,
        outcome: PlaybackOutcome,
    ) -> None:
        """Apply one playback outcome to the pending scheduled block."""

        if block is not self._pending_block:
            raise SchedulerStateError("outcome does not match the pending block")

        if isinstance(block, SongBlock):
            if not isinstance(outcome, SongPlaybackOutcome):
                raise SchedulerStateError("song block requires a song playback outcome")
            self._validate_song_outcome(block, outcome)
            self._apply_song_outcome(block, outcome)
        else:
            if not isinstance(outcome, AdvertisementPlaybackOutcome):
                raise SchedulerStateError(
                    "advertisement block requires an advertisement playback outcome"
                )
            self._validate_advertisement_outcome(outcome)
            self._apply_advertisement_outcome(block, outcome)

        self._pending_block = None

    def _build_song_block(self, initial):
        song = self._select_song()
        intro = None if initial else self._select_intro(song)
        outro = self._select_outro(song)
        return SongBlock(song=song, intro=intro, outro=outro, initial=initial)

    def _select_song(self):
        if not self._songs:
            raise ScheduleUnavailableError("no songs are available to schedule")

        completed_tracks = {song.track for song in self._completed_songs}
        candidates = [
            song for song in self._songs if song.track not in completed_tracks
        ]
        if not candidates:
            candidates = list(self._songs)

        if self._last_selected_song is not None and len(candidates) > 1:
            alternatives = [
                song
                for song in candidates
                if song.track != self._last_selected_song.track
            ]
            if alternatives:
                candidates = alternatives

        selected = self._random.choice(candidates)
        self._last_selected_song = selected
        return selected

    def _select_intro(self, song):
        song_specific = [
            intro for intro in self._intros if intro.song == song.track
        ]
        artist_specific = [
            intro
            for intro in self._intros
            if intro.song is None and intro.artist == song.artist
        ]
        candidates = song_specific or artist_specific
        if not candidates:
            return None
        return self._random.choice(candidates)

    def _select_outro(self, song):
        song_specific = [
            outro for outro in self._outros if outro.song == song.track
        ]
        artist_specific = [
            outro
            for outro in self._outros
            if outro.song is None and outro.artist == song.artist
        ]
        candidates = song_specific or artist_specific
        if not candidates:
            return None
        return self._random.choice(candidates)

    def _build_advertisement_block(self):
        if not self._advertisement_intros:
            raise ScheduleUnavailableError(
                "no advertisement intros are available to schedule"
            )
        advertisement = self._select_advertisement()
        return AdvertisementBlock(
            intro=self._random.choice(self._advertisement_intros),
            advertisement=advertisement,
        )

    def _select_advertisement(self):
        if not self._advertisements:
            raise ScheduleUnavailableError("no advertisements are available to schedule")
        if not self._advertisement_bag:
            self._refill_advertisement_bag()
        return self._advertisement_bag[-1]

    def _refill_advertisement_bag(self):
        self._advertisement_bag = list(self._advertisements)
        self._random.shuffle(self._advertisement_bag)

        if (
            len(self._advertisement_bag) > 1
            and self._advertisement_bag[-1]
            == self._last_completed_advertisement
        ):
            replacement_index = next(
                (
                    index
                    for index, advertisement in enumerate(self._advertisement_bag)
                    if advertisement != self._last_completed_advertisement
                ),
                None,
            )
            if replacement_index is not None:
                self._advertisement_bag[-1], self._advertisement_bag[replacement_index] = (
                    self._advertisement_bag[replacement_index],
                    self._advertisement_bag[-1],
                )

    def _validate_song_outcome(self, block, outcome):
        if (block.intro is None) != (outcome.intro_completed is None):
            raise SchedulerStateError(
                "intro outcome must be reported exactly when an intro is scheduled"
            )

        if not outcome.song_completed:
            if outcome.outro_completed is not None:
                raise SchedulerStateError(
                    "an outro outcome cannot be reported after a failed song"
                )
            return

        if (block.outro is None) != (outcome.outro_completed is None):
            raise SchedulerStateError(
                "outro outcome must be reported exactly when an outro is scheduled"
            )

    @staticmethod
    def _validate_advertisement_outcome(outcome):
        if not outcome.intro_completed and outcome.advertisement_completed is not None:
            raise SchedulerStateError(
                "an advertisement outcome cannot follow a failed advertisement intro"
            )
        if outcome.intro_completed and outcome.advertisement_completed is None:
            raise SchedulerStateError(
                "an advertisement outcome is required after a completed intro"
            )

    def _apply_song_outcome(self, block, outcome):
        if outcome.song_completed:
            self._completed_songs.append(block.song)
            self._completed_song_count += 1

    def _apply_advertisement_outcome(self, block, outcome):
        if outcome.advertisement_completed:
            if (
                not self._advertisement_bag
                or self._advertisement_bag[-1] != block.advertisement
            ):
                raise SchedulerStateError(
                    "completed advertisement does not match the current rotation"
                )
            self._advertisement_bag.pop()
            self._last_completed_advertisement = block.advertisement

        self._next_advertisement_at += ADVERTISEMENT_INTERVAL
