from unittest.mock import Mock

from fastapi.testclient import TestClient

from backend.api import app as app_module
from backend.api import routes
from backend.api.app import app
from backend.config import settings
from backend.core import pipeline
from backend.core.exporter import write_all
from backend.core.history import HistoryItem, HistoryStore
from backend.core.job_manager import JobManager
from backend.core.transcriber import TranscriptionResult, TranscriptSegment


def make_result(text="Hola."):
    return TranscriptionResult(
        segments=[TranscriptSegment(0, 1, text)], language="es", language_probability=0.9,
        duration=1, text=text, model_size="small", device="cpu", compute_type="int8",
        batch_size=1, profile="balanced",
    )


def save(store, item_id, source="https://youtu.be/abc"):
    write_all(make_result(), store._output_dir / item_id, source=source, title="t",
              created_at="c", audio_quality="best")
    store.add_entry(HistoryItem(item_id, "url", source, "t", "c", 1, 1, "es"))


def fail(store, item_id, source):
    store.add_entry(HistoryItem(item_id, "url", source, source, "c", 0, 0, "", "failed", "Error"))


def test_failures_never_push_transcripts_out(tmp_path):
    store = HistoryStore(tmp_path / "h.json", 2, tmp_path / "out", max_failed=2)
    save(store, "job_a", "https://youtu.be/a")
    save(store, "job_b", "https://youtu.be/b")
    for index in range(5):
        fail(store, f"job_f{index}", f"https://youtu.be/f{index}")
    entries = store.list_entries()
    assert [e["id"] for e in entries if e["status"] == "completed"] == ["job_b", "job_a"]
    assert [e["id"] for e in entries if e["status"] == "failed"] == ["job_f4", "job_f3"]
    assert (store._output_dir / "job_a").exists()


def test_a_success_clears_earlier_failures_of_the_same_video(tmp_path):
    store = HistoryStore(tmp_path / "h.json", 10, tmp_path / "out")
    fail(store, "job_f", "https://www.youtube.com/watch?v=abc")
    fail(store, "job_other", "https://youtu.be/other")
    save(store, "job_ok", "https://youtu.be/abc")
    assert [e["id"] for e in store.list_entries()] == ["job_ok", "job_other"]


def test_forced_retranscription_replaces_the_previous_result(tmp_path, monkeypatch):
    store = HistoryStore(tmp_path / "h.json", 10, tmp_path / "out")
    monkeypatch.setattr(settings, "model_size", "small")
    monkeypatch.setattr(settings, "device", "cpu")
    monkeypatch.setattr(settings, "beam_size", 1)
    monkeypatch.setattr(settings, "output_dir", store._output_dir)
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(routes, "history_store", store)
    monkeypatch.setattr(pipeline, "history_store", store)
    manager = JobManager()
    monkeypatch.setattr(routes, "job_manager", manager)
    save(store, "job_old")
    start = Mock()
    monkeypatch.setattr(routes, "_start_background", start)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        new_id = client.post("/api/jobs", json={"url": "https://youtu.be/abc", "force": True}).json()["id"]
    assert start.call_args.args[5] == "job_old"

    def finish(job_id, *_args, **_kwargs):
        save(store, job_id)
        return make_result()

    monkeypatch.setattr(routes, "run_pipeline", finish)
    routes._run_job(new_id, pipeline.URLSource("https://youtu.be/abc"), "balanced",
                    "balanced", None, "job_old")
    assert [e["id"] for e in store.list_entries()] == [new_id]
    assert not (store._output_dir / "job_old").exists()


def test_stale_temp_folders_are_removed_at_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    (tmp_path / "temp" / "job_left").mkdir(parents=True)
    (tmp_path / "temp" / "job_left" / "audio.wav").write_bytes(b"x")
    (tmp_path / "temp" / "keep.txt").write_text("not a job folder")
    assert app_module.remove_stale_temp_files() == 1
    assert [p.name for p in (tmp_path / "temp").iterdir()] == ["keep.txt"]


def test_editing_text_and_speakers_rewrites_every_export(tmp_path, monkeypatch):
    store = HistoryStore(tmp_path / "h.json", 10, tmp_path / "out")
    monkeypatch.setattr(settings, "output_dir", store._output_dir)
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(routes, "history_store", store)
    monkeypatch.setattr(routes, "job_manager", JobManager())
    result = make_result()
    result.segments = [
        TranscriptSegment(0, 1, "Ola.", speaker="Hablante 1"),
        TranscriptSegment(1.2, 2, "Bien.", speaker="Hablante 2"),
    ]
    write_all(result, store._output_dir / "job_ed", source="s", title="Charla",
              created_at="c", audio_quality="best")
    store.add_entry(HistoryItem("job_ed", "url", "s", "Charla", "c", 2, 2, "es"))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        edited = client.patch("/api/jobs/job_ed/transcript", json={
            "segments": [{"index": 0, "text": "Hola, ¿qué tal?"}],
            "speakers": {"Hablante 1": "Ana", "Hablante 2": "Luis"},
        })
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["edited"] is True
        assert [s["speaker"] for s in body["segments"]] == ["Ana", "Luis"]
        assert body["text"] == "Hola, ¿qué tal? Bien."
        assert client.get("/api/jobs/job_ed/result").json()["text"] == body["text"]
        assert client.patch("/api/jobs/job_ed/transcript",
                            json={"segments": [{"index": 9, "text": "x"}]}).status_code == 422
        assert client.patch("/api/jobs/job_ed/transcript",
                            json={"speakers": {"Ana": "<v Evil>"}}).status_code == 422
        assert client.patch("/api/jobs/job_missing/transcript", json={}).status_code == 404
    folder = store._output_dir / "job_ed"
    assert (folder / "transcript.txt").read_text(encoding="utf-8") == (
        "Ana: Hola, ¿qué tal?\n\nLuis: Bien.\n"
    )
    assert "<v Luis>Bien." in (folder / "subtitles.vtt").read_text(encoding="utf-8")
    assert store.list_entries()[0]["word_count"] == 4


def test_pipeline_keeps_a_playable_audio_copy(tmp_path, monkeypatch):
    import subprocess

    from backend.core.audio import find_ffmpeg

    if find_ffmpeg() is None:
        import pytest
        pytest.skip("FFmpeg is not installed")
    source = tmp_path / "tone.wav"
    subprocess.run([find_ffmpeg(), "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", str(source)], check=True)
    store = HistoryStore(tmp_path / "h.json", 10, tmp_path / "out")
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(settings, "output_dir", store._output_dir)
    monkeypatch.setattr(pipeline, "history_store", store)
    monkeypatch.setattr(routes, "history_store", store)
    monkeypatch.setattr(routes, "job_manager", JobManager())
    monkeypatch.setattr(pipeline, "transcribe_audio", lambda *_a, **_k: make_result())
    measured = pipeline.run_pipeline(
        "job_audio", pipeline.FileSource(source, "tone.wav"),
        output_dir=store._output_dir / "job_audio",
    )
    assert "audio_copy" in measured.timings
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/jobs/job_audio/result").json()["has_audio"] is True
        audio = client.get("/api/jobs/job_audio/audio", headers={"Range": "bytes=0-99"})
        assert audio.status_code == 206 and len(audio.content) == 100
        assert audio.headers["content-type"] == "audio/mp4"


def test_audio_copy_failure_does_not_fail_the_job(tmp_path, monkeypatch):
    from backend.core.errors import AudioExtractionError

    store = HistoryStore(tmp_path / "h.json", 10, tmp_path / "out")
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(pipeline, "history_store", store)
    monkeypatch.setattr(pipeline, "normalize_to_wav16k_mono", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(pipeline, "make_listening_copy",
                        Mock(side_effect=AudioExtractionError("sin ffmpeg")))
    monkeypatch.setattr(pipeline, "transcribe_audio", lambda *_a, **_k: make_result())
    result = pipeline.run_pipeline("job_x", pipeline.FileSource(tmp_path / "a.mp4", "a.mp4"),
                                   output_dir=store._output_dir / "job_x")
    assert result.text == "Hola." and "audio_copy" not in result.timings


def test_model_download_reports_megabytes(monkeypatch, tmp_path):
    import threading
    from types import SimpleNamespace

    from backend.core import model_manager, transcriber

    monkeypatch.setattr(settings, "models_dir", tmp_path)
    blobs = tmp_path / "models--Systran--faster-whisper-small" / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "abc.incomplete").write_bytes(b"x" * 1024 * 1024 * 3)
    monkeypatch.setattr(model_manager, "expected_download_bytes", lambda _m: 6 * 1024 * 1024)
    assert model_manager.downloaded_bytes("small") == 3 * 1024 * 1024
    monkeypatch.setattr(transcriber, "is_model_cached", lambda *_: False)

    def slow_model(*_args):
        import time
        time.sleep(0.35)
        model = Mock()
        model.transcribe.return_value = (iter([]), SimpleNamespace(
            language="es", language_probability=1.0, duration=1))
        return model

    monkeypatch.setattr(transcriber, "get_model", slow_model)
    original = model_manager.report_download_progress
    monkeypatch.setattr(transcriber, "report_download_progress",
                        lambda size, cb: original(size, cb, interval=0.1))
    messages = []
    transcriber.transcribe_audio(tmp_path / "a.wav", "small", "cpu", "int8", threading.Event(),
                                 on_status=lambda _s, message: messages.append(message))
    assert any("3 MB de 6 MB (50 %)" in message for message in messages), messages
