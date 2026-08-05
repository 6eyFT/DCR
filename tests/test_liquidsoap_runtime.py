import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from streaming_proof import run_liquidsoap_proof


RUNTIME_ENABLED = os.environ.get("DCR_RUN_LIQUIDSOAP_TESTS") == "1"
RUNTIME_AVAILABLE = all(
    shutil.which(command) is not None
    for command in ("liquidsoap", "ffmpeg", "ffprobe")
)


@unittest.skipUnless(
    RUNTIME_ENABLED and RUNTIME_AVAILABLE,
    "set DCR_RUN_LIQUIDSOAP_TESTS=1 with Liquidsoap and FFmpeg installed",
)
class LiquidsoapRuntimeTests(unittest.TestCase):
    def test_generated_wav_mp3_failure_and_restart_suite(self):
        with TemporaryDirectory(prefix="dcr-runtime-test-") as temp:
            output = Path(temp) / "proof.mp3"

            self.assertEqual(run_liquidsoap_proof(output), 0)
            self.assertTrue(output.is_file())
            self.assertTrue(output.with_name("proof-mp3-cue.mp3").is_file())


if __name__ == "__main__":
    unittest.main()
