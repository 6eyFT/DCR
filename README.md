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

## Validation

Tests:

```bash
poetry run python -m unittest discover -s tests
```

Compile/syntax checks:

```bash
poetry run python -m py_compile diamondcityradio.py _radio_gui.py load_data.py tests/test_data_integrity.py
```

Import smoke check:

```bash
poetry run python -c "import diamondcityradio, _radio_gui"
```

## Notes

- Use Poetry as the only maintained dependency workflow for this repo. There is no hand-maintained `requirements.txt`.
- Do not commit local virtualenv directories. `.venv/` is the expected local Poetry environment and is ignored by git.
- Both entrypoints expect the local `assets/` tree and `data/*.json` catalogs to stay in sync.
- If mixer initialization fails during real playback, that is usually an audio-device or SDL environment issue rather than a packaging issue.
