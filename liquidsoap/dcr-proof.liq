# Finite-output proof uses the same event transport as the live station.
%include "dcr-events.liq"
output_path = environment.get(default="/tmp/dcr-streaming-proof.mp3", "DCR_STREAM_OUTPUT")
output.file(
  %mp3(bitrate=128, samplerate=44100, stereo=true),
  output_path,
  radio
)
