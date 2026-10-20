import subprocess
import sys
import threading
import wave
from unittest.mock import Mock

import pytest

from backend.core import audio
from backend.core.errors import AudioExtractionError, JobCancelledError


@pytest.mark.parametrize("mode", ["success", "failure", "timeout", "cancel"])
def test_normalization_process_is_reaped_and_partial_files_removed(tmp_path, monkeypatch, mode):
    output = tmp_path / "audio.wav"
    output.touch()
    event = threading.Event()
    real_popen = subprocess.Popen
    children = []
    commands = []

    def spawn(command, **kwargs):
        commands.append(command)
        script = (
            "import sys; sys.stderr.write('x' * 100000); sys.exit(1)"
            if mode == "failure" else
            "import time; time.sleep(60)" if mode in {"timeout", "cancel"} else "pass"
        )
        child = real_popen([sys.executable, "-c", script], **kwargs)
        children.append(child)
        if mode == "cancel":
            event.set()
        return child

    monkeypatch.setattr(audio, "find_ffmpeg", lambda: "ffmpeg.exe")
    monkeypatch.setattr(audio.subprocess, "Popen", spawn)
    if mode == "success":
        assert audio.normalize_to_wav16k_mono(tmp_path / "input.mp4", output, event) == output
        assert output.exists()
    else:
        error = JobCancelledError if mode == "cancel" else AudioExtractionError
        with pytest.raises(error):
            audio.normalize_to_wav16k_mono(
                tmp_path / "input.mp4", output, event, timeout=0.15 if mode == "timeout" else 5,
            )
        assert not output.exists()
    assert commands[0][0] == "ffmpeg.exe"
    assert commands[0][-6:] == ["-ac", "1", "-ar", "16000", "-vn", str(output)]
    assert all(child.poll() is not None for child in children)


def test_pre_cancelled_normalization_never_spawns(tmp_path, monkeypatch):
    event = threading.Event()
    event.set()
    spawn = Mock()
    monkeypatch.setattr(audio, "find_ffmpeg", lambda: "ffmpeg.exe")
    monkeypatch.setattr(audio.subprocess, "Popen", spawn)
    with pytest.raises(JobCancelledError):
        audio.normalize_to_wav16k_mono(tmp_path / "in.mp4", tmp_path / "out.wav", event)
    spawn.assert_not_called()


def test_actual_ffmpeg_normalizes_and_rejects_invalid_media(tmp_path):
    if audio.find_ffmpeg() is None:
        pytest.skip("FFmpeg is not installed")
    source = tmp_path / "stereo.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0" * 44100 * 4)
    output = tmp_path / "mono.wav"
    audio.normalize_to_wav16k_mono(source, output)
    with wave.open(str(output), "rb") as stream:
        assert (stream.getnchannels(), stream.getframerate()) == (1, 16000)
        assert stream.getnframes() == 16000
    source.write_bytes(b"not media")
    with pytest.raises(AudioExtractionError):
        audio.normalize_to_wav16k_mono(source, output)
    assert not output.exists()
