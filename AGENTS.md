# Diamond City Radio

## Project Purpose

Diamond City Radio is a small custom Python radio app inspired by Fallout's in-world station format. It plays local songs with DJ intro/outro clips and ad breaks, with both a console autoplay script and a Tkinter GUI player.

This repo is an older personal project. Treat it like a stabilization and professionalization effort, not a greenfield rewrite.

## Current Architecture

- `diamondcityradio.py`: console/autoplay entrypoint. Loads catalog JSON, uses `pygame` mixer, and loops songs, intros, outros, and ads.
- `_radio_gui.py`: Tkinter GUI entrypoint. Separate playback flow with the same catalog data and `pygame` backend.
- `load_data.py`: shared JSON/path helper. All repo-relative paths should flow through here.
- `data/*.json`: media catalog. These files are runtime-critical and tightly coupled to local asset filenames.
- `assets/`: local songs, intros, outros, ads, and GIF artwork. Much of this tree is intentionally ignored from git because of media size/licensing.

## Important Files And Directories

- [`diamondcityradio.py`](/home/six/code/projects/DCR/diamondcityradio.py)
- [`_radio_gui.py`](/home/six/code/projects/DCR/_radio_gui.py)
- [`load_data.py`](/home/six/code/projects/DCR/load_data.py)
- [`pyproject.toml`](/home/six/code/projects/DCR/pyproject.toml)
- [`poetry.toml`](/home/six/code/projects/DCR/poetry.toml)
- [`.python-version`](/home/six/code/projects/DCR/.python-version)
- [`README.md`](/home/six/code/projects/DCR/README.md)
- [`data/songs.json`](/home/six/code/projects/DCR/data/songs.json)
- [`data/intros.json`](/home/six/code/projects/DCR/data/intros.json)
- [`data/outros.json`](/home/six/code/projects/DCR/data/outros.json)
- [`data/ads.json`](/home/six/code/projects/DCR/data/ads.json)
- [`data/ad_intros.json`](/home/six/code/projects/DCR/data/ad_intros.json)
- [`docs/tasklog.md`](/home/six/code/projects/DCR/docs/tasklog.md)

## How To Run

Use `pyenv` plus Poetry. Poetry is the canonical dependency manager for this repo, and `pyenv` is the preferred local Python version manager.

The repo is pinned to Python `3.11.11` via [`.python-version`](/home/six/code/projects/DCR/.python-version). Do not use the old checked-in `venv/`; it was a stale Windows environment artifact and should not be recreated.

```bash
pyenv local 3.11.11
poetry env use "$(pyenv which python)"
poetry install
poetry run python diamondcityradio.py
```

GUI entrypoint:

```bash
poetry run python _radio_gui.py
```

Notes:

- Poetry is configured to create an in-project `.venv/`.
- If the shell's `python` does not automatically follow [`.python-version`](/home/six/code/projects/DCR/.python-version), explicitly bind Poetry with `poetry env use "$(pyenv which python)"`.
- `tkinter` is expected from the system Python installation.
- Both entrypoints assume the local media files exist under `assets/`.
- `pygame` needs a working audio device. If mixer initialization fails, treat that as an environment issue first.

## Test And Validation

Current lightweight validation commands:

```bash
poetry run python -m unittest discover -s tests
poetry run python -m py_compile diamondcityradio.py _radio_gui.py load_data.py tests/test_data_integrity.py
poetry run python -c "import diamondcityradio, _radio_gui"
```

There is no configured linter, formatter, or CI yet. If you add one, log that work in the tasklog unless the user explicitly asked for the full setup.

## Repo-Specific Guardrails

- Prefer bounded, high-signal fixes. Do not rewrite the playback architecture on a first pass.
- Keep Poetry as the only maintained dependency workflow. Do not reintroduce a hand-maintained `requirements.txt` unless there is a concrete export/use case.
- Prefer `pyenv` for selecting the local interpreter and keep [`.python-version`](/home/six/code/projects/DCR/.python-version) aligned with the Poetry Python constraint.
- Keep path handling repo-relative. Do not reintroduce cwd-dependent file loading.
- Treat `data/*.json` as production runtime data. When editing it, verify the referenced assets actually exist.
- Do not bulk rename or relocate media assets unless you also validate every affected catalog entry.
- Do not commit local virtualenvs. `.venv/` and `venv/` are local-only artifacts.
- Keep console and GUI behavior aligned when fixing shared playback/data bugs. If a change only lands in one path, document the drift explicitly.
- Do not assume the existing structure is correct just because it exists. Question placeholder data, duplicated logic, and stale setup artifacts.
- Larger ideas belong in [`docs/tasklog.md`](/home/six/code/projects/DCR/docs/tasklog.md), not as speculative in-place rewrites.
- Preserve user-facing behavior unless a change is required to fix a real bug or startup failure.

## Change Boundaries

- Fix now: broken imports, bad paths, missing guards, clearly wrong catalog entries, startup crashes, and small maintainability issues with low regression risk.
- Log for later: architectural consolidation, packaging/distribution work, deep GUI redesigns, and major playback-flow refactors.
- If a task needs design choices, cross-cutting changes, or new product direction, stop and add it to the tasklog instead of improvising.

## Validation Expectations For Future Codex Work

- Run the narrowest relevant validation after every change, preferably through `poetry run ...` instead of the host interpreter.
- For data edits, validate asset existence and song-reference consistency.
- For playback logic changes, prefer small automated tests that do not require real audio output when possible.
- If runtime validation is blocked by missing local dependencies or media, say exactly what could not be validated and why.
