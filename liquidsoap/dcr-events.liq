# Shared event transport for Liquidsoap 2.2.4. Python owns all station policy.

socket_path = environment.get(default="/tmp/dcr-streaming.sock", "DCR_STREAM_SOCKET")
bridge = environment.get(
  default="poetry run python streaming_bridge.py",
  "DCR_STREAM_BRIDGE"
)
active_request = ref(request.create("dcr:active-inactive"))
active_event_id = ref("")
active_started = ref(false)
start_reported = ref(false)

def bridge_command(arguments) =
  "#{bridge} --socket #{process.quote(socket_path)} #{arguments}"
end

events = request.queue(
  id="dcr_events",
  interactive=false,
  prefetch=0,
  timeout=20.
)

def report_in_background(arguments) =
  thread.run(
    fast=false,
    fun () -> process.run(timeout=5., bridge_command(arguments))
  )
end

def fetch_next_event() =
  lines = process.read.lines(
    timeout=10.,
    log_errors=false,
    bridge_command("next")
  )
  id = list.nth(default="", lines, 0)
  uri = list.nth(default="", lines, 1)
  if id != "" and id != "DCR_NO_EVENT" and uri != "" then
    new_request = request.create(uri)
    active_request.set(new_request)
    active_event_id.set(id)
    active_started.set(false)
    start_reported.set(false)
    events.push(new_request)
  end
end

def metadata_value(key, metadata) =
  list.assoc(default="", key, metadata)
end

def report_started(metadata) =
  id = metadata_value("dcr_event_id", metadata)
  if id != "" then
    active_started.set(true)
    media_type = metadata_value("dcr_media_type", metadata)
    media_path = metadata_value("dcr_media_path", metadata)
    title = metadata_value("title", metadata)
    station = metadata_value("station_name", metadata)
    artist = metadata_value("artist", metadata)
    associated_song = metadata_value("dcr_associated_song", metadata)
    requested_offset_text = metadata_value("dcr_start_offset", metadata)
    requested_offset = float_of_string(requested_offset_text, default=0.)
    applied_offset = source.seek(events, requested_offset)
    log.important(
      label="dcr_event",
      "START event_id=#{id} media_type=#{media_type} path=#{media_path} title=#{title} station=#{station} artist=#{artist} associated_song=#{associated_song} requested_offset=#{requested_offset} applied_offset=#{applied_offset}"
    )
    process.run(timeout=5., bridge_command("started #{process.quote(id)}"))
    start_reported.set(true)
  end
end

def monitor_completion() =
  id = active_event_id()
  if id != "" then
    if request.status(active_request()) == "destroyed" then
      if active_started() and start_reported() then
        active_event_id.set("")
        log.important(label="dcr_event", "END event_id=#{id}")
        report_in_background("result #{process.quote(id)} completed")
      elsif not active_started() then
        active_event_id.set("")
        log.important(label="dcr_event", "START_FAILED event_id=#{id}")
        report_in_background(
          "result #{process.quote(id)} start_failed --detail #{process.quote('Liquidsoap could not resolve or decode the media request')}"
        )
      end
    end
  end
end

events.on_track(report_started)
thread.run(delay=0.1, fast=false, every=0.1, fetch_next_event)
thread.run(every=0.02, monitor_completion)

# Immediate fallback switching keeps the output clock running in silence while
# Python has no event ready or the request source is temporarily unavailable.
radio = fallback(track_sensitive=false, [events, blank()])
