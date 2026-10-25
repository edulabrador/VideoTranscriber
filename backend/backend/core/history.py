import json
import logging
import re
import shutil
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from backend.config import settings
from backend.core.exporter import PROCESSING_VERSION, read_json, result_from_payload
from backend.core.model_manager import select_device
from backend.core.transcriber import (
    TranscriptionOptions,
    TranscriptionProfile,
    TranscriptionResult,
    resolve_job_model,
)

_QUALITY_RANK = {"compact": 0, "balanced": 1, "best": 2}
# Marks a folder whose history entry was deleted on purpose while keeping its files.
KEPT_MARKER = ".kept"
_JOB_ID = re.compile(r"job_[A-Za-z0-9_-]{1,64}")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_KNOWN_PATH_HOSTS = {"instagram.com", "tiktok.com", "x.com", "twitter.com"}
_TRACKING_PARAMS = re.compile(r"^(?:utm_.*|si|s|t|igsh|igshid|feature|ref|ref_src|fbclid|gclid)$")
logger = logging.getLogger(__name__)


def _bare_host(host: str) -> str:
    host = host.lower()
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix):
            return host[len(prefix):]
    return host


def _source_key(source: str) -> str:
    parsed = urlsplit(source.strip())
    if parsed.scheme not in {"http", "https"}:
        return source.strip()
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    if host in _YOUTUBE_HOSTS:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if video_id:
            return f"youtube:{video_id}"
        parts = path.strip("/").split("/")
        if len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
            return f"youtube:{parts[1]}"
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = path.strip("/").split("/", 1)[0]
        if video_id:
            return f"youtube:{video_id}"
    bare = _bare_host(host)
    if bare == "twitter.com":
        bare = "x.com"
    if bare == "instagram.com":
        # /reel/, /reels/, /p/ and /tv/ address the same post by its shortcode.
        match = re.match(r"^/(?:reels?|p|tv)/([A-Za-z0-9_-]+)", path)
        if match:
            return f"instagram:{match.group(1)}"
    if bare == "x.com":
        match = re.match(r"^/[^/]+/status/(\d+)", path)
        if match:
            return f"x:{match.group(1)}"
    if bare == "tiktok.com":
        match = re.match(r"^/@[^/]+/video/(\d+)", path)
        if match:
            return f"tiktok:{match.group(1)}"
    if bare in _KNOWN_PATH_HOSTS:
        return f"{bare}{path}"
    # Other sites may identify the video in the query string, so keep it minus tracking.
    query = sorted(
        (key, value)
        for key, values in parse_qs(parsed.query).items()
        if not _TRACKING_PARAMS.match(key)
        for value in values
    )
    suffix = f"?{urlencode(query)}" if query else ""
    return f"{bare}{path}{suffix}"


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
    status: str = "completed"  # "completed" | "failed"
    error: str | None = None


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
        if not _JOB_ID.fullmatch(item_id):
            return None
        path = self._output_dir / item_id
        if path.is_symlink() or path.resolve().parent != self._output_dir.resolve():
            return None
        return path

    def _remove_files(self, item_id: str) -> None:
        path = self._job_dir(item_id)
        if path is not None and path.exists():
            shutil.rmtree(path, ignore_errors=True)

    def load_result(self, item_id: str) -> TranscriptionResult | None:
        with self._lock:
            if not any(
                entry.get("id") == item_id and entry.get("status", "completed") == "completed"
                for entry in self._read()
            ):
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
            entries = [entry for entry in self._read() if entry.get("id") != item.id]
            entries.insert(0, asdict(item))
            kept, dropped = entries[: self._max_entries], entries[self._max_entries:]
            self._write(kept)
        # Entries pushed out of the history can no longer be opened; free their files.
        for entry in dropped:
            self._remove_files(str(entry.get("id", "")))

    def orphan_outputs(self) -> list[Path]:
        """Output folders no history entry references and nobody chose to keep."""
        with self._lock:
            known = {entry.get("id") for entry in self._read()}
        if not self._output_dir.exists():
            return []
        return sorted(
            path for path in self._output_dir.iterdir()
            if path.is_dir() and not path.is_symlink() and _JOB_ID.fullmatch(path.name)
            and path.name not in known and not (path / KEPT_MARKER).exists()
        )

    def list_entries(self, query: str = "") -> list[dict]:
        with self._lock:
            entries = self._read()
            matches: list[dict] = []
            previews = 0
            query = query.strip().casefold()
            for entry in entries:
                path = self._job_dir(entry["id"])
                if path is None:
                    continue
                entry.setdefault("status", "completed")
                text = ""
                try:
                    if entry["status"] == "completed" and (query or previews < 2):
                        with (path / "transcript.txt").open(encoding="utf-8") as transcript:
                            text = transcript.read() if query else transcript.read(240)
                except OSError:
                    pass
                searchable = " ".join(
                    (entry.get("title", ""), entry.get("source", ""), entry.get("error") or "", text)
                )
                if query and query not in searchable.casefold():
                    continue
                if text and previews < 2:
                    entry["text"] = text[:240]
                    previews += 1
                matches.append(entry)
            return matches

    def find_cached(
        self,
        source: str,
        profile: TranscriptionProfile,
        audio_quality: str,
        options: TranscriptionOptions | None = None,
    ) -> tuple[str, TranscriptionResult] | None:
        options = options or TranscriptionOptions()
        source_key = _source_key(source)
        device = select_device(settings.device)
        model, beam_size = resolve_job_model(
            profile, options, settings.model_size, settings.beam_size, device,
        )
        with self._lock:
            entries = self._read()

        for entry in entries:
            if entry.get("status", "completed") != "completed":
                continue
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
                cached_options = {
                    key: payload.get(key, default)
                    for key, default in TranscriptionOptions().cache_fields().items()
                }
                compatible = (
                    payload.get("processing_version") == PROCESSING_VERSION
                    and payload.get("model_size") == model
                    and payload.get("beam_size") == beam_size
                    and cached_options == options.cache_fields()
                )
                if compatible and cached_profile == profile and quality_is_sufficient:
                    return entry["id"], result_from_payload(payload)
            except (KeyError, TypeError, OSError, ValueError):
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
            else:
                path = self._job_dir(item_id)
                if path is not None and path.is_dir():
                    (path / KEPT_MARKER).touch()
            self._write(filtered)
            return True


history_store = HistoryStore(
    settings.history_file,
    settings.max_history_entries,
    settings.output_dir,
)
