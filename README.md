# Diamond City Radio

Diamond City Radio is a small custom Python radio app inspired by Fallout's in-world station format. It plays a local library of songs, DJ intros/outros, and ad breaks through either a console autoplay script or a Tkinter GUI.

## Canonical Local Workflow

This repo uses:

- `pyenv` for selecting the local Python runtime
- `poetry` for dependency management and virtualenv creation

The canonical Python version for this repo is `3.11.11`, pinned in [.python-version](/home/six/code/projects/DCR/.python-version). That version is a practical target for this older codebase and is a safer compatibility choice for `pygame` than the stale checked-in Windows `3.12` virtualenv that used to sit beside the project.

## Prerequisites

- `pyenv`
- `poetry`
- system `tkinter` support if you want to run the GUI entrypoint
- a working local audio device if you want real playback through `pygame`

## Setup

If you do not already have Python `3.11.11` installed in `pyenv`:

```bash
pyenv install 3.11.11
```

From the repo root:

```bash
pyenv local 3.11.11
poetry env use "$(pyenv which python)"
poetry install
```

This project is configured to use an in-project Poetry virtualenv at `.venv/`.

If your shell is fully initialized for `pyenv`, `python --version` should now report `3.11.11`. If it does not, keep using the explicit `poetry env use "$(pyenv which python)"` step above; it removes ambiguity and ensures Poetry binds to the `pyenv` interpreter you selected.

## Run

Console autoplay:

```bash
poetry run python diamondcityradio.py
```

Tkinter GUI:

```bash
poetry run python _radio_gui.py
```

On WSLg, the app now auto-prefers the Pulse backend when it detects `/mnt/wslg/PulseServer` on a WSL kernel, and it uses a `48 kHz / 16-bit / stereo / 2048-buffer` mixer profile to better match the local song library and reduce crackle under Pulse.

Console autoplay with dummy audio:

```bash
poetry run python diamondcityradio.py --dummy-audio
```

Console autoplay with dummy audio via environment variable:

```bash
DCR_DUMMY_AUDIO=1 poetry run python diamondcityradio.py
```

GUI with dummy audio:

```bash
poetry run python _radio_gui.py --dummy-audio
```

If you need to force the real WSLg Pulse path explicitly while debugging:

```bash
DCR_AUDIO_BACKEND=pulse poetry run python _radio_gui.py
```

If your shell/session needs the Pulse socket spelled out explicitly:

```bash
SDL_AUDIODRIVER=pulse PULSE_SERVER=unix:/mnt/wslg/PulseServer poetry run python _radio_gui.py
```

## Validation

Tests:

```bash
poetry run python -m unittest discover -s tests
```

Private-media integrity tests run when local WAV or MP3 assets are present and
are skipped in clean clones. Fixture-based tests still validate the tracked
catalogs with temporary placeholder audio.

Compile/syntax checks:

```bash
poetry run python -m py_compile diamondcityradio.py _radio_gui.py audio_runtime.py catalog_loader.py station_scheduler.py playback_events.py pygame_duration.py tests/test_catalog_loader.py tests/test_station_scheduler.py tests/test_playback_events.py tests/test_entrypoint_scheduling.py tests/test_data_integrity.py tests/test_audio_runtime.py
```

Import smoke check:

```bash
poetry run python -c "import diamondcityradio, _radio_gui"
```

## Notes

- Use Poetry as the only maintained dependency workflow for this repo. There is no hand-maintained `requirements.txt`.
- Do not commit local virtualenv directories. `.venv/` is the expected local Poetry environment and is ignored by git.
- WAV and MP3 files under `assets/` are local-only; tracked `.gitkeep` files preserve the expected media directory layout in clean clones.
- Starting either entrypoint expects the local `assets/` tree and `data/*.json` catalogs to stay in sync; importing the modules does not load catalogs or media.
- Catalogs are loaded and validated together by `catalog_loader.py` before playback starts. Validation reports actionable schema, relationship, path, and supported-format problems in one aggregated error.
- `station_scheduler.py` is the single station-policy implementation used by both entrypoints; playback outcomes determine song history and advertisement cadence.
- `playback_events.py` converts scheduled blocks into immutable, metadata-bearing events. The initial song receives a duration-bounded random cue offset from the isolated pygame duration provider.
- If mixer initialization fails during real playback, the app now exits with a friendly message that points to `--dummy-audio` and `DCR_DUMMY_AUDIO=1` for headless or server-like testing.
- If WSLg is detected, the app prefers Pulse automatically unless you already set `SDL_AUDIODRIVER`, or you explicitly override with `DCR_AUDIO_BACKEND`.
