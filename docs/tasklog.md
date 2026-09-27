# Tasklog

## Completed: private shared-station prototype (2026-09-26)

- Reused the existing scheduler; consolidated duplicated block execution across
  console, GUI, and streaming paths in `block_player.py`.
- Added loopback-only browser player and shared Liquidsoap HTTP output, using
  generated demo audio when explicitly requested. No catalog or media edits.
- Verified real two-listener audio equivalence, late joining, zero-listener
  progression, ad cadence, private routes, and source-loss handling.
- See [private-station.md](private-station.md) for evidence, run instructions,
  private hosting requirements, and the blocked browser/private-media checks.

This backlog is for work that should improve Diamond City Radio over time without pretending the project is already production-grade. Items here are intentionally pragmatic and scoped for a solo owner returning to an older codebase.

## Immediate / Stabilization

### Harden The Poetry-Based Runtime Setup
- Why it matters: the repo now has a Poetry baseline, but local reliability still depends on clear audio-system expectations, cross-machine verification, and avoiding environment drift.
- Rough scope: verify the `pyenv` + Poetry flow on a clean machine, document any system packages needed for `pygame` or `tkinter`, and keep the pinned Python version current without widening compatibility claims prematurely.
- Suggested acceptance criteria: a fresh machine can follow the documented setup, create `.venv/`, import the app successfully, and any remaining platform prerequisites are explicitly documented.
- Risk / priority: high priority, low risk.

### Add Startup Preflight Checks
- Why it matters: `pygame` import failures, mixer initialization issues, and missing local media currently surface as rough runtime errors.
- Rough scope: add clear startup checks for dependency availability, audio device initialization, and required catalog/media files before entering the playback loop.
- Suggested acceptance criteria: startup failures exit early with actionable error messages instead of tracebacks or partial playback state.
- Risk / priority: high priority, low to medium risk.

### Validate WSLg / Pulse Playback Quality End-To-End
- Why it matters: startup and backend selection can be stabilized in code, but audible crackle/static under WSLg still needs empirical listening checks against the real Pulse/RDP sink.
- Rough scope: verify real playback after backend and mixer tuning, compare buffer sizes if artifacts remain, and decide whether any remaining issues are environment-specific or asset/mastering-related.
- Suggested acceptance criteria: playback is subjectively clean on the target WSLg machine, or the remaining defect is narrowed to a specific unresolved cause with documented follow-up steps.
- Risk / priority: high priority, medium risk.

### Add Smoke Tests For Playback Selection Logic
- Why it matters: the console and GUI paths both contain custom playback logic, and regressions are easy to introduce without noticing.
- Rough scope: add tests around song rotation, ad rotation, intro/outro selection, and missing-asset fallback behavior using mocked mixer/audio calls.
- Suggested acceptance criteria: automated tests cover the main selection rules and fail if broken catalog assumptions or control-flow bugs are reintroduced.
- Risk / priority: high priority, medium risk.

### Improve Error Handling And User Feedback
- Why it matters: playback failures currently mostly print to stdout, which is weak for both the console and GUI entrypoints.
- Rough scope: standardize error handling paths, surface critical failures in the GUI, and avoid silent continuation when core runtime assumptions break.
- Suggested acceptance criteria: common failures have explicit messages, the GUI reflects fatal playback errors, and logs are coherent enough to debug a bad session.
- Risk / priority: high priority, medium risk.

### Add A Catalog Validation Script
- Why it matters: the project depends on manual JSON-to-asset consistency, which drifts easily as files move or clips are renamed.
- Rough scope: create a small validation command that checks asset existence, duplicate IDs, broken references, and suspicious placeholder values.
- Suggested acceptance criteria: one command reports catalog integrity problems before runtime, and new catalog edits are expected to pass it.
- Risk / priority: high priority, low risk.

## Near-Term / Quality

### Consolidate Shared Playback Logic
- Why it matters: `diamondcityradio.py` and `_radio_gui.py` duplicate core selection behavior, which invites drift and duplicate bugfixes.
- Rough scope: extract catalog loading, track selection, intro/outro selection, and history management into a shared module while keeping the current entrypoints thin.
- Suggested acceptance criteria: one shared playback core drives both entrypoints, and fixes to selection logic only need to land in one place.
- Risk / priority: medium priority, medium risk.

### Introduce Real Configuration Management
- Why it matters: settings like ad interval, asset roots, and playback behavior are hardcoded, which makes local tweaking and future distribution clumsy.
- Rough scope: define a small configuration layer for user-tunable settings, with safe defaults and explicit validation.
- Suggested acceptance criteria: core settings can be changed without editing source, invalid config is rejected clearly, and defaults preserve current behavior.
- Risk / priority: medium priority, medium risk.

### Establish Baseline Logging / Observability
- Why it matters: plain `print` statements are enough for hobby experimentation but weak for debugging repeatable playback or startup issues.
- Rough scope: replace ad hoc prints with structured logging levels and a consistent logger setup shared by both entrypoints.
- Suggested acceptance criteria: logs distinguish info/warning/error events, startup and playback failures are easy to trace, and optional file logging is supported.
- Risk / priority: medium priority, low to medium risk.

### Improve GUI UX And Session Controls
- Why it matters: the Tkinter app currently behaves like a basic prototype with minimal controls and weak feedback during failures or long playback.
- Rough scope: add stop/pause behavior, disable duplicate start actions, improve current-track state, and tighten thread-safe UI updates.
- Suggested acceptance criteria: the GUI can start and stop reliably, shows useful playback state, and avoids obvious race-condition or repeat-click issues.
- Risk / priority: medium priority, medium risk.

### Expand Documentation
- Why it matters: the project historically relied on memory and local context, which makes returning to it expensive.
- Rough scope: add a user-facing README, explain the media catalog format, and document any assumptions around asset sourcing and licensing.
- Suggested acceptance criteria: a returning maintainer can understand the repo, the runtime model, and the media-data conventions without reading every source file.
- Risk / priority: medium priority, low risk.

### Tighten Developer Workflow
- Why it matters: there is no standard workflow for validation, formatting, review, or regression checks.
- Rough scope: add a small set of default developer commands, decide on lint/type tooling, and document the expected pre-commit validation loop.
- Suggested acceptance criteria: contributors have one documented path for install, validation, and basic quality checks.
- Risk / priority: medium priority, low to medium risk.

## Longer-Term / Professionalization

### Prepare For Distribution
- Why it matters: if this is going to feel like a professional application, startup should not depend on a manually managed source checkout and local media layout.
- Rough scope: choose a packaging/distribution strategy such as `pyinstaller`, an installable package, or a platform-specific app bundle.
- Suggested acceptance criteria: a target user can install or launch the application through a documented, repeatable release artifact.
- Risk / priority: lower priority, high effort.

### Rework Audio Session Architecture
- Why it matters: blocking playback loops are simple but limit responsiveness, future controls, and recoverability from runtime errors.
- Rough scope: move toward a queued or event-driven playback controller with clearer state transitions and interruption handling.
- Suggested acceptance criteria: playback control is explicit, pause/stop/skip are technically supportable, and the GUI no longer depends on long-running blocking audio calls.
- Risk / priority: lower priority, high risk.

### Add Release-Quality Test Coverage
- Why it matters: moving toward professional quality will require confidence beyond smoke tests and manual runs.
- Rough scope: grow coverage across catalog validation, playback state transitions, GUI-safe integration seams, and packaging smoke tests.
- Suggested acceptance criteria: the project has a repeatable test suite that covers the core runtime model and catches the main regression classes before release.
- Risk / priority: lower priority, medium to high effort.

### Improve Performance And Asset Handling
- Why it matters: larger asset libraries, slower disks, or packaged builds may expose latency and memory issues that are currently hidden by the tiny codebase.
- Rough scope: measure startup/playback latency, consider lightweight metadata caching, and avoid loading or decoding more media than needed.
- Suggested acceptance criteria: startup and track transitions remain responsive with a larger media library, and bottlenecks are understood rather than guessed.
- Risk / priority: lower priority, medium risk.

### Formalize Maintenance And Release Process
- Why it matters: a professional-feeling project needs predictable release notes, versioning, and a maintenance loop, not just ad hoc local edits.
- Rough scope: add versioning, release notes, backup/asset handling expectations, and a lightweight maintenance checklist for future passes.
- Suggested acceptance criteria: releases are named, tracked, and repeatable, with a clear process for validating and shipping changes.
- Risk / priority: lower priority, medium effort.
