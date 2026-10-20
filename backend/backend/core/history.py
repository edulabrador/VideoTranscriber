import json
import re
import shutil
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from backend.config import settings
from backend.core.exporter import PROCESSING_VERSION, read_json
from backend.core.model_manager import resolve_model_size, select_device_and_compute_type
from backend.core.transcriber import (
    TranscriptionProfile, TranscriptionResult, resolve_profile_settings,
)

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
        temporary = self._path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._path)
        finally:
            temporary.unlink(missing_ok=True)

    def _job_dir(self, item_id: str) -> Path | None:
        if not re.fullmatch(r"job_[A-Za-z0-9_-]{1,64}", item_id):
            return None
        path = self._output_dir / item_id
        if path.is_symlink() or path.resolve().parent != self._output_dir.resolve():
            return None
        return path

    def load_result(self, item_id: str) -> TranscriptionResult | None:
        with self._lock:
            if not any(entry.get("id") == item_id for entry in self._read()):
                return None
            path = self._job_dir(item_id)
            if path is None:
                return None
            try:
                return read_json(path / "transcript.json")
            except (KeyError, TypeError, ValueError, OSError):
                return None

    def add_entry(self, item: HistoryItem) -> None:
        with self._lock:
            entries = self._read()
            entries.insert(0, asdict(item))
            entries = entries[: self._max_entries]
            self._write(entries)

    def list_entries(self, query: str = "") -> list[dict]:
        with self._lock:
            entries = self._read()
            matches: list[dict] = []
            query = query.strip().casefold()
            for entry in entries:
                path = self._job_dir(entry["id"])
                if path is None:
                    continue
                text = ""
                try:
                    if query or len(matches) < 2:
                        text = (path / "transcript.txt").read_text(encoding="utf-8")
                except OSError:
                    pass
                searchable = " ".join((entry.get("title", ""), entry.get("source", ""), text))
                if query and query not in searchable.casefold():
                    continue
                if text and len(matches) < 2:
                    entry["text"] = text
                matches.append(entry)
            return matches

    def find_cached(
        self,
        source: str,
        profile: TranscriptionProfile,
        audio_quality: str,
    ) -> tuple[str, TranscriptionResult] | None:
        source_key = _source_key(source)
        model, beam_size = resolve_profile_settings(profile, settings.model_size, settings.beam_size)
        device, _ = select_device_and_compute_type(settings.device)
        model = resolve_model_size(model, device)
        with self._lock:
            entries = self._read()

        for entry in entries:
            if _source_key(entry.get("source", "")) != source_key:
                continue
            job_dir = self._job_dir(entry["id"])
            if job_dir is None:
                continue
            transcript_path = job_dir / "transcript.json"
            try:
                payload = json.loads(transcript_path.read_text(encoding="utf-8"))
                cached_profile = payload.get("profile", "balanced")
                cached_quality = payload.get("audio_quality", "best")
                quality_is_sufficient = _QUALITY_RANK.get(cached_quality, 0) >= _QUALITY_RANK[
                    audio_quality
                ]
                compatible = (
                    payload.get("processing_version") == PROCESSING_VERSION
                    and payload.get("model_size") == model
                    and payload.get("beam_size") == beam_size
                )
                if compatible and cached_profile == profile and quality_is_sufficient:
                    return entry["id"], read_json(transcript_path)
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                continue
        return None

    def delete_entry(self, item_id: str, delete_files: bool = False) -> bool:
        with self._lock:
            entries = self._read()
            filtered = [e for e in entries if e["id"] != item_id]
            if len(filtered) == len(entries):
                return False
            if delete_files:
                path = self._job_dir(item_id)
                if path is None:
                    return False
                if path.exists():
                    shutil.rmtree(path)
            self._write(filtered)
            return True


history_store = HistoryStore(
    settings.history_file,
    settings.max_history_entries,
    settings.output_dir,
)
