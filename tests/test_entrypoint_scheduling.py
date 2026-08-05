import random
import unittest
from unittest import mock

import _radio_gui
import diamondcityradio
from catalog_loader import Ad, AdIntro, Catalogs, Intro, Outro, Song
from station_scheduler import (
    AdvertisementBlock,
    AdvertisementPlaybackOutcome,
    SongBlock,
    SongPlaybackOutcome,
)


def synthetic_catalogs():
    return Catalogs(
        songs=(Song(id=1, track="song.wav", artist="Artist"),),
        intros=(),
        outros=(),
        ads=(Ad(ad="ad.wav"),),
        ad_intros=(AdIntro(ad_intro="ad-intro.wav"),),
    )


def song_block():
    song = Song(id=1, track="song.wav", artist="Artist")
    return SongBlock(
        song=song,
        intro=Intro(artist=song.artist, intro="intro.wav"),
        outro=Outro(artist=song.artist, outro="outro.wav"),
        initial=False,
    )


def advertisement_block():
    return AdvertisementBlock(
        intro=AdIntro(ad_intro="ad-intro.wav"),
        advertisement=Ad(ad="ad.wav"),
    )


def playback_adapter(app_class):
    app = app_class.__new__(app_class)
    app.scheduler = mock.Mock()
    app.play_audio = mock.Mock()
    if app_class is _radio_gui.RadioApp:
        app.update_current_track = mock.Mock()
    return app


class EntrypointSchedulerConstructionTests(unittest.TestCase):
    def test_console_constructs_shared_scheduler_with_injected_random_source(self):
        catalogs = synthetic_catalogs()
        random_source = random.Random(1)

        with (
            mock.patch.object(diamondcityradio, "initialize_audio"),
            mock.patch.object(diamondcityradio, "load_catalogs", return_value=catalogs),
            mock.patch.object(diamondcityradio, "StationScheduler") as scheduler_class,
        ):
            diamondcityradio.RadioApp(random_source=random_source)

        scheduler_class.assert_called_once_with(catalogs, random_source)

    def test_gui_constructs_shared_scheduler_with_injected_random_source(self):
        catalogs = synthetic_catalogs()
        random_source = random.Random(2)
        root = mock.Mock()
        widget = mock.Mock()

        with (
            mock.patch.object(_radio_gui, "initialize_audio"),
            mock.patch.object(_radio_gui, "load_catalogs", return_value=catalogs),
            mock.patch.object(_radio_gui, "StationScheduler") as scheduler_class,
            mock.patch.object(_radio_gui.RadioApp, "load_gif_frames", return_value=[]),
            mock.patch.object(_radio_gui.tk, "Label", return_value=widget),
            mock.patch.object(_radio_gui.tk, "Frame", return_value=widget),
            mock.patch.object(_radio_gui.ttk, "Scale", return_value=widget),
            mock.patch.object(_radio_gui.ttk, "Label", return_value=widget),
            mock.patch.object(_radio_gui.ttk, "Button", return_value=widget),
            mock.patch.object(_radio_gui.pygame.mixer.music, "set_volume"),
        ):
            _radio_gui.RadioApp(root, random_source=random_source)

        scheduler_class.assert_called_once_with(catalogs, random_source)


class EntrypointPlaybackOutcomeTests(unittest.TestCase):
    def test_both_entrypoints_continue_after_intro_failure(self):
        for app_class in (diamondcityradio.RadioApp, _radio_gui.RadioApp):
            with self.subTest(entrypoint=app_class.__module__):
                app = playback_adapter(app_class)
                block = song_block()
                app.play_audio.side_effect = [False, True, False]

                app.play_scheduled_block(block)

                self.assertEqual(
                    app.play_audio.call_args_list,
                    [
                        mock.call("intro.wav"),
                        mock.call("song.wav"),
                        mock.call("outro.wav"),
                    ],
                )
                app.scheduler.report_outcome.assert_called_once_with(
                    block,
                    SongPlaybackOutcome(
                        intro_completed=False,
                        song_completed=True,
                        outro_completed=False,
                    ),
                )

    def test_both_entrypoints_skip_outro_after_song_failure(self):
        for app_class in (diamondcityradio.RadioApp, _radio_gui.RadioApp):
            with self.subTest(entrypoint=app_class.__module__):
                app = playback_adapter(app_class)
                block = song_block()
                app.play_audio.side_effect = [True, False]

                app.play_scheduled_block(block)

                self.assertEqual(
                    app.play_audio.call_args_list,
                    [mock.call("intro.wav"), mock.call("song.wav")],
                )
                app.scheduler.report_outcome.assert_called_once_with(
                    block,
                    SongPlaybackOutcome(
                        intro_completed=True,
                        song_completed=False,
                        outro_completed=None,
                    ),
                )

    def test_both_entrypoints_skip_advertisement_after_intro_failure(self):
        for app_class in (diamondcityradio.RadioApp, _radio_gui.RadioApp):
            with self.subTest(entrypoint=app_class.__module__):
                app = playback_adapter(app_class)
                block = advertisement_block()
                app.play_audio.return_value = False

                app.play_scheduled_block(block)

                app.play_audio.assert_called_once_with("ad-intro.wav")
                app.scheduler.report_outcome.assert_called_once_with(
                    block,
                    AdvertisementPlaybackOutcome(
                        intro_completed=False,
                        advertisement_completed=None,
                    ),
                )

    def test_both_entrypoints_play_exactly_one_intro_and_advertisement(self):
        for app_class in (diamondcityradio.RadioApp, _radio_gui.RadioApp):
            with self.subTest(entrypoint=app_class.__module__):
                app = playback_adapter(app_class)
                block = advertisement_block()
                app.play_audio.return_value = True

                app.play_scheduled_block(block)

                self.assertEqual(
                    app.play_audio.call_args_list,
                    [mock.call("ad-intro.wav"), mock.call("ad.wav")],
                )
                app.scheduler.report_outcome.assert_called_once_with(
                    block,
                    AdvertisementPlaybackOutcome(
                        intro_completed=True,
                        advertisement_completed=True,
                    ),
                )

    def test_gui_radio_loop_uses_scheduler_without_a_window(self):
        app = playback_adapter(_radio_gui.RadioApp)
        block = song_block()
        app.playing = True
        app.scheduler.next_block.side_effect = [block, RuntimeError("bounded stop")]
        app.play_scheduled_block = mock.Mock()

        app.radio_loop()

        app.play_scheduled_block.assert_called_once_with(block)
        self.assertFalse(app.playing)


if __name__ == "__main__":
    unittest.main()
