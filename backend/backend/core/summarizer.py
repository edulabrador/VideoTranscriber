"""Optional summaries with a local Ollama server. Nothing leaves the computer.

The feature appears only when Ollama answers at OLLAMA_URL. Long transcripts are
summarised in parts first, then the partial notes are combined.
"""
import json
import logging
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

from backend.config import settings
from backend.core.errors import TranscriberError
from backend.core.exporter import paragraphs
from backend.core.transcriber import TranscriptionResult

logger = logging.getLogger(__name__)
# Characters per request. About 3 000 tokens, which fits the default context of
# common local models with room for the instructions and the answer.
CHUNK_CHARS = 12000
SUMMARY_FILE = "summary.md"


class SummaryError(TranscriberError):
    code = "summary_failed"


@dataclass
class OllamaStatus:
    available: bool
    model: str | None = None
    models: tuple[str, ...] = ()


def _post(path: str, payload: dict, timeout: float) -> dict:
    request = Request(
        f"{(settings.ollama_url or '').rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def status() -> OllamaStatus:
    if not settings.ollama_url:
        return OllamaStatus(False)
    try:
        with urlopen(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError):
        return OllamaStatus(False)
    models = tuple(
        str(item["name"]) for item in data.get("models", []) if isinstance(item, dict) and item.get("name")
    )
    if not models:
        return OllamaStatus(False)
    chosen = settings.ollama_model if settings.ollama_model in models else models[0]
    return OllamaStatus(True, chosen, models)


def _clock(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def transcript_lines(result: TranscriptionResult) -> list[str]:
    lines = []
    for paragraph in paragraphs(result.segments):
        speaker = f"{paragraph.speaker}: " if paragraph.speaker else ""
        lines.append(f"[{_clock(paragraph.start)}] {speaker}{paragraph.text}")
    return lines or [result.text]


def chunks(lines: list[str], size: int | None = None) -> list[str]:
    size = size or CHUNK_CHARS
    parts: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        while len(line) > size:  # A single huge paragraph is split by characters.
            if current:
                parts.append("\n".join(current))
                current, length = [], 0
            parts.append(line[:size])
            line = line[size:]
        if current and length + len(line) > size:
            parts.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts


def _ask(model: str, prompt: str) -> str:
    try:
        reply = _post(
            "/api/chat",
            {
                "model": model,
                "stream": False,
                "options": {"temperature": 0.2},
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=settings.ollama_timeout_seconds,
        )
    except (OSError, URLError, ValueError) as exc:
        raise SummaryError(f"Ollama no respondió: {exc}") from exc
    content = (reply.get("message") or {}).get("content", "").strip()
    if not content:
        raise SummaryError("Ollama devolvió una respuesta vacía")
    return content


def summarize(result: TranscriptionResult, title: str) -> str:
    """Markdown with a short summary, key points and timestamped chapters."""
    current = status()
    if not current.available or current.model is None:
        raise SummaryError(
            "Ollama no está disponible. Instálalo, descarga un modelo (por ejemplo "
            "'ollama pull llama3.2') y vuelve a intentarlo."
        )
    language = settings.summary_language
    parts = chunks(transcript_lines(result))
    if len(parts) > 1:
        notes = [
            _ask(current.model, (
                f"Esta es la parte {index} de {len(parts)} de la transcripción de «{title}». "
                f"Escribe en {language} notas breves con las ideas principales y conserva "
                f"las marcas de tiempo [mm:ss] de cada tema.\n\n{part}"
            ))
            for index, part in enumerate(parts, start=1)
        ]
        material = "\n\n".join(notes)
        source = "Notas de cada parte de la transcripción"
    else:
        material = parts[0]
        source = "Transcripción"
    answer = _ask(current.model, (
        f"{source} de «{title}». Las marcas [mm:ss] indican el momento de cada parte.\n\n"
        f"{material}\n\n"
        f"Escribe en {language}, solo con información del texto, usando exactamente este "
        "formato Markdown:\n"
        "## Resumen\n(3 a 5 frases)\n\n"
        "## Puntos clave\n(de 3 a 8 viñetas)\n\n"
        "## Capítulos\n(una viñeta por tema: - [mm:ss] Título breve)"
    ))
    return f"# Resumen de {title}\n\n_Generado con {current.model} mediante Ollama._\n\n{answer}\n"
