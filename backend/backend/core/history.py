import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from backend.config import settings
from backend.core.exporter import read_json
from backend.core.transcriber import TranscriptionProfile, TranscriptionResult

_QUALITY_RANK = {"compact": 0, "balanced": 1, "best": 2}


def _source_key(source: str) -> str:
    parsed = urlsplit(source.strip())
    if parsed.scheme not in {"http", "https"}:
        return source.strip()
    host = (parsed.hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if video_id:
            return f"youtube:{video_id}"
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/", 1)[0]
        if video_id:
            return f"youtube:{video_id}"
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
            return f"youtube:{parts[1]}"
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


@dataclass
class HistoryItem:
    id: str
    source_type: str  # "url" | "file"
    source: str
    title: str
    created_at: str
    duration: float
    word_count: int
    language: str


class HistoryStore:
    def __init__(self, path: Path, max_entries: int, output_dir: Path):
        self._path = path
        self._max_entries = max_entries
        self._output_dir = output_dir
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _write(self, entries: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_entry(self, item: HistoryItem) -> None:
        with self._lock:
            entries = self._read()
            entries.insert(0, asdict(item))
            entries = entries[: self._max_entries]
            self._write(entries)

    def list_entries(self) -> list[dict]:
        with self._lock:
            entries = self._read()
            for entry in entries[:2]:
                transcript_path = self._output_dir / entry["id"] / "transcript.txt"
                try:
                    entry["text"] = transcript_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            return entries

    def find_cached(
        self,
        source: str,
        profile: TranscriptionProfile,
        audio_quality: str,
    ) -> tuple[str, TranscriptionResult] | None:
        source_key = _source_key(source)
        with self._lock:
            entries = self._read()

        for entry in entries:
            if _source_key(entry.get("source", "")) != source_key:
                continue
            transcript_path = self._output_dir / entry["id"] / "transcript.json"
            try:
                payload = json.loads(transcript_path.read_text(encoding="utf-8"))
                cached_profile = payload.get("profile", "balanced")
                cached_quality = payload.get("audio_quality", "best")
                quality_is_sufficient = _QUALITY_RANK.get(cached_quality, 0) >= _QUALITY_RANK[
                    audio_quality
                ]
                if cached_profile == profile and quality_is_sufficient:
                    return entry["id"], read_json(transcript_path)
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                continue
        return None

    def delete_entry(self, item_id: str) -> bool:
        with self._lock:
            entries = self._read()
            filtered = [e for e in entries if e["id"] != item_id]
            if len(filtered) == len(entries):
                return False
            self._write(filtered)
            return True


history_store = HistoryStore(
    settings.history_file,
    settings.max_history_entries,
    settings.output_dir,
)
