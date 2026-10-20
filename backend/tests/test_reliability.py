import asyncio
import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from backend.api import routes
from backend.api.app import app
from backend.config import settings
from backend.core import pipeline, transcriber
from backend.core.downloader import DownloadResult
from backend.core.errors import JobCancelledError
from backend.core.exporter import PROCESSING_VERSION, write_json
from backend.core.history import HistoryItem, HistoryStore
from backend.core.job_manager import JobManager
from backend.core.transcriber import TranscriptionResult


@pytest.fixture
def result():
    return TranscriptionResult(
        segments=[], language="es", language_probability=0.99, duration=3,
        text="Texto de prueba para buscar", model_size="small", device="cpu",
        compute_type="int8", batch_size=1, profile="balanced",
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "model_size", "small")
    monkeypatch.setattr(settings, "device", "cpu")
    monkeypatch.setattr(settings, "beam_size", 1)
    return HistoryStore(tmp_path / "history.json", 50, tmp_path / "output")


def save_result(store, result, item_id="job_saved", source="https://youtu.be/video123"):
    write_json(
        result, store._output_dir / item_id / "transcript.json",
        source=source, title="Vídeo guardado", created_at="2026-10-20", audio_quality="best",
    )
    (store._output_dir / item_id / "transcript.txt").write_text(result.text, encoding="utf-8")
    store.add_entry(HistoryItem(item_id, "url", source, "Vídeo guardado", "2026-10-20", 3, 5, "es"))


@pytest.fixture
def client(tmp_path, monkeypatch, store):
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(settings, "output_dir", store._output_dir)
    monkeypatch.setattr(routes, "history_store", store)
    monkeypatch.setattr(routes, "job_manager", JobManager())
    monkeypatch.setattr(routes, "_run_job", Mock())
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("name", ["../../outside.mp4", "C:\\outside.mp4", "normal.wav"])
def test_upload_filename_never_controls_destination(client, tmp_path, name):
    response = client.post("/api/jobs/upload", files={"file": (name, b"media", "video/mp4")})
    assert response.status_code == 201
    job_id = response.json()["id"]
    path = tmp_path / "temp" / job_id / "upload.media"
    assert path.read_bytes() == b"media"
    assert [p.name for p in path.parent.iterdir()] == ["upload.media"]
    assert not (tmp_path / "outside.mp4").exists()


def test_upload_rejects_oversize_empty_and_non_media(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "max_upload_bytes", 4)
    assert client.post("/api/jobs/upload", files={"file": ("x.wav", b"12345", "audio/wav")}).status_code == 413
    assert client.post("/api/jobs/upload", files={"file": ("x.wav", b"", "audio/wav")}).status_code == 400
    assert client.post("/api/jobs/upload", files={"file": ("x.txt", b"x", "text/plain")}).status_code == 400
    assert not list((tmp_path / "temp").glob("*/upload.media"))


def test_streamed_upload_limit_and_cleanup_without_declared_size(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "max_upload_bytes", 4)
    file = UploadFile(
        io.BytesIO(b"12345"), filename="../escape.wav",
        headers=Headers({"content-type": "audio/wav"}),
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.create_job_from_upload(file, "balanced"))
    assert error.value.status_code == 413
    assert file.file.closed
    assert not list((tmp_path / "temp").glob("*/upload.media"))


def test_force_retranscription_bypasses_cache(client, store, result):
    save_result(store, result)
    cached = client.post("/api/jobs", json={"url": "https://youtu.be/video123"})
    assert cached.json()["cached"] is True
    fresh = client.post("/api/jobs", json={"url": "https://youtu.be/video123", "force": True})
    assert fresh.status_code == 201
    assert fresh.json()["id"] != cached.json()["id"]
    assert fresh.json()["cached"] is False


@pytest.mark.parametrize("changed", [
    {"processing_version": PROCESSING_VERSION - 1},
    {"model_size": "different"},
    {"beam_size": 5},
])
def test_cache_rejects_old_processing_or_changed_model_settings(store, result, changed):
    save_result(store, result)
    path = store._output_dir / "job_saved" / "transcript.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(changed)
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.find_cached("https://youtu.be/video123", "balanced", "compact") is None
    assert store.load_result("job_saved").text == result.text


def test_results_recover_after_backend_restart(client, store, result):
    save_result(store, result)
    assert routes.job_manager.get_job("job_saved") is None
    assert client.get("/api/jobs/job_saved").json()["status"] == "completed"
    assert client.get("/api/jobs/job_saved/result").json()["text"] == result.text
    assert client.get("/api/jobs/job_missing").status_code == 404


def test_search_reads_older_transcripts_and_delete_can_preserve_files(client, store, result):
    save_result(store, result)
    result.text = "Otra grabación"
    save_result(store, result, "job_new1")
    save_result(store, result, "job_new2")
    matches = client.get("/api/history", params={"q": "prueba para buscar"}).json()
    assert [item["id"] for item in matches] == ["job_saved"]
    assert client.delete("/api/history/job_saved").status_code == 204
    assert (store._output_dir / "job_saved" / "transcript.json").exists()
    assert client.delete("/api/history/job_new1?delete_files=true").status_code == 204
    assert not (store._output_dir / "job_new1").exists()
    assert client.get("/api/jobs/job_new1/result").status_code == 404


def test_history_paths_cannot_escape_output_directory(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    store._write([{"id": "../outside"}])
    assert store.load_result("../outside") is None
    assert store.delete_entry("../outside", delete_files=True) is False
    assert (outside / "keep.txt").exists()


def test_failed_atomic_history_write_keeps_previous_data(store, monkeypatch):
    store._write([{"id": "job_old"}])
    previous = store._path.read_bytes()
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("disk error")))
    with pytest.raises(OSError):
        store._write([{"id": "job_new"}])
    assert store._path.read_bytes() == previous


@pytest.mark.parametrize("cached", [True, False])
def test_model_status_is_visible_before_inference(monkeypatch, result, cached):
    statuses = []
    model = Mock()
    model.transcribe.return_value = (iter([]), SimpleNamespace(
        language="es", language_probability=1.0, duration=3,
    ))
    monkeypatch.setattr(transcriber, "get_model", lambda *_: model)
    monkeypatch.setattr(transcriber, "is_model_cached", lambda *_: cached)
    measured = transcriber.transcribe_audio(
        Path("audio.wav"), "small", "cpu", "int8", threading.Event(),
        on_status=lambda status, message: statuses.append((status, message)),
    )
    assert statuses[0][0] == "loading_model"
    assert ("Cargando" if cached else "Descargando") in statuses[0][1]
    assert statuses[1][0] == "transcribing"
    assert set(measured.timings) == {"model_loading", "audio_analysis", "transcription"}
    assert all(value >= 0 for value in measured.timings.values())


def test_cancelled_job_does_not_load_model(monkeypatch):
    model = Mock()
    monkeypatch.setattr(transcriber, "get_model", model)
    event = threading.Event()
    event.set()
    with pytest.raises(JobCancelledError):
        transcriber.transcribe_audio(Path("audio.wav"), "small", "cpu", "int8", event)
    model.assert_not_called()


def test_pipeline_persists_original_audio_and_stages(tmp_path, monkeypatch, store, result):
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(pipeline, "history_store", store)
    monkeypatch.setattr(pipeline.downloader, "download_media", lambda *_args, **_kwargs: DownloadResult(
        tmp_path / "audio.webm", "Vídeo", None, 3, "es", "251-es", "original",
    ))

    def infer(*args):
        args[-1]("loading_model", "Cargando modelo")
        args[-1]("transcribing", "Analizando audio")
        args[-2](50, 1)
        return result

    monkeypatch.setattr(pipeline, "transcribe_audio", infer)
    statuses = []
    pipeline.run_pipeline(
        "job_pipeline", pipeline.URLSource("https://youtu.be/video123"),
        output_dir=store._output_dir / "job_pipeline",
        on_stage=lambda status, message, progress: statuses.append((status, message, progress)),
    )
    saved = store.load_result("job_pipeline")
    assert saved.audio_language == "es"
    assert saved.audio_selection == "original"
    assert saved.audio_format_id == "251-es"
    assert {"queued", "loading_model", "transcribing", "completed"} <= {s[0] for s in statuses}
    assert any("Audio: es (original)" in s[1] for s in statuses)
    assert not (settings.temp_dir / "job_pipeline").exists()
    assert {"download", "queue", "processing_total"} <= saved.timings.keys()


def test_history_previews_are_bounded_but_search_and_open_keep_full_text(client, store, result):
    result.text = "inicio " * 500 + "término al final"
    save_result(store, result)
    preview = client.get("/api/history").json()[0]["text"]
    assert preview == result.text[:240]
    matches = client.get("/api/history", params={"q": "término al final"}).json()
    assert matches[0]["id"] == "job_saved"
    assert len(matches[0]["text"]) == 240
    assert client.get("/api/jobs/job_saved/result").json()["text"] == result.text


def test_cache_hit_reads_transcript_json_only_once(store, result, monkeypatch):
    save_result(store, result)
    real_read = Path.read_text
    reads = []

    def read(path, *args, **kwargs):
        if path.name == "transcript.json":
            reads.append(path)
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert store.find_cached("https://youtu.be/video123", "balanced", "compact") is not None
    assert len(reads) == 1


def test_timings_survive_export_restart_and_api_and_legacy_files(client, store, result):
    result.timings = {"model_loading": 1.25, "transcription": 2.5, "processing_total": 4.0}
    save_result(store, result)
    assert store.load_result("job_saved").timings == result.timings
    assert client.get("/api/jobs/job_saved/result").json()["timings"] == result.timings
    path = store._output_dir / "job_saved" / "transcript.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["timings"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.load_result("job_saved").timings == {}


def test_file_pipeline_passes_cancel_and_timeout_and_records_preparation(
    tmp_path, monkeypatch, store, result,
):
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(settings, "audio_preparation_timeout_seconds", 7)
    monkeypatch.setattr(pipeline, "history_store", store)
    prepare = Mock(return_value=tmp_path / "audio.wav")
    monkeypatch.setattr(pipeline, "normalize_to_wav16k_mono", prepare)
    monkeypatch.setattr(pipeline, "transcribe_audio", lambda *_: result)
    event = threading.Event()
    measured = pipeline.run_pipeline(
        "job_file", pipeline.FileSource(tmp_path / "input.mp4", "input.mp4"),
        cancel_event=event, output_dir=store._output_dir / "job_file",
    )
    assert prepare.call_args.args[2] is event
    assert prepare.call_args.kwargs["timeout"] == 7
    assert "audio_preparation" in measured.timings
    assert "download" not in measured.timings
    assert measured.timings["processing_total"] >= measured.timings["audio_preparation"]


def test_pipeline_cancellation_during_preparation_cleans_up_without_loading_model(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(pipeline, "normalize_to_wav16k_mono", Mock(side_effect=JobCancelledError()))
    infer = Mock()
    monkeypatch.setattr(pipeline, "transcribe_audio", infer)
    with pytest.raises(JobCancelledError):
        pipeline.run_pipeline("job_cancel", pipeline.FileSource(tmp_path / "a.mp4", "a.mp4"))
    infer.assert_not_called()
    assert not (settings.temp_dir / "job_cancel").exists()


def test_inference_timings_measure_separate_stages(monkeypatch):
    model = Mock()
    model.transcribe.return_value = (iter([]), SimpleNamespace(
        language="es", language_probability=1.0, duration=3,
    ))
    monkeypatch.setattr(transcriber, "get_model", lambda *_: model)
    clock = iter([0.0, 2.0, 3.0, 5.0, 6.0, 7.0])
    monkeypatch.setattr(transcriber.time, "perf_counter", lambda: next(clock))
    measured = transcriber.transcribe_audio(
        Path("audio.wav"), "small", "cpu", "int8", threading.Event(),
    )
    assert measured.timings == {"model_loading": 2.0, "audio_analysis": 2.0, "transcription": 1.0}
