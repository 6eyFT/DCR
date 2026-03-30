import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pygame

DUMMY_AUDIO_FLAG = "--dummy-audio"
DUMMY_AUDIO_ENV_VAR = "DCR_DUMMY_AUDIO"
AUDIO_BACKEND_ENV_VAR = "DCR_AUDIO_BACKEND"
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
WSLG_PULSE_SOCKET = Path("/mnt/wslg/PulseServer")
WSLG_PULSE_SERVER = f"unix:{WSLG_PULSE_SOCKET}"
WSLG_PULSE_MIXER_KWARGS = {
    "frequency": 48000,
    "size": -16,
    "channels": 2,
    "buffer": 2048,
}


@dataclass
class AudioConfiguration:
    backend: str | None = None
    backend_source: str | None = None
    using_dummy_audio: bool = False
    wslg_detected: bool = False
    pulse_server: str | None = None
    mixer_kwargs: dict[str, int] = field(default_factory=dict)


class AudioInitializationError(RuntimeError):
    pass


def _env_truthy(value):
    return str(value).strip().lower() in TRUTHY_ENV_VALUES


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _wsl_kernel_hint_text():
    return f"{_read_text('/proc/sys/kernel/osrelease')}\n{_read_text('/proc/version')}".lower()


def _wslg_pulse_socket_exists():
    return WSLG_PULSE_SOCKET.exists()


def is_wslg_environment(environ=None):
    env = os.environ if environ is None else environ
    kernel_hints = _wsl_kernel_hint_text()
    running_in_wsl = any(
        [
            env.get("WSL_DISTRO_NAME"),
            env.get("WSL_INTEROP"),
            "microsoft" in kernel_hints,
            "wsl2" in kernel_hints,
        ]
    )
    return running_in_wsl and _wslg_pulse_socket_exists()


def consume_dummy_audio_request(argv=None, environ=None):
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ

    cleaned_args = []
    dummy_audio_requested = False
    for arg in args:
        if arg == DUMMY_AUDIO_FLAG:
            dummy_audio_requested = True
            continue
        cleaned_args.append(arg)

    if _env_truthy(env.get(DUMMY_AUDIO_ENV_VAR, "")):
        dummy_audio_requested = True

    return dummy_audio_requested, cleaned_args


def build_audio_configuration(dummy_audio_requested=False, environ=None):
    env = os.environ if environ is None else environ
    wslg_detected = is_wslg_environment(env)

    if dummy_audio_requested:
        return AudioConfiguration(
            backend="dummy",
            backend_source="dummy",
            using_dummy_audio=True,
            wslg_detected=wslg_detected,
        )

    explicit_sdl_backend = str(env.get("SDL_AUDIODRIVER", "")).strip()
    if explicit_sdl_backend:
        return AudioConfiguration(
            backend=explicit_sdl_backend,
            backend_source="sdl_env",
            wslg_detected=wslg_detected,
            pulse_server=_select_pulse_server(explicit_sdl_backend, env),
            mixer_kwargs=_select_mixer_kwargs(explicit_sdl_backend, wslg_detected),
        )

    explicit_backend = str(env.get(AUDIO_BACKEND_ENV_VAR, "")).strip()
    if explicit_backend:
        return AudioConfiguration(
            backend=explicit_backend,
            backend_source="dcr_env",
            wslg_detected=wslg_detected,
            pulse_server=_select_pulse_server(explicit_backend, env),
            mixer_kwargs=_select_mixer_kwargs(explicit_backend, wslg_detected),
        )

    if wslg_detected:
        return AudioConfiguration(
            backend="pulse",
            backend_source="wslg_auto",
            wslg_detected=True,
            pulse_server=_select_pulse_server("pulse", env),
            mixer_kwargs=dict(WSLG_PULSE_MIXER_KWARGS),
        )

    return AudioConfiguration(wslg_detected=wslg_detected)


def _select_pulse_server(backend, environ):
    if backend != "pulse":
        return None
    if environ.get("PULSE_SERVER"):
        return None
    if _wslg_pulse_socket_exists():
        return WSLG_PULSE_SERVER
    return None


def _select_mixer_kwargs(backend, wslg_detected):
    if backend == "pulse" and wslg_detected:
        return dict(WSLG_PULSE_MIXER_KWARGS)
    return {}


def _announce_audio_configuration(app_name, config):
    if config.using_dummy_audio:
        print(f"{app_name}: dummy audio mode enabled. No real sound will play.")
    elif config.backend_source == "wslg_auto":
        print(f"{app_name}: using Pulse audio backend for WSLg with a 48 kHz stereo mixer.")
    elif config.backend_source == "dcr_env":
        print(f"{app_name}: using requested audio backend '{config.backend}'.")


def initialize_audio(app_name, dummy_audio_requested=False, environ=None):
    env = os.environ if environ is None else environ
    config = build_audio_configuration(
        dummy_audio_requested=dummy_audio_requested,
        environ=env,
    )

    if pygame.mixer.get_init():
        return config

    if config.backend:
        env["SDL_AUDIODRIVER"] = config.backend
    if config.pulse_server:
        env["PULSE_SERVER"] = config.pulse_server

    _announce_audio_configuration(app_name, config)

    try:
        pygame.mixer.init(**config.mixer_kwargs)
    except pygame.error as error:
        backend_note = f"\nTried SDL audio backend: {config.backend}" if config.backend else ""
        if config.using_dummy_audio:
            raise AudioInitializationError(
                f"{app_name}: audio startup failed even with dummy audio enabled."
                f"{backend_note}\nOriginal pygame error: {error}"
            ) from error

        raise AudioInitializationError(
            f"{app_name}: no usable audio device was found."
            f"{backend_note}\nConnect or configure local audio, or rerun with {DUMMY_AUDIO_FLAG} "
            f"or {DUMMY_AUDIO_ENV_VAR}=1 for headless testing.\n"
            f"Original pygame error: {error}"
        ) from error

    return config
