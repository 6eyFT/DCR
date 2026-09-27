# Private live prototype. No playlist, shuffle, ad cadence, or history here.
settings.harbor.bind_addrs := ["127.0.0.1"]
settings.server.telnet := false
settings.server.socket := false
%include "dcr-events.liq"

output.harbor(
  %mp3(bitrate=128, samplerate=44100, stereo=true),
  port=int_of_string(environment.get("DCR_STREAM_PORT")),
  mount="/radio.mp3",
  user="listener",
  password=environment.get("DCR_STREAM_PASSWORD"),
  burst=2048,
  chunk=1024,
  buffer=65536,
  register_telnet=false,
  headers=[("Cache-Control", "no-store")],
  radio
)
