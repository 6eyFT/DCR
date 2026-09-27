# Private shared-station prototype

Based on repository commit `92820652c58db8ba6bbb59f89b5b1925e09f5a09`.
This extends the scheduler already present on main. Catalog schema, media,
legacy players, and licensing are preserved.

## Run

Use the repository's Python 3.11 and Poetry setup. On Ubuntu 24.04:

```bash
sudo apt install liquidsoap ffmpeg
poetry install
poetry run python station_web.py --demo
```

Open `http://127.0.0.1:8080` on that machine. The explicit demo generates twelve
musical test signals, intros/outros, and three advertisement signals in a fresh
temporary directory. These are not Fallout recordings. The UI labels demo mode.
Stop with Ctrl+C; generated media is removed.

For the real station, use `poetry run python station_web.py`. A clean clone without
private media fails with the catalog loader's missing-file report. There is no
silent fallback to demo mode. An isolated checkout can read an existing library:

```bash
poetry run python station_web.py --media-root /home/six/code/projects/DCR
```

That root must contain the existing `data/` and `assets/` structure. All loading
and resolution still use `catalog_loader.py`. `--port` changes the local web port;
`--seed` makes selection reproducible. Run as your ordinary user, not root.

## Architecture decision

Python owns exactly one `StationScheduler`, `PlaybackPlanner`, and `BlockPlayer`
per station process. Both legacy entrypoints use this same executor, as does the
compatible `StreamingBlockPlayer` wrapper. There is no browser playlist or
scheduler per listener.

Liquidsoap owns decoding, cueing, resampling, stereo conversion, fallback silence,
and one 128 kb/s MP3 encoder. The live configuration and original finite-output
proof include the same event transport file. Liquidsoap 2.2.4's built-in
`output.harbor` provides the shared HTTP stream, removing the need for a separate
Icecast service for this prototype. The installed operator documentation and the
real two-listener proof validated this choice. The official
[Liquidsoap output reference](https://www.liquidsoap.info/doc-2.2.5/reference/source-output)
documents this output family. Icecast remains an option for greater listener scale
or its administration features.

The standard-library HTTP server exposes four static player files, `/api/now`,
and a fixed `/stream` proxy. No added Python packages, frontend framework,
database, public asset bucket, or catalog conversion.

## Preserved rules

| Rule | Behavior |
| --- | --- |
| Startup | First song has no intro and a duration-bounded random cue, once per station launch. |
| Music | Matching intro, song, then matching outro. Song-specific clips take precedence over artist clips. |
| Song repeats | Exclude the last ten completed songs when alternatives exist; avoid immediate repeats when possible in smaller catalogs. |
| Ads | One ad intro and one ad after each five completed songs, including the initial song. |
| Ad repeats | Shuffle bag uses every completed ad before refilling and avoids a repeat across bag boundaries when possible. |
| Failures | Intro failure permits song; failed song skips outro and does not count; outro failure preserves song completion. Failed ad intro skips its ad. |
| Joining | Connect to the same ongoing encoder without changing station state. |
| Pause | Close that listener's connection and discard its buffer. Tune In opens a new live connection. |

Policy remains in the unchanged `station_scheduler.py`. Metadata comes from
confirmed playback callbacks, not queued events. Filesystem paths are excluded.

## Private remote access

The web server, stream, and control broker bind only to `127.0.0.1`. Stream and
control connections use separate random per-run credentials between local
processes, never sent to the browser or committed. The app has no directory
listing, media-file/catalog routes, seek, skip, queue, or broadcast-control API.
Responses are not cached. Cross-site requests and unexpected Host headers fail.

On a private Linux host with your media present, run the same station command
under your user and keep it alive with your existing process manager or terminal
multiplexer. On each authorized listener machine:

```bash
ssh -N -L 127.0.0.1:8080:127.0.0.1:8080 your-user@your-private-host
```

Open `http://127.0.0.1:8080` there. SSH provides access control and transport
encryption. Do not open the station ports to the Internet. Anyone with access to
the host's loopback interface can listen; this is a single-owner prototype.

No hosted deployment was made. This workspace has no configured private host or
private media. Available Sites hosting uses Cloudflare Workers and cannot run
this persistent Python/Liquidsoap process. Publishing only the page would not
provide a working station.

## Verification

```bash
# Standard suite; TCP option supports environments without Unix sockets.
DCR_PROOF_TCP=1 poetry run python -m unittest discover -s tests

# Real audio/HTTP proofs, without private media.
DCR_PROOF_TCP=1 DCR_RUN_STATION_TESTS=1 DCR_RUN_LIQUIDSOAP_TESTS=1 \
  poetry run python -m unittest tests.test_station_live tests.test_liquidsoap_runtime

# Player logic with Node's built-in test runner; Node is development-only.
node --test tests/player.test.cjs
```

Tested with Python 3.11.16, dependencies from the unchanged Poetry lockfile, and
Liquidsoap 2.2.4. The repository's 3.11.11 pin remains unchanged. System runtime
packages were extracted into an isolated test directory because global package
installation is unavailable in this workspace.

Results:

- Existing scheduler, catalog, event, legacy entrypoint, and failure tests passed.
- Two listeners with a three-second join delay shared 40,960 exact encoded MP3
  bytes, starting at byte 52,161 in the first capture. Output decoded successfully
  and contained nonzero audio.
- Actual output continued with zero listeners, preserved intro/song/outro order,
  inserted the first ad after five songs, and accepted a later reconnect.
- Unauthenticated direct stream access returned 401. Asset/catalog/traversal
  requests returned 404; foreign Host and cross-site requests returned 403.
  Dead-source state appeared as offline and stream requests returned 503.
- Real Liquidsoap proof passed WAV/MP3 cueing, metadata, missing/corrupt media,
  failure-outcome mapping, source termination, and restart.
- Seven player logic tests passed, covering play/pause/rejoin, local volume,
  paused metadata, offline startup, autoplay denial, recovery, and tab restoration.

The browser service refused this workspace's local URL. Visual layout, actual
browser audio, and mobile behavior still require a browser check on the host.
Private-media integrity tests were skipped because media is absent. Unix-socket
compatibility was skipped because AF_UNIX is disallowed here; TCP tests passed.

## Limits

- Shared broadcast, not sample-synchronized speakers. Browser/network buffering
  adds delay; source metadata may lead the audio heard by a listener.
- The inherited one-event transport can insert brief silence between clips.
  Gapless transitions and crossfades are not claimed.
- History is in memory. Restart resets the station and its initial cue.
- A dead source or three consecutive failed blocks stops playback and reports
  offline. Restart the process to recover; automatic restart is not implemented.
- The loopback development server caps stream connections at 16. Large audiences,
  TLS termination, and public access are outside this prototype.
- Actual private-media completeness and sound quality need verification on the host.
