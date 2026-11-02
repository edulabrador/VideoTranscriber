import json
import logging
import re
import shutil
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from backend.config import settings
from backend.core.exporter import PROCESSING_VERSION, read_json, result_from_payload, write_all
from backend.core.fileio import atomic_write_text, interprocess_lock
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
# Folders renamed to this prefix are being deleted; a crash may leave one behind.
DELETING_PREFIX = ".deleting-"
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
    # Failed jobs only: the request that failed, so "Reintentar" repeats it exactly.
    retry: dict | None = None


class HistoryStore:
    def __init__(self, path: Path, max_entries: int, output_dir: Path, max_failed: int = 20):
        self._path = path
        self._max_entries = max_entries
        self._max_failed = max_failed
        self._output_dir = output_dir
        self._thread_lock = threading.Lock()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """Serialise access within this process and with the CLI in another process."""
        with self._thread_lock, interprocess_lock(self._path.with_name(self._path.name + ".lock")):
            yield

    def _read(self) -> list[dict]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        try:
            entries = json.loads(raw)
        except ValueError:
            return self._recover(raw)
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict) and isinstance(entry.get("id"), str) for entry in entries
        ):
            return self._recover(raw)
        return entries

    def _recover(self, raw: str) -> list[dict]:
        """Keep the damaged file aside and rebuild the history from the saved transcripts.

        Writing an empty list over it would make every transcript look orphaned and
        lose it for good at the next clean-up.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        backup = self._path.with_name(f"{self._path.stem}.corrupt-{stamp}{self._path.suffix}")
        if raw.strip():
            atomic_write_text(backup, raw)
        entries = self._rebuild_from_outputs()
        self._write(entries)
        logger.warning(
            "El historial estaba dañado. Se guardó una copia en %s y se reconstruyeron "
            "%d entradas a partir de las transcripciones guardadas.",
            backup.name, len(entries),
        )
        return entries

    def _rebuild_from_outputs(self) -> list[dict]:
        entries: list[dict] = []
        if not self._output_dir.is_dir():
            return entries
        for path in self._output_dir.iterdir():
            if (
                not path.is_dir() or path.is_symlink() or not _JOB_ID.fullmatch(path.name)
                or (path / KEPT_MARKER).exists()
            ):
                continue
            try:
                payload = json.loads((path / "transcript.json").read_text(encoding="utf-8"))
                source = str(payload.get("source", ""))
                entries.append(asdict(HistoryItem(
                    id=path.name,
                    source_type="url" if source.startswith(("http://", "https://")) else "file",
                    source=source,
                    title=str(payload.get("title") or source or path.name),
                    created_at=str(payload.get("created_at", "")),
                    duration=float(payload.get("duration", 0)),
                    word_count=int(payload.get("word_count", 0)),
                    language=str(payload.get("language", "")),
                )))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        entries.sort(key=lambda entry: entry["created_at"], reverse=True)
        return entries[: self._max_entries]

    def _write(self, entries: list[dict]) -> None:
        atomic_write_text(self._path, json.dumps(entries, indent=2, ensure_ascii=False))

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
        with self._lock():
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
        source_key = _source_key(item.source)
        with self._lock():
            entries = [entry for entry in self._read() if entry.get("id") != item.id]
            if item.status == "completed":
                # A success supersedes earlier failures of the same source.
                entries = [
                    entry for entry in entries
                    if entry.get("status", "completed") == "completed"
                    or _source_key(entry.get("source", "")) != source_key
                ]
            entries.insert(0, asdict(item))
            kept: list[dict] = []
            dropped: list[dict] = []
            completed = failed = 0
            for entry in entries:
                if entry.get("status", "completed") == "completed":
                    completed += 1
                    (kept if completed <= self._max_entries else dropped).append(entry)
                else:
                    failed += 1
                    if failed <= self._max_failed:
                        kept.append(entry)
            self._write(kept)
        # Transcripts pushed out of the history can no longer be opened; free their files.
        for entry in dropped:
            self._remove_files(str(entry.get("id", "")))

    def orphan_outputs(self) -> list[Path]:
        """Output folders no history entry references and nobody chose to keep."""
        with self._lock():
            known = {entry.get("id") for entry in self._read()}
        if not self._output_dir.exists():
            return []
        return sorted(
            path for path in self._output_dir.iterdir()
            if path.is_dir() and not path.is_symlink() and _JOB_ID.fullmatch(path.name)
            and path.name not in known and not (path / KEPT_MARKER).exists()
        )

    def list_entries(self, query: str = "") -> list[dict]:
        with self._lock():
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
        with self._lock():
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

    def update_transcript(
        self,
        item_id: str,
        segment_texts: dict[int, str] | None = None,
        speaker_names: dict[str, str] | None = None,
    ) -> TranscriptionResult | None:
        """Apply hand corrections and rewrite every export. None if the item is unknown."""
        with self._lock():
            entries = self._read()
            entry = next(
                (e for e in entries if e.get("id") == item_id
                 and e.get("status", "completed") == "completed"),
                None,
            )
            path = self._job_dir(item_id)
            if entry is None or path is None:
                return None
            payload = json.loads((path / "transcript.json").read_text(encoding="utf-8"))
            result = result_from_payload(payload)
            for index, text in (segment_texts or {}).items():
                if not 0 <= index < len(result.segments):
                    raise ValueError(f"No existe el fragmento {index}")
                result.segments[index].text = text.strip()
                result.segments[index].words = []  # Old word timings no longer match.
            for segment in result.segments:
                if segment.speaker and segment.speaker in (speaker_names or {}):
                    segment.speaker = (speaker_names or {})[segment.speaker].strip()
            result.text = " ".join(s.text for s in result.segments if s.text).strip()
            result.edited = True
            write_all(
                result,
                path,
                source=payload.get("source", entry.get("source", "")),
                title=payload.get("title", entry.get("title", "")),
                created_at=payload.get("created_at", entry.get("created_at", "")),
                audio_quality=payload.get("audio_quality", "best"),
            )
            entry["word_count"] = result.word_count
            self._write(entries)
            return result

    def delete_entry(self, item_id: str, delete_files: bool = False) -> bool:
        """Remove an entry, and optionally its files, all or nothing.

        The folder is first renamed out of the way. If any file is in use (Windows
        refuses the rename then) nothing changes and OSError is raised, instead of
        leaving an entry that points at a half-deleted folder.
        """
        trash: Path | None = None
        with self._lock():
            entries = self._read()
            filtered = [e for e in entries if e.get("id") != item_id]
            if len(filtered) == len(entries):
                return False
            path = self._job_dir(item_id)
            if delete_files:
                if path is None:
                    return False
                if path.exists():
                    trash = path.with_name(f"{DELETING_PREFIX}{item_id}-{uuid.uuid4().hex[:8]}")
                    path.rename(trash)
            elif path is not None and path.is_dir():
                (path / KEPT_MARKER).touch()
            try:
                self._write(filtered)
            except BaseException:
                if trash is not None and path is not None:
                    trash.rename(path)
                raise
        if trash is not None:
            shutil.rmtree(trash, ignore_errors=True)
        return True

    def remove_interrupted_deletions(self) -> int:
        """Finish deleting folders a previous run renamed but could not remove."""
        if not self._output_dir.is_dir():
            return 0
        removed = 0
        for path in self._output_dir.iterdir():
            if path.name.startswith(DELETING_PREFIX) and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        return removed


history_store = HistoryStore(
    settings.history_file,
    settings.max_history_entries,
    settings.output_dir,
    settings.max_failed_entries,
)
