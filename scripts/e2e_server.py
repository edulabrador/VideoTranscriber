"""The real API for browser tests, with Whisper, diarization and Ollama simulated.

Downloads, FFmpeg, history, exports, the audio copy and every endpoint are real;
only the model work is replaced so the test runs in seconds and needs no models.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import uvicorn
from faster_whisper import decode_audio

from backend.config import settings
from backend.core import diarizer, transcriber
from backend.core.diarizer import SpeakerTurn


class FakeWhisper:
    def transcribe(self, path, **_options):
        duration = len(decode_audio(path, sampling_rate=16000)) / 16000

        def segments():
            for index in range(int(duration // 5)):
                yield SimpleNamespace(
                    start=index * 5.0, end=index * 5.0 + 4.5,
                    text=f"Frase número {index + 1} sobre el presupuesto.", words=None,
                )

        return segments(), SimpleNamespace(language="es", language_probability=0.95, duration=duration)


def fake_diarize(_path, num_speakers, _cancel, on_progress=None):
    if on_progress:
        on_progress(100)
    speakers = num_speakers or 2
    return [SpeakerTurn(start, start + 10, (start // 10) % speakers) for start in range(0, 600, 10)]


class FakeOllama(BaseHTTPRequestHandler):
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
        self._send({"models": [{"name": "modelo-de-prueba"}]})

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self._send({"message": {"content": "## Resumen\nUna reunión sobre el presupuesto."}})


ollama = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=ollama.serve_forever, daemon=True).start()
settings.ollama_url = f"http://127.0.0.1:{ollama.server_port}"
transcriber.get_model = lambda *_: FakeWhisper()
transcriber.is_model_cached = lambda *_: True
diarizer.diarize = fake_diarize
diarizer.models_ready = lambda: True
uvicorn.run("backend.api.app:app", host="127.0.0.1", port=8187, log_level="warning")
