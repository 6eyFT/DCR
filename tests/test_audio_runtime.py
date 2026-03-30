import unittest
from unittest import mock

import pygame

from audio_runtime import (
    AUDIO_BACKEND_ENV_VAR,
    AudioInitializationError,
    DUMMY_AUDIO_ENV_VAR,
    WSLG_PULSE_SERVER,
    WSLG_PULSE_MIXER_KWARGS,
    build_audio_configuration,
    consume_dummy_audio_request,
    initialize_audio,
    is_wslg_environment,
)


class DummyAudioRequestTests(unittest.TestCase):
    def test_flag_is_consumed_from_args(self):
        requested, remaining_args = consume_dummy_audio_request(["--dummy-audio", "--other"])

        self.assertTrue(requested)
        self.assertEqual(remaining_args, ["--other"])

    def test_environment_variable_enables_dummy_audio(self):
        requested, remaining_args = consume_dummy_audio_request(
            ["--other"],
            environ={DUMMY_AUDIO_ENV_VAR: "1"},
        )

        self.assertTrue(requested)
        self.assertEqual(remaining_args, ["--other"])


class BackendSelectionTests(unittest.TestCase):
    @mock.patch("audio_runtime._wslg_pulse_socket_exists", return_value=True)
    @mock.patch("audio_runtime._wsl_kernel_hint_text", return_value="microsoft wsl2")
    def test_wslg_auto_selects_pulse_backend(self, _kernel_hints, _socket_exists):
        config = build_audio_configuration(environ={})

        self.assertEqual(config.backend, "pulse")
        self.assertEqual(config.backend_source, "wslg_auto")
        self.assertEqual(config.pulse_server, WSLG_PULSE_SERVER)
        self.assertEqual(config.mixer_kwargs, WSLG_PULSE_MIXER_KWARGS)

    @mock.patch("audio_runtime._wslg_pulse_socket_exists", return_value=True)
    @mock.patch("audio_runtime._wsl_kernel_hint_text", return_value="microsoft wsl2")
    def test_explicit_sdl_backend_is_respected(self, _kernel_hints, _socket_exists):
        config = build_audio_configuration(environ={"SDL_AUDIODRIVER": "alsa"})

        self.assertEqual(config.backend, "alsa")
        self.assertEqual(config.backend_source, "sdl_env")
        self.assertEqual(config.mixer_kwargs, {})

    @mock.patch("audio_runtime._wslg_pulse_socket_exists", return_value=True)
    @mock.patch("audio_runtime._wsl_kernel_hint_text", return_value="microsoft wsl2")
    def test_app_specific_backend_override_is_supported(self, _kernel_hints, _socket_exists):
        config = build_audio_configuration(environ={AUDIO_BACKEND_ENV_VAR: "pulse"})

        self.assertEqual(config.backend, "pulse")
        self.assertEqual(config.backend_source, "dcr_env")
        self.assertEqual(config.pulse_server, WSLG_PULSE_SERVER)
        self.assertEqual(config.mixer_kwargs, WSLG_PULSE_MIXER_KWARGS)

    @mock.patch("audio_runtime._wslg_pulse_socket_exists", return_value=True)
    @mock.patch("audio_runtime._wsl_kernel_hint_text", return_value="microsoft wsl2")
    def test_wslg_detection_requires_wsl_and_socket(self, _kernel_hints, _socket_exists):
        self.assertTrue(is_wslg_environment({}))


class AudioInitializationTests(unittest.TestCase):
    @mock.patch("audio_runtime.pygame.mixer.get_init", return_value=False)
    @mock.patch("audio_runtime.pygame.mixer.init")
    @mock.patch("audio_runtime._wslg_pulse_socket_exists", return_value=True)
    @mock.patch("audio_runtime._wsl_kernel_hint_text", return_value="microsoft wsl2")
    def test_wslg_pulse_sets_backend_env_and_mixer_kwargs(
        self,
        _kernel_hints,
        _socket_exists,
        mixer_init,
        _get_init,
    ):
        env = {}

        initialize_audio("Diamond City Radio", environ=env)

        self.assertEqual(env["SDL_AUDIODRIVER"], "pulse")
        self.assertEqual(env["PULSE_SERVER"], WSLG_PULSE_SERVER)
        mixer_init.assert_called_once_with(**WSLG_PULSE_MIXER_KWARGS)

    @mock.patch("audio_runtime.pygame.mixer.get_init", return_value=False)
    @mock.patch("audio_runtime.pygame.mixer.init")
    def test_dummy_audio_sets_dummy_backend(self, mixer_init, _get_init):
        env = {}

        initialize_audio("Diamond City Radio", dummy_audio_requested=True, environ=env)

        self.assertEqual(env["SDL_AUDIODRIVER"], "dummy")
        mixer_init.assert_called_once_with()

    @mock.patch("audio_runtime.pygame.mixer.get_init", return_value=False)
    @mock.patch("audio_runtime.pygame.mixer.init", side_effect=pygame.error("dsp: No such audio device"))
    def test_friendly_error_is_raised_for_missing_audio_device(self, _mixer_init, _get_init):
        with self.assertRaises(AudioInitializationError) as context:
            initialize_audio("Diamond City Radio", dummy_audio_requested=False, environ={})

        message = str(context.exception)
        self.assertIn("no usable audio device was found", message)
        self.assertIn("--dummy-audio", message)
        self.assertIn("DCR_DUMMY_AUDIO=1", message)


if __name__ == "__main__":
    unittest.main()
