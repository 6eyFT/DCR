# Diamond City Radio Phase 4A proof, targeted at Liquidsoap 2.2.4.
# This is a development proof, not a production service configuration.

socket_path = environment.get(default="/tmp/dcr-streaming.sock", "DCR_STREAM_SOCKET")
bridge = environment.get(
  default="poetry run python streaming_bridge.py",
  "DCR_STREAM_BRIDGE"
)
output_path = environment.get(default="/tmp/dcr-streaming-proof.mp3", "DCR_STREAM_OUTPUT")

def bridge_command(arguments) =
  "#{bridge} --socket #{process.quote(socket_path)} #{arguments}"
end

def next_request() =
  lines = process.read.lines(
    timeout=5.,
    log_errors=false,
    bridge_command("next")
  )
  uri = list.hd(default="", lines)
  if uri == "" then
    null
  else
    request.create(uri)
  end
end

def event_id(metadata) =
  list.assoc(default="", "dcr_event_id", metadata)
end

def report_started(metadata) =
  id = event_id(metadata)
  if id != "" then
    process.run(timeout=5., bridge_command("started #{process.quote(id)}"))
  end
end

def report_completed(_remaining, metadata) =
  id = event_id(metadata)
  if id != "" then
    process.run(
      timeout=5.,
      bridge_command("result #{process.quote(id)} completed")
    )
  end
end

def report_shutdown() =
  process.run(timeout=5., bridge_command("shutdown"))
end

events = request.dynamic(
  id="dcr_events",
  prefetch=0,
  retry_delay=0.25,
  timeout=20.,
  next_request
)
events.on_track(report_started)
events = source.on_end(delay=0., events, report_completed)
events.on_shutdown(report_shutdown)

# Immediate fallback switching keeps the output clock running in silence while
# Python has no event ready or the request source is temporarily unavailable.
radio = fallback(track_sensitive=false, [events, blank()])

output.file(
  %mp3(bitrate=128, samplerate=44100, stereo=true),
  output_path,
  radio
)
