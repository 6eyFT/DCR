import contextlib
import io
import random
import unittest
from unittest import mock

import _radio_gui
import diamondcityradio
from catalog_loader import Ad, AdIntro, Catalogs, Intro, Outro, Song
from playback_events import MediaType, PlaybackEvent
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


def song_events():
    return (
        PlaybackEvent("intro.wav", MediaType.INTRO, "intro"),
        PlaybackEvent("song.wav", MediaType.SONG, "song"),
        PlaybackEvent("outro.wav", MediaType.OUTRO, "outro"),
    )


def advertisement_events():
    return (
        PlaybackEvent(
            "ad-intro.wav",
            MediaType.ADVERTISEMENT_INTRO,
            "ad-intro",
        ),
        PlaybackEvent("ad.wav", MediaType.ADVERTISEMENT, "ad"),
    )


def playback_adapter(app_class):
    app = app_class.__new__(app_class)
    app.scheduler = mock.Mock()
    app.playback_planner = mock.Mock()
    app.play_event = mock.Mock()
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
                events = song_events()
                app.playback_planner.plan.return_value = events
                app.play_event.side_effect = [False, True, False]

                app.play_scheduled_block(block)

                self.assertEqual(
                    app.play_event.call_args_list,
                    [
                        mock.call(events[0]),
                        mock.call(events[1]),
                        mock.call(events[2]),
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
                events = song_events()
                app.playback_planner.plan.return_value = events
                app.play_event.side_effect = [True, False]

                app.play_scheduled_block(block)

                self.assertEqual(
                    app.play_event.call_args_list,
                    [mock.call(events[0]), mock.call(events[1])],
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
                events = advertisement_events()
                app.playback_planner.plan.return_value = events
                app.play_event.return_value = False

                app.play_scheduled_block(block)

                app.play_event.assert_called_once_with(events[0])
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
                events = advertisement_events()
                app.playback_planner.plan.return_value = events
                app.play_event.return_value = True

                app.play_scheduled_block(block)

                self.assertEqual(
                    app.play_event.call_args_list,
                    [mock.call(events[0]), mock.call(events[1])],
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


class EntrypointMetadataTests(unittest.TestCase):
    def test_console_output_uses_event_type_and_extensionless_title(self):
        app = diamondcityradio.RadioApp.__new__(diamondcityradio.RadioApp)
        event = PlaybackEvent(
            "assets/songs/Example Song.wav",
            MediaType.SONG,
            "Example Song",
            start_offset=12.5,
        )
        missing_path = mock.Mock()
        missing_path.exists.return_value = False

        with (
            mock.patch.object(
                diamondcityradio,
                "resolve_project_path",
                return_value=missing_path,
            ),
            io.StringIO() as output,
            contextlib.redirect_stdout(output),
        ):
            played = app.play_event(event)
            console_output = output.getvalue()

        self.assertFalse(played)
        self.assertIn("Now attempting Song: Example Song from 12.500s", console_output)

    def test_console_passes_event_offset_to_pygame(self):
        app = diamondcityradio.RadioApp.__new__(diamondcityradio.RadioApp)
        event = PlaybackEvent(
            "assets/songs/Example Song.wav",
            MediaType.SONG,
            "Example Song",
            start_offset=12.5,
        )
        resolved_path = mock.Mock()
        resolved_path.exists.return_value = True
        resolved_path.__str__ = mock.Mock(return_value="resolved.wav")

        with (
            mock.patch.object(
                diamondcityradio,
                "resolve_project_path",
                return_value=resolved_path,
            ),
            mock.patch.object(diamondcityradio.pygame.mixer.music, "load"),
            mock.patch.object(
                diamondcityradio.pygame.mixer.music,
                "play",
            ) as play,
            mock.patch.object(
                diamondcityradio.pygame.mixer.music,
                "get_busy",
                return_value=False,
            ),
            io.StringIO() as output,
            contextlib.redirect_stdout(output),
        ):
            played = app.play_event(event)

        self.assertTrue(played)
        play.assert_called_once_with(start=12.5)

    def test_gui_title_updates_for_currently_attempted_event(self):
        app = _radio_gui.RadioApp.__new__(_radio_gui.RadioApp)
        app.root = mock.Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        app.current_track_label = mock.Mock()
        app.current_track_length = 0
        app.playing = True
        event = PlaybackEvent(
            "assets/intros/Current Intro.wav",
            MediaType.INTRO,
            "Current Intro",
            start_offset=12.5,
        )
        resolved_path = mock.Mock()
        resolved_path.exists.return_value = True
        resolved_path.__str__ = mock.Mock(return_value="resolved.wav")
        sound = mock.Mock()
        sound.get_length.return_value = 30.0

        with (
            mock.patch.object(
                _radio_gui,
                "resolve_project_path",
                return_value=resolved_path,
            ),
            mock.patch.object(_radio_gui.pygame.mixer.music, "load"),
            mock.patch.object(_radio_gui.pygame.mixer.music, "play") as play,
            mock.patch.object(
                _radio_gui.pygame.mixer.music,
                "get_busy",
                return_value=False,
            ),
            mock.patch.object(
                _radio_gui.pygame.mixer,
                "Sound",
                return_value=sound,
            ),
        ):
            played = app.play_event(event)

        self.assertTrue(played)
        app.current_track_label.config.assert_called_once_with(
            text="Current Track: Current Intro"
        )
        play.assert_called_once_with(start=12.5)


if __name__ == "__main__":
    unittest.main()
