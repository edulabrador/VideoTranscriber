import shutil
import threading
import time
import logging
from collections import deque
from math import ceil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.core import downloader, validators
from backend.core.audio import normalize_to_wav16k_mono
from backend.core.downloader import AudioQuality
from backend.core.errors import JobCancelledError, TranscriberError
from backend.core.exporter import write_all
from backend.core.history import HistoryItem, history_store
from backend.core.job_manager import JobStatus
from backend.core.model_manager import model_cache
from backend.core.transcriber import (
    TranscriptionOptions,
    TranscriptionProfile,
    TranscriptionResult,
    transcribe_audio,
)

StageCallback = Callable[[JobStatus, str, int | None], None]
logger = logging.getLogger(__name__)


class TranscriptionTurns:
    """First-come, first-served access to the single transcription slot."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._waiting: deque[object] = deque()
        self._running = False

    def acquire(
        self, cancel_event: threading.Event, on_position: Callable[[int], None],
    ) -> None:
        ticket = object()
        with self._condition:
            self._waiting.append(ticket)
        last_position = None
        try:
            while True:
                with self._condition:
                    if self._waiting[0] is ticket and not self._running:
                        self._waiting.popleft()
                        self._running = True
                        return
                    # Jobs ahead of this one, counting the one being transcribed.
                    position = self._waiting.index(ticket) + int(self._running)
                if position != last_position:
                    on_position(position)
                    last_position = position
                if cancel_event.is_set():
                    raise JobCancelledError()
                with self._condition:
                    self._condition.wait(0.25)
        except BaseException:
            with self._condition:
                if ticket in self._waiting:
                    self._waiting.remove(ticket)
                self._condition.notify_all()
            raise

    def try_acquire_idle(self) -> bool:
        with self._condition:
            if self._running or self._waiting:
                return False
            self._running = True
            return True

    def release(self) -> None:
        with self._condition:
            self._running = False
            self._condition.notify_all()


_TURNS = TranscriptionTurns()


def release_idle_models() -> bool:
    """Free cached models after the configured idle time. True when memory was freed."""
    idle_limit = settings.model_idle_unload_seconds
    if not idle_limit or model_cache.idle_seconds() < idle_limit:
        return False
    if not _TURNS.try_acquire_idle():
        return False
    try:
        freed = model_cache.clear()
    finally:
        _TURNS.release()
    if freed:
        logger.info("Modelos liberados tras %.0f s sin uso", idle_limit)
    return freed


@dataclass
class URLSource:
    url: str


@dataclass
class FileSource:
    path: Path
    original_name: str


Source = URLSource | FileSource


def _noop_stage(_status: JobStatus, _message: str, _progress: int | None = None) -> None:
    pass


def run_pipeline(
    job_id: str,
    source: Source,
    *,
    cancel_event: threading.Event | None = None,
    on_stage: StageCallback = _noop_stage,
    output_dir: Path | None = None,
    profile: TranscriptionProfile = "balanced",
    audio_quality: AudioQuality = "balanced",
    options: TranscriptionOptions | None = None,
    record_history: bool = True,
) -> TranscriptionResult:
    options = options or TranscriptionOptions()
    cancel_event = cancel_event or threading.Event()
    output_dir = output_dir or (settings.output_dir / job_id)
    job_temp_dir = settings.temp_dir / job_id
    job_temp_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.perf_counter()
    timings: dict[str, float] = {}

    try:
        if cancel_event.is_set():
            raise JobCancelledError()
        if isinstance(source, URLSource):
            validators.validate_supported_url(source.url)

            on_stage("downloading", "Consultando el vídeo y las pistas de audio...", 1)

            def report_download(message: str, percent: int | None) -> None:
                overall = 1 if percent is None else 1 + round(percent * 0.19)
                on_stage("downloading", message, overall)

            download_result = downloader.download_media(
                source.url,
                job_temp_dir,
                settings.cookies_file,
                cancel_event,
                on_progress=report_download,
                cobalt_api_url=settings.cobalt_api_url,
                audio_quality=audio_quality,
            )
            timings["download"] = time.perf_counter() - started_at
            raw_audio_path = download_result.audio_path
            title = download_result.title
            source_label = source.url
            source_type = "url"
            transcription_start = 20
            audio_label = (
                f"Audio: {download_result.audio_language} (original)"
                if download_result.audio_selection == "original"
                else "Audio: pista por defecto, no identificada"
            )
        else:
            on_stage("extracting_audio", "Preparando el audio del archivo subido...", 0)
            raw_audio_path = normalize_to_wav16k_mono(
                source.path, job_temp_dir / "audio.wav", cancel_event,
                timeout=settings.audio_preparation_timeout_seconds,
            )
            timings["audio_preparation"] = time.perf_counter() - started_at
            title = source.original_name
            source_label = source.original_name
            source_type = "file"
            transcription_start = 0
            audio_label = "Audio: archivo subido"

        queue_started = time.perf_counter()
        on_stage("queued", f"En cola. Esperando turno de procesamiento. {audio_label}", transcription_start)

        def report_position(ahead: int) -> None:
            if ahead:
                waiting = "1 trabajo" if ahead == 1 else f"{ahead} trabajos"
                on_stage("queued", f"En cola: {waiting} por delante. {audio_label}", transcription_start)

        _TURNS.acquire(cancel_event, report_position)

        def report_transcription(percent: int, eta_seconds: int | None) -> None:
            overall = transcription_start + round(percent * (98 - transcription_start) / 100)
            if eta_seconds is None:
                remaining = "Calculando el tiempo restante."
            elif eta_seconds < 60:
                remaining = "Queda menos de 1 minuto."
            else:
                remaining = f"Quedan aproximadamente {ceil(eta_seconds / 60)} minutos."
            on_stage(
                "transcribing",
                f"Transcribiendo audio: {percent} %. {remaining} {audio_label}",
                overall,
            )

        try:
            timings["queue"] = time.perf_counter() - queue_started
            if cancel_event.is_set():
                raise JobCancelledError()
            result = transcribe_audio(
                raw_audio_path,
                settings.model_size,
                settings.device,
                settings.compute_type,
                cancel_event,
                settings.batch_size,
                settings.beam_size,
                profile,
                report_transcription,
                lambda status, message: on_stage(
                    status, f"{message} {audio_label}", transcription_start
                ),
                options=options,
            )
            if isinstance(source, URLSource):
                result.audio_language = download_result.audio_language
                result.audio_format_id = download_result.audio_format_id
                result.audio_selection = download_result.audio_selection
        finally:
            model_cache.touch()
            _TURNS.release()

        on_stage("exporting", "Preparando los archivos...", 99)
        result.timings.update(timings)
        created_at = datetime.now(timezone.utc).isoformat()
        result.timings["processing_total"] = time.perf_counter() - started_at
        write_all(
            result,
            output_dir,
            source=source_label,
            title=title,
            created_at=created_at,
            audio_quality=audio_quality,
        )

        if record_history:
            history_store.add_entry(
                HistoryItem(
                    id=job_id,
                    source_type=source_type,
                    source=source_label,
                    title=title,
                    created_at=created_at,
                    duration=result.duration,
                    word_count=result.word_count,
                    language=result.language,
                )
            )
        logger.info("Job %s timings (seconds): %s", job_id, result.timings)

        on_stage("completed", "Transcripción completada.", 100)
        return result
    except TranscriberError:
        raise
    except Exception as exc:  # noqa: BLE001 - single boundary that wraps any unexpected failure
        raise TranscriberError(f"Se produjo un error inesperado: {exc}") from exc
    finally:
        shutil.rmtree(job_temp_dir, ignore_errors=True)
