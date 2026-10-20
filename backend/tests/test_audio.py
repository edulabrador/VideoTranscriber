from pathlib import Path
from unittest.mock import patch
import unittest
import tempfile
import subprocess

from backend.core.audio import normalize_to_wav16k_mono


class AudioNormalizationTests(unittest.TestCase):
    def test_uploaded_file_is_normalized_to_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "upload.mp4"
            source.touch()
            output = Path(temp_dir) / "audio.wav"

            def create_output(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
                output.touch()
                return subprocess.CompletedProcess([], 0, "", "")

            with patch("backend.core.audio.find_ffmpeg", return_value="ffmpeg.exe"), patch(
                "backend.core.audio.subprocess.run", side_effect=create_output
            ) as run:
                self.assertEqual(normalize_to_wav16k_mono(source, output), output)

            self.assertEqual(
                run.call_args.args[0][:7],
                ["ffmpeg.exe", "-y", "-i", str(source), "-ac", "1", "-ar"],
            )
