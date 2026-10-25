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
