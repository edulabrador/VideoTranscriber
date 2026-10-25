"""Real models on real audio, to catch breakage when faster-whisper or CTranslate2 change.

Skipped by default; CI runs it with VIDEO_TRANSCRIBER_MODEL_TEST=1. Downloads the
Whisper "tiny" model (about 75 MB) and a short recording from the sherpa-onnx releases.
"""
import os
import threading
from urllib.request import urlretrieve

import pytest

from backend.config import settings
from backend.core import diarizer, model_manager, transcriber
from backend.core.exporter import subtitle_cues

pytestmark = pytest.mark.skipif(
    not os.environ.get("VIDEO_TRANSCRIBER_MODEL_TEST"), reason="downloads models and audio",
)


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "four-speakers.wav"
    urlretrieve(
        f"{diarizer._RELEASES}/speaker-segmentation-models/0-four-speakers-zh.wav", path,
    )
    return path


def test_tiny_model_transcribes_real_speech(recording, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    monkeypatch.setattr(model_manager, "model_cache", model_manager.ModelCache(1))
    statuses = []
    result = transcriber.transcribe_audio(
        recording, "tiny", "cpu", "int8", threading.Event(),
        on_status=lambda status, message: statuses.append(status),
        options=transcriber.TranscriptionOptions(word_timestamps=True),
    )
    assert result.language == "zh"
    assert 50 < result.duration < 60
    assert len(result.text) > 20
    assert result.segments and result.segments[0].words
    assert subtitle_cues(result.segments)
    assert statuses[0] == "loading_model"
