import random
import unittest
from dataclasses import FrozenInstanceError

from catalog_loader import Ad, AdIntro, Catalogs, Intro, Outro, Song
from station_scheduler import (
    AdvertisementBlock,
    AdvertisementPlaybackOutcome,
    SongBlock,
    SongPlaybackOutcome,
    SchedulerStateError,
    StationScheduler,
)


def make_catalogs(
    song_count=3,
    *,
    intros=(),
    outros=(),
    advertisement_count=3,
    advertisement_intro_count=2,
):
    return Catalogs(
        songs=tuple(
            Song(
                id=index,
                track=f"assets/songs/Song {index}.wav",
                artist=f"Artist {index}",
            )
            for index in range(1, song_count + 1)
        ),
        intros=tuple(intros),
        outros=tuple(outros),
        ads=tuple(
            Ad(id=index, ad=f"assets/ads/Ad {index}.wav")
            for index in range(1, advertisement_count + 1)
        ),
        ad_intros=tuple(
            AdIntro(id=index, ad_intro=f"assets/ad_intros/Intro {index}.wav")
            for index in range(1, advertisement_intro_count + 1)
        ),
    )


def song_outcome(block, *, song_completed=True, intro_completed=True, outro_completed=True):
    return SongPlaybackOutcome(
        intro_completed=intro_completed if block.intro is not None else None,
        song_completed=song_completed,
        outro_completed=(
            outro_completed
            if song_completed and block.outro is not None
            else None
        ),
    )


def complete_song(scheduler, block=None, **outcome_overrides):
    if block is None:
        block = scheduler.next_block()
    if not isinstance(block, SongBlock):
        raise AssertionError(f"expected a song block, got {block!r}")
    scheduler.report_outcome(block, song_outcome(block, **outcome_overrides))
    return block


def complete_advertisement(scheduler, block=None):
    if block is None:
        block = scheduler.next_block()
    if not isinstance(block, AdvertisementBlock):
        raise AssertionError(f"expected an advertisement block, got {block!r}")
    scheduler.report_outcome(
        block,
        AdvertisementPlaybackOutcome(
            intro_completed=True,
            advertisement_completed=True,
        ),
    )
    return block


def next_song_block(scheduler):
    block = scheduler.next_block()
    if isinstance(block, AdvertisementBlock):
        complete_advertisement(scheduler, block)
        block = scheduler.next_block()
    if not isinstance(block, SongBlock):
        raise AssertionError(f"expected a song block, got {block!r}")
    return block


class SongSchedulingTests(unittest.TestCase):
    def test_scheduled_blocks_are_immutable(self):
        scheduler = StationScheduler(make_catalogs(), random.Random(1))
        block = scheduler.next_block()

        with self.assertRaises(FrozenInstanceError):
            block.initial = False

    def test_next_selection_requires_pending_outcome(self):
        scheduler = StationScheduler(make_catalogs(), random.Random(1))
        scheduler.next_block()

        with self.assertRaises(SchedulerStateError):
            scheduler.next_block()

    def test_seeded_initial_song_selection(self):
        scheduler = StationScheduler(make_catalogs(song_count=5), random.Random(7))

        block = scheduler.next_block()

        self.assertEqual(block.song.track, "assets/songs/Song 3.wav")

    def test_initial_block_contains_no_intro(self):
        song = make_catalogs(song_count=1).songs[0]
        intro = Intro(
            artist=song.artist,
            song=song.track,
            intro="assets/intros/Song Intro.wav",
        )
        scheduler = StationScheduler(
            make_catalogs(song_count=1, intros=(intro,)),
            random.Random(1),
        )

        block = scheduler.next_block()

        self.assertTrue(block.initial)
        self.assertIsNone(block.intro)

    def test_initial_block_uses_song_specific_outro_precedence(self):
        song = make_catalogs(song_count=1).songs[0]
        artist_outro = Outro(
            artist=song.artist,
            outro="assets/outros/Artist Outro.wav",
        )
        song_outro = Outro(
            artist=song.artist,
            song=song.track,
            outro="assets/outros/Song Outro.wav",
        )
        scheduler = StationScheduler(
            make_catalogs(song_count=1, outros=(artist_outro, song_outro)),
            random.Random(2),
        )

        block = scheduler.next_block()

        self.assertEqual(block.outro, song_outro)

    def test_successful_initial_song_counts_toward_advertisements(self):
        scheduler = StationScheduler(make_catalogs(), random.Random(3))

        for _ in range(5):
            complete_song(scheduler)

        self.assertIsInstance(scheduler.next_block(), AdvertisementBlock)

    def test_failed_initial_song_does_not_count_toward_advertisements(self):
        scheduler = StationScheduler(make_catalogs(), random.Random(4))
        initial = scheduler.next_block()
        scheduler.report_outcome(
            initial,
            song_outcome(initial, song_completed=False),
        )

        for _ in range(4):
            complete_song(scheduler)

        fifth_success = scheduler.next_block()
        self.assertIsInstance(fifth_success, SongBlock)
        complete_song(scheduler, fifth_success)
        self.assertIsInstance(scheduler.next_block(), AdvertisementBlock)

    def test_song_specific_intro_has_priority(self):
        song = make_catalogs(song_count=1).songs[0]
        artist_intro = Intro(
            artist=song.artist,
            intro="assets/intros/Artist Intro.wav",
        )
        song_intro = Intro(
            artist=song.artist,
            song=song.track,
            intro="assets/intros/Song Intro.wav",
        )
        scheduler = StationScheduler(
            make_catalogs(song_count=1, intros=(artist_intro, song_intro)),
            random.Random(5),
        )
        complete_song(scheduler)

        block = scheduler.next_block()

        self.assertEqual(block.intro, song_intro)

    def test_artist_intro_is_used_as_fallback(self):
        song = make_catalogs(song_count=1).songs[0]
        artist_intro = Intro(
            artist=song.artist,
            intro="assets/intros/Artist Intro.wav",
        )
        scheduler = StationScheduler(
            make_catalogs(song_count=1, intros=(artist_intro,)),
            random.Random(6),
        )
        complete_song(scheduler)

        block = scheduler.next_block()

        self.assertEqual(block.intro, artist_intro)

    def test_song_specific_outro_has_priority(self):
        song = make_catalogs(song_count=1).songs[0]
        artist_outro = Outro(
            artist=song.artist,
            outro="assets/outros/Artist Outro.wav",
        )
        song_outro = Outro(
            artist=song.artist,
            song=song.track,
            outro="assets/outros/Song Outro.wav",
        )
        scheduler = StationScheduler(
            make_catalogs(song_count=1, outros=(artist_outro, song_outro)),
            random.Random(7),
        )

        self.assertEqual(scheduler.next_block().outro, song_outro)

    def test_artist_outro_is_used_as_fallback(self):
        song = make_catalogs(song_count=1).songs[0]
        artist_outro = Outro(
            artist=song.artist,
            outro="assets/outros/Artist Outro.wav",
        )
        scheduler = StationScheduler(
            make_catalogs(song_count=1, outros=(artist_outro,)),
            random.Random(8),
        )

        self.assertEqual(scheduler.next_block().outro, artist_outro)

    def test_same_priority_variants_are_selected_randomly(self):
        song = make_catalogs(song_count=1).songs[0]
        variants = (
            Intro(artist=song.artist, intro="assets/intros/One.wav"),
            Intro(artist=song.artist, intro="assets/intros/Two.wav"),
        )
        selected = set()

        for seed in range(20):
            scheduler = StationScheduler(
                make_catalogs(song_count=1, intros=variants),
                random.Random(seed),
            )
            complete_song(scheduler)
            selected.add(scheduler.next_block().intro)

        self.assertEqual(selected, set(variants))

    def test_ten_most_recently_completed_songs_are_excluded(self):
        scheduler = StationScheduler(make_catalogs(song_count=11), random.Random(9))
        completed_tracks = []

        for _ in range(10):
            block = next_song_block(scheduler)
            completed_tracks.append(block.song.track)
            complete_song(scheduler, block)

        complete_advertisement(scheduler)
        next_block = scheduler.next_block()

        self.assertNotIn(next_block.song.track, completed_tracks)

    def test_failed_song_does_not_enter_completed_history(self):
        scheduler = StationScheduler(make_catalogs(song_count=2), random.Random(10))
        failed = scheduler.next_block()
        scheduler.report_outcome(
            failed,
            song_outcome(failed, song_completed=False),
        )

        alternative = scheduler.next_block()
        self.assertNotEqual(alternative.song, failed.song)
        complete_song(scheduler, alternative)
        next_block = scheduler.next_block()
        self.assertEqual(next_block.song, failed.song)

    def test_small_catalog_does_not_deadlock(self):
        scheduler = StationScheduler(make_catalogs(song_count=1), random.Random(11))
        scheduled_songs = 0

        while scheduled_songs < 16:
            block = scheduler.next_block()
            if isinstance(block, AdvertisementBlock):
                complete_advertisement(scheduler, block)
            else:
                complete_song(scheduler, block)
                scheduled_songs += 1

        self.assertEqual(scheduled_songs, 16)


class AdvertisementSchedulingTests(unittest.TestCase):
    def test_breaks_are_due_after_completions_five_ten_and_fifteen(self):
        scheduler = StationScheduler(make_catalogs(), random.Random(12))
        completions = 0
        break_counts = []

        while len(break_counts) < 3:
            block = scheduler.next_block()
            if isinstance(block, SongBlock):
                complete_song(scheduler, block)
                completions += 1
            else:
                break_counts.append(completions)
                complete_advertisement(scheduler, block)

        self.assertEqual(break_counts, [5, 10, 15])

    def test_break_contains_exactly_one_intro_and_one_advertisement(self):
        scheduler = StationScheduler(make_catalogs(), random.Random(13))
        for _ in range(5):
            complete_song(scheduler)

        block = scheduler.next_block()

        self.assertIsInstance(block.intro, AdIntro)
        self.assertIsInstance(block.advertisement, Ad)

    def test_advertisement_intros_are_selected_independently(self):
        selected_intros = set()

        for seed in range(20):
            scheduler = StationScheduler(make_catalogs(), random.Random(seed))
            for _ in range(5):
                complete_song(scheduler)
            selected_intros.add(scheduler.next_block().intro)

        self.assertEqual(len(selected_intros), 2)

    def test_shuffle_bag_uses_every_ad_before_repeating(self):
        scheduler = StationScheduler(make_catalogs(advertisement_count=3), random.Random(14))
        selected_ads = []

        while len(selected_ads) < 4:
            block = scheduler.next_block()
            if isinstance(block, SongBlock):
                complete_song(scheduler, block)
            else:
                selected_ads.append(block.advertisement)
                complete_advertisement(scheduler, block)

        self.assertEqual(len(set(selected_ads[:3])), 3)
        self.assertIn(selected_ads[3], selected_ads[:3])

    def test_refill_avoids_immediate_repeat_when_alternatives_exist(self):
        scheduler = StationScheduler(make_catalogs(advertisement_count=3), random.Random(15))
        selected_ads = []

        while len(selected_ads) < 4:
            block = scheduler.next_block()
            if isinstance(block, SongBlock):
                complete_song(scheduler, block)
            else:
                selected_ads.append(block.advertisement)
                complete_advertisement(scheduler, block)

        self.assertNotEqual(selected_ads[2], selected_ads[3])

    def test_advertisement_intro_failure_ends_break_attempt(self):
        scheduler = StationScheduler(make_catalogs(), random.Random(16))
        for _ in range(5):
            complete_song(scheduler)
        block = scheduler.next_block()

        scheduler.report_outcome(
            block,
            AdvertisementPlaybackOutcome(
                intro_completed=False,
                advertisement_completed=None,
            ),
        )

        self.assertIsInstance(scheduler.next_block(), SongBlock)

    def test_advertisement_failure_ends_break_without_completing_rotation(self):
        scheduler = StationScheduler(make_catalogs(), random.Random(17))
        for _ in range(5):
            complete_song(scheduler)
        failed_block = scheduler.next_block()
        scheduler.report_outcome(
            failed_block,
            AdvertisementPlaybackOutcome(
                intro_completed=True,
                advertisement_completed=False,
            ),
        )
        for _ in range(5):
            complete_song(scheduler)
        retry_block = scheduler.next_block()

        self.assertEqual(retry_block.advertisement, failed_block.advertisement)


class PlaybackOutcomeTests(unittest.TestCase):
    def test_intro_failure_does_not_prevent_song_completion(self):
        song = make_catalogs(song_count=1).songs[0]
        intro = Intro(artist=song.artist, intro="assets/intros/Artist.wav")
        scheduler = StationScheduler(
            make_catalogs(song_count=1, intros=(intro,)),
            random.Random(18),
        )
        complete_song(scheduler)
        for index in range(4):
            block = scheduler.next_block()
            complete_song(
                scheduler,
                block,
                intro_completed=index != 0,
            )

        self.assertIsInstance(scheduler.next_block(), AdvertisementBlock)

    def test_song_failure_does_not_increment_cadence(self):
        scheduler = StationScheduler(make_catalogs(), random.Random(19))
        failed = scheduler.next_block()
        scheduler.report_outcome(
            failed,
            song_outcome(failed, song_completed=False),
        )
        for _ in range(4):
            complete_song(scheduler)

        fifth_success = scheduler.next_block()
        self.assertIsInstance(fifth_success, SongBlock)

    def test_outro_failure_does_not_reverse_song_completion(self):
        song = make_catalogs(song_count=1).songs[0]
        outro = Outro(artist=song.artist, outro="assets/outros/Artist.wav")
        scheduler = StationScheduler(
            make_catalogs(song_count=1, outros=(outro,)),
            random.Random(20),
        )
        first = scheduler.next_block()
        complete_song(scheduler, first, outro_completed=False)
        for _ in range(4):
            complete_song(scheduler)

        self.assertIsInstance(scheduler.next_block(), AdvertisementBlock)


class DeterminismTests(unittest.TestCase):
    @staticmethod
    def scheduled_signature(seed):
        scheduler = StationScheduler(make_catalogs(song_count=12), random.Random(seed))
        signature = []

        while len(signature) < 16:
            block = scheduler.next_block()
            if isinstance(block, SongBlock):
                signature.append(("song", block.song.track))
                complete_song(scheduler, block)
            else:
                signature.append(("ad", block.advertisement.ad))
                complete_advertisement(scheduler, block)

        return signature

    def test_seeded_schedulers_are_repeatable(self):
        self.assertEqual(self.scheduled_signature(21), self.scheduled_signature(21))

    def test_different_seeds_can_produce_different_valid_results(self):
        first = self.scheduled_signature(22)
        second = self.scheduled_signature(23)

        self.assertNotEqual(first, second)
        self.assertTrue(all(kind in {"song", "ad"} for kind, _ in first + second))


if __name__ == "__main__":
    unittest.main()
