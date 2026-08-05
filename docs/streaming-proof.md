# Phase 4A/4B1 Streaming Proof

This is a development proof for Liquidsoap 2.2.4, not a production service or
an Icecast configuration.

## Retained architecture

```text
StationScheduler -> PlaybackPlanner -> StreamingBlockPlayer
                                      -> LiquidsoapStreamingAdapter
                                      <-> streaming_bridge.py
                                      <-> Liquidsoap request.queue
                                      -> fallback silence -> local MP3 output
                                      -> future Icecast mount
```

Python owns selection, playback-event metadata, scheduler outcome mapping, and
supervision of the Liquidsoap process. Liquidsoap owns request resolution,
decoding, forward cueing, resampling, stereo conversion, encoding, and the
continuous fallback clock. The Liquidsoap file contains no song, advertisement,
history, or cadence policy.

A direct Python/FFmpeg source would require custom management of a persistent
PCM pipe, gapless fallback, encoder restarts, partial writes, metadata updates,
and future Icecast reconnection. The verified Liquidsoap boundary is smaller
for this MVP despite adding one system runtime.

## Installed-version design

Ubuntu's Liquidsoap 2.2.4 package advertises `request.dynamic`, but its callback
does not type-check with a returned `request?`. `request.dynamic.list` accepts
the callback but is deprecated. The proof therefore uses supported
`request.queue.push`: a bounded background poll obtains one event, constructs a
request, and pushes it onto the queue. The Python adapter allows only one
in-flight event, so this is an event transport rather than a second playlist or
scheduler.

The bridge returns an event ID and an annotated native absolute path on separate
lines. The annotation carries media type, resolved path, display title, station
name, artist, associated song, and requested start offset. Native paths are
required because this Liquidsoap package treated percent-encoded `file:` paths
as literal filenames.

`liq_cue_in` was observable as metadata but did not alter decoded WAV output in
the installed runtime. The retained configuration explicitly calls
`source.seek` from `on_track`, logs both requested and actually applied offsets,
then reports the start to Python. Completion is reported only after the exact
request reaches Liquidsoap's `destroyed` lifecycle state. A request destroyed
without `on_track` is `start_failed`.

The adapter records monotonic submission, delivery, start, and finish times in
its immutable terminal result. A concurrent socket handler prevents a waiting
`next` poll from blocking start/end callbacks. The proof's process supervisor
reports unexpected Liquidsoap exit as `connection_lost`; the same adapter can
then serve a restarted runtime.

## Prerequisites

On Ubuntu 24.04:

```bash
sudo apt update
sudo apt install -y liquidsoap ffmpeg
```

Icecast is deliberately not installed or configured by this phase.

Verify the installed tools and configuration:

```bash
liquidsoap --version
ffmpeg -version
ffprobe -version
liquidsoap --check liquidsoap/dcr-proof.liq
```

## Run the proofs

The standard clean-clone-safe transport proof uses generated WAV fixtures and
the actual Unix-socket protocol, but no external decoder:

```bash
poetry run python streaming_proof.py
```

The real runtime suite generates all media under a temporary directory. It runs
the seven-event sequence with a WAV initial cue and again with an MP3 initial
cue, verifies metadata from Liquidsoap logs, analyzes the first stable output
frequency, probes the encoded files, exercises missing and invalid media,
checks block outcome mappings, terminates Liquidsoap during a track, and starts
a replacement runtime:

```bash
poetry run python streaming_proof.py --liquidsoap \
  --output /tmp/dcr-streaming-runtime.mp3
```

It retains two finite proof outputs:

- `/tmp/dcr-streaming-runtime.mp3`
- `/tmp/dcr-streaming-runtime-mp3-cue.mp3`

The same suite is available as an opt-in integration test. It is skipped by the
standard suite so clean clones do not require system packages:

```bash
DCR_RUN_LIQUIDSOAP_TESTS=1 poetry run python -m unittest \
  tests.test_liquidsoap_runtime
```

Inspect an output independently with:

```bash
ffprobe -v error -show_streams -show_format \
  /tmp/dcr-streaming-runtime.mp3
```

## Verified behavior and limitations

- Generated mono 8 kHz PCM WAV and MP3 inputs decode and are converted to a
  44.1 kHz stereo 128 kb/s MP3 output.
- A 2.031377-second cue skips a 220 Hz opening region. The first stable encoded
  regions measured 860-880 Hz against an 880 Hz source region for both WAV and
  MP3 runs. Cueing is therefore materially verified but approximate after
  frame-based seeking, resampling, and MP3 encoding; it is not sample-exact.
- Liquidsoap logs every event ID and metadata field plus requested and applied
  offsets. Metadata embedded in a future Icecast mount is not tested here.
- Completion follows request destruction and occurred approximately 0.95-1.02
  seconds after start for the 0.969-second cued fixtures. It is not inferred
  merely from dequeue or `on_track`.
- Encoded output begins before event submission, includes deliberate fallback
  intervals, and remains active after the event sequence. The finite WAV- and
  MP3-cue outputs were about 9.6 seconds each.
- Missing and invalid media return `start_failed`. Real results preserve intro,
  song, outro, advertisement-intro, and advertisement failure semantics.
- Runtime termination returns `connection_lost`; a newly started Liquidsoap
  process can accept and complete a later event through the same adapter.
- Zero-listener behavior is represented by local file output, which advances
  without a listener. Late-listener synchronization, two-listener equivalence,
  mount metadata, publication failure, and reconnect behavior remain Icecast
  phase work.
- Raspberry Pi CPU use and package availability remain unmeasured until a
  target Pi model and OS are selected.
