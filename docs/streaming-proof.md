# Phase 4A Streaming Proof

This proof selects **Liquidsoap 2.2.4 or a patch-compatible 2.2.x release** as
the streaming source layer. It is development evidence, not a production
service definition.

## Decision

The retained boundary is:

```text
StationScheduler -> PlaybackPlanner -> StreamingBlockPlayer
                                      -> LiquidsoapStreamingAdapter
                                      <-> streaming_bridge.py
                                      <-> Liquidsoap request.dynamic
                                      -> fallback silence -> MP3 output
                                      -> future Icecast mount
```

Python continues to select blocks, create `PlaybackEvent` metadata, and map
terminal event results to scheduler outcomes. Liquidsoap is responsible for
request decoding, `liq_cue_in`, format conversion, resampling, continuous
fallback audio, encoding, and a future Icecast source connection. The
Liquidsoap configuration has no song, intro/outro, advertisement, history, or
cadence logic.

A direct Python/FFmpeg source would avoid Liquidsoap itself, but Python would
then need to supervise per-file decoding, pipe gapless PCM into a durable
encoder, keep silence flowing, update Icecast metadata separately, detect
partial writes, restart subprocesses, and reconnect publication. That is more
custom lifecycle code than this MVP needs. Liquidsoap adds one system service
dependency but removes those responsibilities from application Python and is
the smaller reliable production direction, subject to the runtime checks still
listed below.

## Control and data flow

`LiquidsoapStreamingAdapter.play(event)` permits one in-flight event and blocks
until it receives an immutable `StreamingResult`. Liquidsoap polls the adapter
through short-lived Unix-socket bridge connections. Each event is serialized as
versioned JSON containing its path, type, display title, station name, artist,
associated song, and cue offset. `streaming_bridge.py` converts it to one
Liquidsoap `annotate:` request URI. Spaces, quotes, Unicode, and URI-special path
characters are escaped before they reach Liquidsoap.

Liquidsoap reports an event start from `on_track` and completion from
`source.on_end(delay=0.)`. A delivered request that never produces `on_track`
becomes `start_failed` after the adapter's configured start timeout. Explicit
terminal statuses are `completed`, `start_failed`, `interrupted`, and
`connection_lost`. A separate bounded result timeout prevents an abruptly lost
source from blocking station Python forever. Every bridge operation opens a
fresh socket, so a dropped control connection does not poison later operations.
Infinite `blank()` audio keeps the output clock active when no event is ready.

## Local prerequisites

On Ubuntu 24.04, install the missing system runtimes manually:

```bash
sudo apt update
sudo apt install liquidsoap icecast2 ffmpeg
```

Then verify versions and configuration syntax:

```bash
liquidsoap --version
icecast2 -v
ffmpeg -version
ffprobe -version
liquidsoap --check liquidsoap/dcr-proof.liq
```

Do not put real Icecast credentials in this repository. The Phase 4A file uses
encoded local output and does not configure an Icecast mount.

## Run the proof

The clean-clone-safe transport proof uses generated WAV fixtures and an actual
Unix socket, but deliberately does not claim to decode them:

```bash
poetry run python streaming_proof.py
```

With Liquidsoap and FFmpeg installed, the runtime proof generates temporary WAV
fixtures, converts the normal song to MP3, sends the required seven-event
sequence, and writes a continuous 44.1 kHz stereo 128 kb/s MP3 output:

```bash
poetry run python streaming_proof.py --liquidsoap \
  --output /tmp/dcr-streaming-proof.mp3
ffprobe -v error -show_streams -show_format /tmp/dcr-streaming-proof.mp3
```

Inspect `dcr_event_id`, `title`, `artist`, `station_name`,
`dcr_associated_song`, `dcr_media_type`, and `liq_cue_in` in Liquidsoap's
request/metadata logs. Independently compare decoded samples around the initial
cue before calling cue accuracy exact; container-level MP3/VBR seeking may only
be approximate.

## Known limitations

- The current proof config targets Liquidsoap 2.2.4 and must pass
  `liquidsoap --check` on the deployment machine before retention.
- The Python socket protocol and outcome mapping are executable without private
  media. Decoding, cue accuracy, resampling, encoded output, and callback timing
  require the external runtime proof.
- `source.on_end(delay=0.)` is the smallest completion signal available for this
  proof. Phase 4 must verify that it represents emitted completion closely
  enough for station counting, including output interruption near track end.
- A start timeout distinguishes an unresolved/invalid delivered request from a
  source that never fetched the event. The production timeout and health model
  and the maximum event result timeout still need operational tuning.
- The fallback proves the intended continuous-source topology. Zero-listener,
  late-listener, two-listener synchronization, mount metadata, and Icecast
  reconnect behavior remain Icecast integration checks for production Phase 4.
- Raspberry Pi suitability is an architecture assessment until the exact Pi
  model/OS is known and mixed-format decode plus MP3 encode CPU use is measured.
