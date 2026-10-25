import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.api.app import app
from backend.config import settings
from backend.core import summarizer
from backend.core.exporter import write_all
from backend.core.history import HistoryItem, HistoryStore
from backend.core.job_manager import JobManager
from backend.core.transcriber import TranscriptionResult, TranscriptSegment


class FakeOllama(BaseHTTPRequestHandler):
    models = ["llama3.2:latest", "qwen2.5:7b"]
    prompts: list[str] = []

    def log_message(self, *_args):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"models": [{"name": name} for name in self.models]})

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = request["messages"][0]["content"]
        FakeOllama.prompts.append(prompt)
        self._send({"message": {"content": f"## Resumen\nRespuesta de {request['model']}."}})


@pytest.fixture
def ollama(monkeypatch):
    FakeOllama.prompts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, "ollama_url", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(settings, "ollama_model", None)
    yield FakeOllama
    server.shutdown()


def make_result(segments):
    return TranscriptionResult(
        segments=segments, language="es", language_probability=0.9, duration=100,
        text=" ".join(s.text for s in segments), model_size="small", device="cpu",
        compute_type="int8", batch_size=1, profile="balanced",
    )


def test_unavailable_when_ollama_is_not_running(monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://127.0.0.1:9")
    assert summarizer.status().available is False
    monkeypatch.setattr(settings, "ollama_url", None)
    assert summarizer.status().available is False


def test_status_prefers_the_configured_model(ollama, monkeypatch):
    assert summarizer.status().model == "llama3.2:latest"
    monkeypatch.setattr(settings, "ollama_model", "qwen2.5:7b")
    assert summarizer.status().model == "qwen2.5:7b"


def test_short_transcript_is_summarised_in_one_request(ollama):
    result = make_result([
        TranscriptSegment(0, 2, "Hola.", speaker="Ana"),
        TranscriptSegment(65, 70, "Hablemos de presupuestos.", speaker="Luis"),
    ])
    markdown = summarizer.summarize(result, "Reunión")
    assert markdown.startswith("# Resumen de Reunión")
    assert "llama3.2:latest" in markdown and "## Resumen" in markdown
    assert len(ollama.prompts) == 1
    assert "[01:05] Luis: Hablemos de presupuestos." in ollama.prompts[0]
    assert "## Capítulos" in ollama.prompts[0] and "español" in ollama.prompts[0]


def test_long_transcripts_are_summarised_in_parts(ollama, monkeypatch):
    monkeypatch.setattr(summarizer, "CHUNK_CHARS", 60)
    segments = [TranscriptSegment(i * 10, i * 10 + 2, f"Tema número {i} con detalle.")
                for i in range(6)]
    summarizer.summarize(make_result(segments), "Charla")
    assert len(ollama.prompts) > 2
    assert "parte 1 de" in ollama.prompts[0]
    assert "Notas de cada parte" in ollama.prompts[-1]


def test_chunks_never_exceed_the_limit_even_for_one_long_line():
    parts = summarizer.chunks(["a" * 250, "b" * 10], size=100)
    assert all(len(part) <= 100 for part in parts)
    assert "".join(parts).replace("\n", "") == "a" * 250 + "b" * 10


def test_api_saves_and_returns_the_summary(ollama, tmp_path, monkeypatch):
    store = HistoryStore(tmp_path / "h.json", 10, tmp_path / "out")
    monkeypatch.setattr(settings, "output_dir", store._output_dir)
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(routes, "history_store", store)
    monkeypatch.setattr(routes, "job_manager", JobManager())
    write_all(make_result([TranscriptSegment(0, 2, "Hola.")]), store._output_dir / "job_s",
              source="s", title="Vídeo", created_at="c", audio_quality="best")
    store.add_entry(HistoryItem("job_s", "url", "s", "Vídeo", "c", 2, 1, "es"))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/summary/status").json() == {
            "available": True, "model": "llama3.2:latest"}
        assert client.get("/api/jobs/job_s/result").json()["summary"] is None
        created = client.post("/api/jobs/job_s/summary")
        assert created.status_code == 200
        assert created.json()["markdown"].startswith("# Resumen de Vídeo")
        assert client.get("/api/jobs/job_s/result").json()["summary"] == created.json()["markdown"]
        assert client.get("/api/jobs/job_s/download/summary").status_code == 200
        monkeypatch.setattr(settings, "ollama_url", "http://127.0.0.1:9")
        down = client.post("/api/jobs/job_s/summary")
        assert down.status_code == 503 and down.json()["detail"]["code"] == "summary_failed"
