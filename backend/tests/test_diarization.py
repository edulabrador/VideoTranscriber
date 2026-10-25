import hashlib
import io
import os
import tarfile
import threading
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.api.app import app
from backend.config import settings
from backend.core import diarizer, pipeline
from backend.core.diarizer import SpeakerTurn, _ModelFile, assign_speakers
from backend.core.downloader import DownloadResult
from backend.core.errors import DiarizationError, JobCancelledError
from backend.core.exporter import read_json, write_all
from backend.core.history import HistoryStore
from backend.core.job_manager import JobManager
from backend.core.transcriber import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
)

TURNS = [SpeakerTurn(0, 4, 7), SpeakerTurn(4, 9, 3), SpeakerTurn(9.5, 12, 7)]


def result_with(segments, **kwargs):
    return TranscriptionResult(
        segments=segments, language="es", language_probability=0.9, duration=12,
        text=" ".join(s.text for s in segments), model_size="small", device="cpu",
        compute_type="int8", batch_size=1, profile="balanced", **kwargs,
    )


# Assigning speakers --------------------------------------------------------------

def test_segments_take_the_most_overlapping_speaker_numbered_by_appearance():
    segments = [
        TranscriptSegment(0, 3.5, "Hola."),
        TranscriptSegment(3.6, 8, "Qué tal."),
        TranscriptSegment(10, 11, "Bien."),
    ]
    labelled = assign_speakers(segments, TURNS)
    assert [s.speaker for s in labelled] == ["Hablante 1", "Hablante 2", "Hablante 1"]
    assert [s.text for s in labelled] == ["Hola.", "Qué tal.", "Bien."]


def test_segment_in_a_gap_takes_the_nearest_speaker():
    labelled = assign_speakers([TranscriptSegment(9.1, 9.4, "Eh.")], TURNS)
    assert labelled[0].speaker == "Hablante 1"


def test_word_timings_split_a_segment_where_the_speaker_changes():
    words = [
        TranscriptWord(2.5, 3.0, "Hola,"), TranscriptWord(3.1, 3.6, "¿qué"),
        TranscriptWord(4.2, 4.6, "Muy"), TranscriptWord(4.7, 5.0, "bien."),
    ]
    labelled = assign_speakers([TranscriptSegment(2.5, 5.0, "Hola, ¿qué Muy bien.", words)], TURNS)
    assert [(s.speaker, s.text, s.start, s.end) for s in labelled] == [
        ("Hablante 1", "Hola, ¿qué", 2.5, 3.6),
        ("Hablante 2", "Muy bien.", 4.2, 5.0),
    ]


def test_no_turns_leaves_segments_untouched():
    segments = [TranscriptSegment(0, 1, "Hola.")]
    assert assign_speakers(segments, []) == segments


# Exports --------------------------------------------------------------------------

def test_exports_name_speakers_without_repeating_them(tmp_path):
    segments = [
        TranscriptSegment(0, 2, "Hola.", speaker="Hablante 1"),
        TranscriptSegment(2.2, 3, "¿Qué tal?", speaker="Hablante 1"),
        TranscriptSegment(3.1, 4, "Bien.", speaker="Hablante 2"),
    ]
    options = TranscriptionOptions(diarize=True, num_speakers=2)
    write_all(result_with(segments, options=options), tmp_path, source="s", title="Charla",
              created_at="c", audio_quality="best")
    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8") == (
        "Hablante 1: Hola. ¿Qué tal?\n\nHablante 2: Bien.\n"
    )
    assert "**[00:03]** **Hablante 2:** Bien." in (tmp_path / "transcript.md").read_text(
        encoding="utf-8")
    srt = (tmp_path / "subtitles.srt").read_text(encoding="utf-8")
    assert "[Hablante 1] Hola." in srt and "\n¿Qué tal?\n" in srt and "[Hablante 2] Bien." in srt
    assert "<v Hablante 2>Bien." in (tmp_path / "subtitles.vtt").read_text(encoding="utf-8")
    saved = read_json(tmp_path / "transcript.json")
    assert [s.speaker for s in saved.segments] == ["Hablante 1", "Hablante 1", "Hablante 2"]
    assert saved.options == options


# Model download -------------------------------------------------------------------

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def tarball(member: str, content: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as archive:
        info = tarfile.TarInfo(member)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
        evil = tarfile.TarInfo("../../escape.onnx")
        evil.size = 1
        archive.addfile(evil, io.BytesIO(b"x"))
    return buffer.getvalue()


def test_download_verifies_hash_and_extracts_only_the_model(tmp_path, monkeypatch):
    payload = tarball("pkg/model.onnx", b"onnx-bytes")
    spec = _ModelFile("segmentation.onnx", "https://example/x.tar.bz2",
                      hashlib.sha256(payload).hexdigest(), "pkg/model.onnx")
    fetch = Mock(side_effect=lambda *_a, **_k: FakeResponse(payload))
    monkeypatch.setattr(diarizer, "urlopen", fetch)
    diarizer._download(spec, tmp_path / "models", threading.Event())
    assert (tmp_path / "models" / "segmentation.onnx").read_bytes() == b"onnx-bytes"
    assert sorted(p.name for p in (tmp_path / "models").iterdir()) == ["segmentation.onnx"]
    assert not (tmp_path / "escape.onnx").exists()
    diarizer._download(spec, tmp_path / "models", threading.Event())
    assert fetch.call_count == 1  # Already present: no second download.


def test_download_rejects_tampered_files(tmp_path, monkeypatch):
    spec = _ModelFile("embedding.onnx", "https://example/e.onnx", "0" * 64)
    monkeypatch.setattr(diarizer, "urlopen", lambda *_a, **_k: FakeResponse(b"tampered"))
    with pytest.raises(DiarizationError):
        diarizer._download(spec, tmp_path, threading.Event())
    assert not (tmp_path / "embedding.onnx").exists()


def test_cancelled_diarization_does_not_download(monkeypatch):
    ensure = Mock()
    monkeypatch.setattr(diarizer, "ensure_models", ensure)
    event = threading.Event()
    event.set()
    with pytest.raises(JobCancelledError):
        diarizer.diarize("audio.wav", None, event)
    ensure.assert_not_called()


# Pipeline and API -----------------------------------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "model_size", "small")
    monkeypatch.setattr(settings, "device", "cpu")
    monkeypatch.setattr(settings, "beam_size", 1)
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    return HistoryStore(tmp_path / "history.json", 50, tmp_path / "output")


@pytest.mark.parametrize("diarize", [True, False])
def test_pipeline_runs_diarization_only_when_requested(tmp_path, monkeypatch, store, diarize):
    monkeypatch.setattr(pipeline, "history_store", store)
    monkeypatch.setattr(pipeline.downloader, "download_media", lambda *_a, **_k: DownloadResult(
        tmp_path / "audio.webm", "Vídeo", None, 12,
    ))
    def transcribe(*args, **_kwargs):
        args[-2](100, 0)  # on_progress: transcription finished
        return result_with([TranscriptSegment(0, 3, "Hola."), TranscriptSegment(5, 8, "Adiós.")])

    monkeypatch.setattr(pipeline, "transcribe_audio", transcribe)
    run = Mock(return_value=TURNS)
    monkeypatch.setattr(diarizer, "diarize", run)
    monkeypatch.setattr(diarizer, "models_ready", lambda: True)
    statuses = []
    result = pipeline.run_pipeline(
        "job_diar", pipeline.URLSource("https://youtu.be/abc"),
        output_dir=store._output_dir / "job_diar",
        options=TranscriptionOptions(diarize=diarize, num_speakers=2 if diarize else None),
        on_stage=lambda status, message, progress: statuses.append((status, progress)),
    )
    if diarize:
        assert run.call_args.args[1] == 2
        assert [s.speaker for s in result.segments] == ["Hablante 1", "Hablante 2"]
        assert "diarization" in result.timings
        assert ("diarizing", 88) in statuses
        assert max(p for s, p in statuses if s == "transcribing") == 88
    else:
        run.assert_not_called()
        assert all(s.speaker is None for s in result.segments)


def test_api_validates_and_caches_diarization_options(tmp_path, monkeypatch, store):
    monkeypatch.setattr(settings, "output_dir", store._output_dir)
    monkeypatch.setattr(routes, "history_store", store)
    monkeypatch.setattr(routes, "job_manager", JobManager())
    monkeypatch.setattr(routes, "_run_job", Mock())
    write_all(result_with([TranscriptSegment(0, 1, "Hola.")]), store._output_dir / "job_plain",
              source="https://youtu.be/abc", title="t", created_at="c", audio_quality="best")
    from backend.core.history import HistoryItem
    store.add_entry(HistoryItem("job_plain", "url", "https://youtu.be/abc", "t", "c", 1, 1, "es"))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        url = "https://youtu.be/abc"
        assert client.post("/api/jobs", json={"url": url}).json()["cached"] is True
        fresh = client.post("/api/jobs", json={"url": url, "diarize": True})
        assert fresh.status_code == 201 and fresh.json()["cached"] is False
        assert client.post("/api/jobs", json={"url": url, "diarize": True,
                                              "num_speakers": 0}).status_code == 422
        upload = client.post("/api/jobs/upload", data={"diarize": "true", "num_speakers": "3"},
                             files={"file": ("a.wav", b"x", "audio/wav")})
        assert upload.status_code == 201
    options = routes._run_job.call_args.args[4]
    assert options.diarize is True and options.num_speakers == 3


def test_speaker_count_is_ignored_without_diarization():
    options = TranscriptionOptions(num_speakers=3)
    assert options.cache_fields()["num_speakers"] is None


@pytest.mark.skipif(
    not os.environ.get("VIDEO_TRANSCRIBER_MODEL_TEST"), reason="downloads models and audio",
)
def test_real_four_speaker_recording(tmp_path, monkeypatch):
    from urllib.request import urlretrieve

    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    audio = tmp_path / "four.wav"
    urlretrieve(
        f"{diarizer._RELEASES}/speaker-segmentation-models/0-four-speakers-zh.wav", audio,
    )
    turns = diarizer.diarize(audio, 4, threading.Event())
    assert len({turn.speaker for turn in turns}) == 4


@pytest.mark.parametrize("device,overlaps", [("cuda", True), ("cpu", False)])
def test_gpu_jobs_transcribe_while_another_job_identifies_speakers(
    tmp_path, monkeypatch, store, device, overlaps,
):
    """After a GPU transcription, diarization must not hold the transcription slot."""
    monkeypatch.setattr(pipeline, "history_store", store)
    monkeypatch.setattr(pipeline, "_TURNS", pipeline.TranscriptionTurns())
    monkeypatch.setattr(pipeline, "_DIARIZATION_TURNS", pipeline.TranscriptionTurns())
    monkeypatch.setattr(pipeline, "normalize_to_wav16k_mono", lambda *a, **k: tmp_path / "a.wav")
    diarizing = threading.Event()
    release_diarization = threading.Event()
    second_transcribed = threading.Event()

    def transcribe(*_args, **_kwargs):
        if diarizing.is_set():
            second_transcribed.set()
        result = result_with([TranscriptSegment(0, 3, "Hola.")])
        result.device = device
        return result

    def slow_diarize(*_args, **_kwargs):
        diarizing.set()
        release_diarization.wait(5)
        return TURNS

    monkeypatch.setattr(pipeline, "transcribe_audio", transcribe)
    monkeypatch.setattr(diarizer, "diarize", slow_diarize)
    monkeypatch.setattr(diarizer, "models_ready", lambda: True)
    first = threading.Thread(target=pipeline.run_pipeline, args=(
        "job_first", pipeline.FileSource(tmp_path / "a.mp4", "a.mp4")),
        kwargs={"output_dir": store._output_dir / "job_first",
                "options": TranscriptionOptions(diarize=True)})
    first.start()
    assert diarizing.wait(5)
    second = threading.Thread(target=pipeline.run_pipeline, args=(
        "job_second", pipeline.FileSource(tmp_path / "b.mp4", "b.mp4")),
        kwargs={"output_dir": store._output_dir / "job_second"})
    second.start()
    assert second_transcribed.wait(1) is overlaps
    release_diarization.set()
    first.join(5)
    second.join(5)
    assert second_transcribed.is_set()
