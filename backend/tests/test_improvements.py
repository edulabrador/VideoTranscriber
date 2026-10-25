import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from backend import cli
from backend.api import routes
from backend.api.app import app
from backend.config import settings
from backend.core import model_manager, pipeline, transcriber
from backend.core.errors import DownloadError, JobCancelledError
from backend.core.exporter import (
    Paragraph,
    paragraphs,
    read_json,
    subtitle_cues,
    write_all,
    write_markdown,
    write_txt,
    write_vtt,
)
from backend.core.history import KEPT_MARKER, HistoryItem, HistoryStore, _source_key
from backend.core.job_manager import JobManager
from backend.core.transcriber import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
    resolve_job_model,
)
from backend.core.validators import is_supported_url, site_extractor_name


def make_result(segments, text=None, **kwargs):
    return TranscriptionResult(
        segments=segments, language="es", language_probability=0.9, duration=60,
        text=text if text is not None else " ".join(s.text for s in segments),
        model_size="small", device="cpu", compute_type="int8", batch_size=1,
        profile="balanced", **kwargs,
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "model_size", "small")
    monkeypatch.setattr(settings, "device", "cpu")
    monkeypatch.setattr(settings, "beam_size", 1)
    return HistoryStore(tmp_path / "history.json", 3, tmp_path / "output")


def saved(store, item_id, source="https://youtu.be/abc", result=None, **item):
    result = result or make_result([TranscriptSegment(0, 2, "Hola.")])
    write_all(result, store._output_dir / item_id, source=source, title="t",
              created_at="2026-10-25", audio_quality="best")
    store.add_entry(HistoryItem(item_id, "url", source, "t", "2026-10-25", 2, 1, "es", **item))


# Export ---------------------------------------------------------------------

def test_paragraphs_split_on_long_pauses():
    segments = [
        TranscriptSegment(0, 2, "Uno."), TranscriptSegment(2.5, 4, "Dos."),
        TranscriptSegment(7, 9, "Tres."),
    ]
    assert paragraphs(segments) == [Paragraph(0, "Uno. Dos."), Paragraph(7, "Tres.")]


def test_txt_and_markdown_use_paragraphs(tmp_path):
    result = make_result([TranscriptSegment(0, 2, "Uno."), TranscriptSegment(65, 66, "Dos.")])
    assert write_txt(result, tmp_path / "t.txt").read_text(encoding="utf-8") == "Uno.\n\nDos.\n"
    markdown = write_markdown(result, tmp_path / "t.md", title="Vídeo", source="https://x").read_text(
        encoding="utf-8")
    assert markdown.startswith("# Vídeo\n")
    assert "**[00:00]** Uno." in markdown and "**[01:05]** Dos." in markdown


def test_long_segment_becomes_short_wrapped_cues():
    text = " ".join(f"palabra{i}" for i in range(40))
    cues = subtitle_cues([TranscriptSegment(0, 20, text)])
    assert len(cues) > 3
    assert all(len(cue.text) <= 84 for cue in cues)
    assert all(cue.end - cue.start <= 6.01 for cue in cues)
    assert cues[0].start == 0 and cues[-1].end == pytest.approx(20)
    assert " ".join(cue.text for cue in cues) == text


def test_cues_follow_real_word_timings_when_present():
    words = [TranscriptWord(0, 0.5, "Hola"), TranscriptWord(9, 9.5, "mundo")]
    cues = subtitle_cues([TranscriptSegment(0, 9.5, "Hola mundo", words)])
    assert [(c.start, c.end, c.text) for c in cues] == [(0, 0.5, "Hola"), (9, 9.5, "mundo")]


def test_vtt_header_and_timestamps(tmp_path):
    vtt = write_vtt(make_result([TranscriptSegment(1.5, 3, "Hola.")]), tmp_path / "s.vtt")
    assert vtt.read_text(encoding="utf-8") == "WEBVTT\n\n00:00:01.500 --> 00:00:03.000\nHola.\n"


def test_options_round_trip_through_json(tmp_path):
    options = TranscriptionOptions("en", "translate", "Kubernetes", True)
    result = make_result([TranscriptSegment(0, 1, "Hi")], options=options)
    write_all(result, tmp_path, source="s", title="t", created_at="c", audio_quality="best")
    assert read_json(tmp_path / "transcript.json").options == options
    assert {p.name for p in tmp_path.iterdir()} == {
        "transcript.txt", "subtitles.srt", "subtitles.vtt", "transcript.md", "transcript.json",
    }


# History --------------------------------------------------------------------

@pytest.mark.parametrize("first,second", [
    ("https://www.instagram.com/reel/ABC/", "https://instagram.com/reels/ABC?igsh=1"),
    ("https://twitter.com/a/status/1", "https://mobile.x.com/b/status/1/video/1?s=20"),
    ("https://www.tiktok.com/@a/video/9", "https://m.tiktok.com/@a/video/9/"),
    ("https://vimeo.com/123?utm_source=x", "https://www.vimeo.com/123"),
])
def test_cache_key_normalises_equivalent_links(first, second):
    assert _source_key(first) == _source_key(second)


def test_cache_key_keeps_identifying_query_on_other_sites():
    assert _source_key("https://example.tv/watch?id=1") != _source_key("https://example.tv/watch?id=2")


def test_trimmed_history_entries_lose_their_files(store):
    for index in range(4):
        saved(store, f"job_{index}", source=f"https://youtu.be/v{index}")
    assert not (store._output_dir / "job_0").exists()
    assert (store._output_dir / "job_3").exists()
    assert [e["id"] for e in store.list_entries()] == ["job_3", "job_2", "job_1"]


def test_orphans_skip_folders_the_user_chose_to_keep(store):
    saved(store, "job_kept")
    saved(store, "job_gone")
    store.delete_entry("job_kept", delete_files=False)
    assert (store._output_dir / "job_kept" / KEPT_MARKER).exists()
    (store._output_dir / "job_orphan").mkdir()
    (store._output_dir / "not_a_job").mkdir()
    assert [p.name for p in store.orphan_outputs()] == ["job_orphan"]


def test_failed_entries_are_listed_but_never_cached_or_opened(store):
    store.add_entry(HistoryItem("job_bad", "url", "https://youtu.be/abc", "x", "c", 0, 0, "",
                                status="failed", error="Sin conexión"))
    listed = store.list_entries("conexión")
    assert listed[0]["status"] == "failed" and listed[0]["error"] == "Sin conexión"
    assert store.find_cached("https://youtu.be/abc", "balanced", "compact") is None
    assert store.load_result("job_bad") is None


def test_cache_requires_matching_transcription_options(store):
    saved(store, "job_es")
    assert store.find_cached("https://youtu.be/abc", "balanced", "best") is not None
    assert store.find_cached(
        "https://youtu.be/abc", "balanced", "best", TranscriptionOptions(language="en"),
    ) is None


def test_translation_never_uses_turbo():
    model, _ = resolve_job_model(
        "balanced", TranscriptionOptions(task="translate"), "large-v3-turbo", 1, "cpu",
    )
    assert model == "large-v3"


# Transcriber ------------------------------------------------------------------

def test_options_reach_faster_whisper(monkeypatch):
    model = Mock()
    model.transcribe.return_value = (iter([]), SimpleNamespace(
        language="en", language_probability=1.0, duration=3,
    ))
    monkeypatch.setattr(transcriber, "get_model", lambda *_: model)
    options = TranscriptionOptions("es", "translate", "OpenAI, Whisper", True)
    result = transcriber.transcribe_audio(
        "audio.wav", "small", "cpu", "int8", threading.Event(), options=options,
    )
    kwargs = model.transcribe.call_args.kwargs
    assert kwargs["language"] == "es" and kwargs["task"] == "translate"
    assert kwargs["initial_prompt"] == "OpenAI, Whisper" and kwargs["word_timestamps"] is True
    assert result.options == options


# Queue and model cache ----------------------------------------------------------

def test_turns_are_first_come_first_served_and_report_position():
    turns = pipeline.TranscriptionTurns()
    turns.acquire(threading.Event(), lambda _: None)
    order, positions = [], {}
    threads = []
    for name in ("a", "b", "c"):
        def work(name=name):
            turns.acquire(threading.Event(), lambda ahead: positions.setdefault(name, ahead))
            order.append(name)
            turns.release()
        thread = threading.Thread(target=work)
        thread.start()
        threads.append(thread)
        time.sleep(0.05)
    assert positions == {"a": 1, "b": 2, "c": 3}
    turns.release()
    for thread in threads:
        thread.join(2)
    assert order == ["a", "b", "c"]


def test_cancelled_waiter_leaves_the_queue():
    turns = pipeline.TranscriptionTurns()
    turns.acquire(threading.Event(), lambda _: None)
    event = threading.Event()
    event.set()
    with pytest.raises(JobCancelledError):
        turns.acquire(event, lambda _: None)
    turns.release()
    assert turns.try_acquire_idle()


class FakeCt2:
    def __init__(self, device):
        self.device = device
        self.model_is_loaded = True

    def unload_model(self, to_cpu=False):
        self.model_is_loaded = False

    def load_model(self):
        self.model_is_loaded = True


def test_model_cache_parks_previous_model_and_resumes_it(monkeypatch):
    loads = []

    def load(size, device, compute):
        loads.append(size)
        return SimpleNamespace(model=FakeCt2(device))

    monkeypatch.setattr(model_manager.ModelCache, "_load", staticmethod(load))
    cache = model_manager.ModelCache(2)
    small = cache.get("small", "cuda", "float16")
    turbo = cache.get("turbo", "cuda", "float16")
    assert not small.model.model_is_loaded and turbo.model.model_is_loaded
    assert cache.get("small", "cuda", "float16") is small
    assert small.model.model_is_loaded and not turbo.model.model_is_loaded
    cache.get("large", "cuda", "float16")
    assert loads == ["small", "turbo", "large"] and cache.loaded() == ["small", "large"]
    assert cache.clear() and cache.loaded() == []


def test_idle_models_are_released_only_when_nothing_runs(monkeypatch):
    cache = Mock()
    cache.idle_seconds.return_value = 1000
    monkeypatch.setattr(pipeline, "model_cache", cache)
    monkeypatch.setattr(settings, "model_idle_unload_seconds", 10)
    turns = pipeline.TranscriptionTurns()
    monkeypatch.setattr(pipeline, "_TURNS", turns)
    turns.acquire(threading.Event(), lambda _: None)
    assert pipeline.release_idle_models() is False
    turns.release()
    assert pipeline.release_idle_models() is cache.clear.return_value
    monkeypatch.setattr(settings, "model_idle_unload_seconds", 0)
    cache.clear.reset_mock()
    pipeline.release_idle_models()
    cache.clear.assert_not_called()


# API ------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch, store):
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(settings, "output_dir", store._output_dir)
    monkeypatch.setattr(routes, "history_store", store)
    monkeypatch.setattr(routes, "job_manager", JobManager())
    monkeypatch.setattr(routes, "_run_job", Mock())
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client


@pytest.mark.parametrize("name,content_type,expected", [
    ("clip.mkv", "application/octet-stream", 201),
    ("clip.opus", "", 201),
    ("notes.pdf", "application/octet-stream", 400),
])
def test_upload_accepts_media_extensions_with_generic_types(client, name, content_type, expected):
    response = client.post("/api/jobs/upload", files={"file": (name, b"x", content_type)})
    assert response.status_code == expected


def test_upload_options_are_validated(client):
    bad = client.post("/api/jobs/upload", data={"language": "español"},
                      files={"file": ("a.wav", b"x", "audio/wav")})
    assert bad.status_code == 422


def test_identical_running_request_reuses_the_job(client):
    body = {"url": "https://youtu.be/new1"}
    first = client.post("/api/jobs", json=body).json()["id"]
    assert client.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=new1"}).json()["id"] == first
    assert client.post("/api/jobs", json={**body, "language": "en"}).json()["id"] != first
    assert client.post("/api/jobs", json={**body, "force": True}).json()["id"] != first
    listed = client.get("/api/jobs").json()
    assert len(listed) == 3 and listed[0]["source"] == "https://youtu.be/new1"


def test_other_video_sites_are_accepted(client):
    assert client.post("/api/jobs", json={"url": "https://vimeo.com/76979871"}).status_code == 201
    assert client.post("/api/jobs", json={"url": "https://example.com/page"}).status_code == 400


def test_failed_jobs_are_recorded_in_history(monkeypatch, store):
    monkeypatch.setattr(routes, "history_store", store)
    manager = JobManager()
    monkeypatch.setattr(routes, "job_manager", manager)
    monkeypatch.setattr(routes, "run_pipeline", Mock(side_effect=DownloadError("Vídeo borrado")))
    job = manager.create_job(source="https://youtu.be/x")
    routes._run_job(job.id, pipeline.URLSource("https://youtu.be/x"), "balanced")
    entry = store.list_entries()[0]
    assert entry["id"] == job.id and entry["status"] == "failed"
    assert entry["error"] == "Vídeo borrado"


def test_progress_updates_do_not_hide_cancellation():
    manager = JobManager()
    job = manager.create_job()
    manager.request_cancel(job.id)
    manager.update_status(job.id, "transcribing", "50 %", 50)
    assert manager.get_job(job.id).status == "cancelling"


# Validators and CLI -------------------------------------------------------------

def test_generic_sites_exclude_collections_and_catch_all_pages():
    assert site_extractor_name("https://vimeo.com/76979871") == "Vimeo"
    assert not is_supported_url("https://www.youtube.com/playlist?list=PL123")
    assert not is_supported_url("https://example.com/video/123")
    assert not is_supported_url("file:///etc/passwd")


def test_cli_uses_a_unique_job_folder_and_history_id(tmp_path, monkeypatch):
    calls = []

    def fake_pipeline(job_id, source, **kwargs):
        calls.append((job_id, kwargs))
        return make_result([TranscriptSegment(0, 1, "Hola")])

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    media = tmp_path / "a.wav"
    media.write_bytes(b"x")
    runner = CliRunner()
    for _ in range(2):
        outcome = runner.invoke(cli.app, [str(media), "--no-clipboard", "--profile", "fast"])
        assert outcome.exit_code == 0, outcome.output
    (first, first_kwargs), (second, _) = calls
    assert first != second and first.startswith("job_")
    assert first_kwargs["output_dir"] == tmp_path / "output" / first
    assert first_kwargs["record_history"] is True and first_kwargs["profile"] == "fast"
    runner.invoke(cli.app, [str(media), "--no-clipboard", "--output-dir", str(tmp_path / "custom")])
    assert calls[-1][1]["record_history"] is False
