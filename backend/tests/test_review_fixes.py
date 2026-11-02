"""Regression tests for the bugs found in the code review."""
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from backend import cli
from backend.api import app as app_module
from backend.api import routes
from backend.api.app import app
from backend.config import settings
from backend.core import diarizer, downloader, pipeline
from backend.core.errors import DownloadError, JobCancelledError
from backend.core.exporter import write_all, write_vtt
from backend.core.history import KEPT_MARKER, HistoryItem, HistoryStore
from backend.core.job_manager import JobManager
from backend.core.model_manager import model_cache
from backend.core.transcriber import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
)

LOCAL = {"base_url": "http://127.0.0.1", "client": ("127.0.0.1", 50000)}


def make_result(segments=None, text="hola adiós"):
    segments = segments if segments is not None else [
        TranscriptSegment(0, 1, "hola"), TranscriptSegment(1, 2, "adiós"),
    ]
    return TranscriptionResult(
        segments=segments, language="es", language_probability=1, duration=2,
        text=text, model_size="small", device="cpu", compute_type="int8",
        batch_size=1, profile="balanced",
    )


def save(store, job_id, source="https://youtu.be/abc", created_at="2026-10-01"):
    write_all(make_result(), store._output_dir / job_id, source=source, title=f"T {job_id}",
              created_at=created_at, audio_quality="best")
    store.add_entry(HistoryItem(job_id, "url", source, f"T {job_id}", created_at, 2, 2, "es"))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "model_size", "small")
    monkeypatch.setattr(settings, "device", "cpu")
    monkeypatch.setattr(settings, "beam_size", 1)
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    return HistoryStore(tmp_path / "data" / "history.json", 50, tmp_path / "output")


@pytest.fixture
def api(store, monkeypatch):
    monkeypatch.setattr(routes, "history_store", store)
    monkeypatch.setattr(routes, "job_manager", JobManager())
    with TestClient(app, **LOCAL) as client:
        yield client


# 1. A damaged history is rebuilt instead of being overwritten --------------------

@pytest.mark.parametrize("damage", ["truncated", "empty", "not_a_list"])
def test_damaged_history_is_backed_up_and_rebuilt_from_saved_transcripts(store, damage):
    for index in range(3):
        save(store, f"job_{index}", f"https://youtu.be/v{index}", f"2026-10-0{index + 1}")
    original = store._path.read_text(encoding="utf-8")
    store._path.write_text(
        {"truncated": original[:-5], "empty": "", "not_a_list": '{"a": 1}'}[damage],
        encoding="utf-8",
    )

    save(store, "job_new", "https://youtu.be/new", "2026-10-09")

    ids = [entry["id"] for entry in store.list_entries()]
    assert ids == ["job_new", "job_2", "job_1", "job_0"]
    assert store.orphan_outputs() == []
    backups = list(store._path.parent.glob("history.corrupt-*.json"))
    assert len(backups) == (0 if damage == "empty" else 1)


def test_rebuilt_history_skips_folders_deleted_on_purpose(store):
    save(store, "job_keep")
    save(store, "job_gone")
    store.delete_entry("job_gone", delete_files=False)
    store._path.write_text("[", encoding="utf-8")
    assert [entry["id"] for entry in store.list_entries()] == ["job_keep"]


def test_history_written_by_two_processes_keeps_every_entry(tmp_path):
    # Two stores on the same file stand for the server and the CLI: only the
    # file lock, not the per-object thread lock, keeps their writes apart.
    first = HistoryStore(tmp_path / "h.json", 500, tmp_path / "out")
    second = HistoryStore(tmp_path / "h.json", 500, tmp_path / "out")

    def add(store, prefix):
        for index in range(40):
            store.add_entry(HistoryItem(f"job_{prefix}{index}", "url", f"s{prefix}{index}",
                                        "t", "c", 1, 1, "es"))

    threads = [threading.Thread(target=add, args=(first, "a")),
               threading.Thread(target=add, args=(second, "b"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(json.loads((tmp_path / "h.json").read_text(encoding="utf-8"))) == 80


# 2. A long queue no longer blocks the rest of the API ------------------------------

def test_queued_jobs_do_not_starve_other_background_calls(api, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(routes, "run_pipeline", lambda *_a, **_k: gate.wait(10))
    monkeypatch.setattr(routes.summarizer, "status",
                        lambda: routes.summarizer.OllamaStatus(False))
    try:
        jobs = (os.cpu_count() or 1) + 6  # More than asyncio's default pool.
        for index in range(jobs):
            response = api.post("/api/jobs", json={"url": f"https://youtu.be/abcdefghi{index:02d}"})
            assert response.status_code == 201
        answer = {}
        thread = threading.Thread(
            target=lambda: answer.setdefault("status", api.get("/api/summary/status").status_code),
            daemon=True,
        )
        thread.start()
        thread.join(5)
        assert answer.get("status") == 200
    finally:
        gate.set()


def test_downloads_are_limited_while_the_rest_wait_their_turn(monkeypatch):
    slots = pipeline.PreparationSlots(2)
    cancel = threading.Event()
    active, peak = [0], [0]
    lock = threading.Lock()
    waited = []

    def job(index):
        slots.acquire(cancel, lambda: waited.append(index))
        try:
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
        finally:
            slots.release()

    threads = [threading.Thread(target=job, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak[0] == 2 and waited


def test_waiting_for_a_download_slot_can_be_cancelled():
    slots = pipeline.PreparationSlots(1)
    slots.acquire(threading.Event(), lambda: None)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(JobCancelledError):
        slots.acquire(cancel, lambda: None)


# 3. CUDA libraries are only required where they exist -----------------------------

def test_cuda_wheels_are_not_required_on_macos():
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    dependencies = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    for dependency in (d for d in dependencies if d.startswith("nvidia-")):
        assert "sys_platform != 'darwin'" in dependency, dependency


# 4. --no-history results survive the orphan clean-up -------------------------------

def test_cli_no_history_output_is_never_cleaned_as_an_orphan(store, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "history_store", store)
    media = tmp_path / "clip.wav"
    media.write_bytes(b"x")

    def fake_pipeline(job_id, _source, *, output_dir, record_history, **_kwargs):
        assert record_history is False
        write_all(make_result(), output_dir, source="clip.wav", title="clip",
                  created_at="c", audio_quality="best")
        return make_result()

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    outcome = CliRunner().invoke(cli.app, [str(media), "--no-history", "--no-clipboard"])
    assert outcome.exit_code == 0, outcome.output
    [folder] = list(store._output_dir.iterdir())
    assert (folder / KEPT_MARKER).exists()
    assert store.orphan_outputs() == []


# 5. Routes that touch locks or disk no longer freeze the event loop ----------------

def test_health_waits_for_the_model_lock_without_blocking_other_requests(api):
    model_cache._lock.acquire()  # A model is being downloaded or loaded.
    health = {}
    waiting = threading.Thread(
        target=lambda: health.setdefault("status", api.get("/api/health").status_code),
        daemon=True,
    )
    try:
        waiting.start()
        time.sleep(0.3)
        answer = {}
        thread = threading.Thread(
            target=lambda: answer.setdefault("status", api.get("/api/jobs").status_code),
            daemon=True,
        )
        thread.start()
        thread.join(2)
        assert answer.get("status") == 200
        assert "status" not in health  # Still waiting for the model, as it should.
    finally:
        model_cache._lock.release()
    waiting.join(5)
    assert health.get("status") == 200


# 6. Deleting is all or nothing ------------------------------------------------------

def test_delete_with_a_file_in_use_changes_nothing(api, store, monkeypatch):
    save(store, "job_busy")

    def in_use(self, target):
        raise PermissionError("El archivo está en uso")

    monkeypatch.setattr(Path, "rename", in_use)
    response = api.delete("/api/history/job_busy?delete_files=true")
    assert response.status_code == 409
    assert "en uso" in response.json()["detail"]
    assert [entry["id"] for entry in store.list_entries()] == ["job_busy"]
    assert (store._output_dir / "job_busy" / "transcript.json").exists()


def test_failed_history_write_restores_the_folder(store, monkeypatch):
    save(store, "job_safe")
    monkeypatch.setattr(store, "_write", Mock(side_effect=OSError("disco lleno")))
    with pytest.raises(OSError):
        store.delete_entry("job_safe", delete_files=True)
    assert (store._output_dir / "job_safe" / "transcript.json").exists()


def test_interrupted_deletions_are_finished_at_startup(store, monkeypatch):
    monkeypatch.setattr(app_module, "history_store", store)
    leftover = store._output_dir / ".deleting-job_old-1234"
    leftover.mkdir(parents=True)
    (leftover / "audio.m4a").write_bytes(b"x")
    with TestClient(app, **LOCAL):
        pass
    assert not leftover.exists()


# 8. "Reintentar" repeats the failed request ----------------------------------------

def test_failed_link_keeps_the_options_needed_to_retry_it(api, store, monkeypatch):
    def fail(*_args, **_kwargs):
        raise DownloadError("sin conexión")

    monkeypatch.setattr(routes, "run_pipeline", fail)
    options = TranscriptionOptions(language="en", diarize=True, num_speakers=3)
    job = routes.job_manager.create_job(source="https://youtu.be/abc")
    routes._run_job(job.id, pipeline.URLSource("https://youtu.be/abc"), "precise", "best", options)
    [entry] = api.get("/api/history").json()
    assert entry["status"] == "failed"
    assert entry["retry"] == {
        "profile": "precise", "audio_quality": "best", "language": "en",
        "task": "transcribe", "initial_prompt": None, "word_timestamps": False,
        "diarize": True, "num_speakers": 3,
    }
    retried = api.post("/api/jobs", json={"url": entry["source"], "force": True, **entry["retry"]})
    assert retried.status_code == 201


def test_unexpected_errors_still_finish_the_job(api, monkeypatch):
    monkeypatch.setattr(routes, "run_pipeline", Mock(side_effect=RuntimeError("fallo raro")))
    job = routes.job_manager.create_job(source="s")
    routes._run_job(job.id, pipeline.URLSource("https://youtu.be/abc"), "balanced")
    assert job.status == "failed"
    assert job.error == {"code": "internal_error",
                         "message": "Se produjo un error inesperado: fallo raro"}


# 9. WebVTT escapes markup -----------------------------------------------------------

def test_vtt_and_srt_escape_text_that_would_break_the_cue(tmp_path):
    from backend.core.exporter import write_srt

    result = make_result([TranscriptSegment(0, 1, "si a <b y c & d --> e", speaker="Ana & Luis")])
    vtt = write_vtt(result, tmp_path / "s.vtt").read_text(encoding="utf-8")
    assert "<v Ana &amp; Luis>si a &lt;b y c &amp; d -&gt; e" in vtt
    srt = write_srt(result, tmp_path / "s.srt").read_text(encoding="utf-8")
    assert srt.count("-->") == 1


# Job states -------------------------------------------------------------------------

def test_only_the_result_can_mark_a_job_completed():
    manager = JobManager()
    job = manager.create_job()
    manager.update_status(job.id, "completed", "Transcripción completada.", 100)
    assert job.status == "queued" and job.result is None
    manager.set_result(job.id, make_result())
    assert job.status == "completed"
    manager.update_status(job.id, "transcribing", "tarde", 50)
    assert job.status == "completed"


def test_cancelling_is_not_overwritten_by_a_late_progress_update():
    manager = JobManager()
    job = manager.create_job()
    manager.update_status(job.id, "transcribing", "50 %", 50)
    assert manager.request_cancel(job.id)
    manager.update_status(job.id, "transcribing", "60 %", 60)
    assert job.status == "cancelling"


def test_server_shutdown_cancels_running_jobs(store, monkeypatch):
    manager = JobManager()
    monkeypatch.setattr(routes, "job_manager", manager)
    running = manager.create_job(source="a")
    finished = manager.create_job(source="b")
    manager.set_result(finished.id, make_result())
    with TestClient(app, **LOCAL):
        pass
    assert running.cancel_event.is_set()
    assert not finished.cancel_event.is_set()


# Pipeline ---------------------------------------------------------------------------

def test_cpu_speaker_identification_keeps_its_place_in_the_queue(tmp_path, monkeypatch, store):
    monkeypatch.setattr(pipeline, "history_store", store)
    monkeypatch.setattr(pipeline, "_TURNS", pipeline.TranscriptionTurns())
    monkeypatch.setattr(pipeline, "_DIARIZATION_TURNS", pipeline.TranscriptionTurns())
    monkeypatch.setattr(diarizer, "models_ready", lambda: True)
    events = []
    first_transcribing = threading.Event()
    second_waiting = threading.Event()

    def transcribe(path, *_args, **_kwargs):
        events.append(f"transcribe {path.parent.name}")
        if not first_transcribing.is_set():
            first_transcribing.set()
            assert second_waiting.wait(5)
        return make_result([TranscriptSegment(0, 1, "hola")])

    def diarize(path, *_args, **_kwargs):
        events.append("diarize")
        return [diarizer.SpeakerTurn(0, 1, 0)]

    monkeypatch.setattr(pipeline, "transcribe_audio", transcribe)
    monkeypatch.setattr(diarizer, "diarize", diarize)
    monkeypatch.setattr(pipeline, "normalize_to_wav16k_mono",
                        lambda source, *_a, **_k: source.parent / "audio.wav")
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()

    def stage(status, _message, _progress=None):
        if status == "queued" and "por delante" in _message:
            second_waiting.set()

    first = threading.Thread(target=pipeline.run_pipeline, args=(
        "job_first", pipeline.FileSource(tmp_path / "first" / "a.wav", "a.wav")), kwargs={
        "output_dir": store._output_dir / "job_first", "options": TranscriptionOptions(diarize=True)})
    first.start()
    assert first_transcribing.wait(5)
    second = threading.Thread(target=pipeline.run_pipeline, args=(
        "job_second", pipeline.FileSource(tmp_path / "second" / "b.wav", "b.wav")), kwargs={
        "output_dir": store._output_dir / "job_second", "on_stage": stage})
    second.start()
    first.join(10)
    second.join(10)
    assert events == ["transcribe first", "diarize", "transcribe second"]


def test_failed_job_leaves_no_partial_output_folder(tmp_path, monkeypatch, store):
    monkeypatch.setattr(pipeline, "history_store", store)
    monkeypatch.setattr(pipeline, "normalize_to_wav16k_mono", lambda *a, **k: tmp_path / "a.wav")
    monkeypatch.setattr(pipeline, "transcribe_audio", lambda *a, **k: make_result())

    def copy_then_cancel(_source, target, *_args, **_kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"audio")
        raise JobCancelledError()

    monkeypatch.setattr(pipeline, "make_listening_copy", copy_then_cancel)
    with pytest.raises(JobCancelledError):
        pipeline.run_pipeline("job_partial", pipeline.FileSource(tmp_path / "a.mp4", "a.mp4"),
                              output_dir=store._output_dir / "job_partial")
    assert not (store._output_dir / "job_partial").exists()


# Downloads and uploads ----------------------------------------------------------------

class LiveYDL:
    info = {"id": "live1", "title": "Directo", "is_live": True, "live_status": "is_live"}

    def __init__(self, opts):
        self.params = opts
        self.processed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def extract_info(self, _url, download=True):
        assert download is False
        return dict(self.info)

    def process_ie_result(self, info, download=True):
        raise AssertionError("A live stream must not start downloading")


@pytest.mark.parametrize("status", ["is_live", "is_upcoming"])
def test_live_streams_are_refused_before_downloading(tmp_path, monkeypatch, status):
    LiveYDL.info = {"id": "live1", "title": "Directo", "is_live": status == "is_live",
                    "live_status": status}
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", LiveYDL)
    for url in ("https://www.youtube.com/live/abcdefghijk", "https://vimeo.com/123456"):
        with pytest.raises(DownloadError):
            downloader.download_media(url, tmp_path, None, threading.Event())


def test_non_youtube_sites_download_after_reading_metadata(tmp_path, monkeypatch):
    calls = []

    class SiteYDL(LiveYDL):
        def extract_info(self, _url, download=True):
            calls.append(("extract", download))
            return {"id": "v1", "title": "Vídeo", "live_status": "was_live"}

        def process_ie_result(self, info, download=True):
            calls.append(("process", download))
            return info

        def prepare_filename(self, info):
            path = Path(self.params["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", "mp4"))
            path.write_bytes(b"x")
            return str(path)

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", SiteYDL)
    result = downloader.download_media("https://vimeo.com/1", tmp_path, None, threading.Event())
    assert calls == [("extract", False), ("process", True)]
    assert result.title == "Vídeo"


def test_oversized_upload_is_refused_before_reading_the_body(api, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    response = api.post(
        "/api/jobs/upload",
        content=b"x" * (2 * 1024 * 1024),
        headers={"content-type": "multipart/form-data; boundary=abc",
                 "origin": "http://127.0.0.1:5187"},
    )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5187"
    assert api.get("/api/health").json()["max_upload_bytes"] == 10

