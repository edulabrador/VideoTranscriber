import shutil
import threading
from math import ceil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.core import downloader, validators
from backend.core.downloader import AudioQuality
from backend.core.errors import JobCancelledError, TranscriberError
from backend.core.exporter import write_json, write_srt, write_txt
from backend.core.history import HistoryItem, history_store
from backend.core.job_manager import JobStatus
from backend.core.transcriber import TranscriptionProfile, TranscriptionResult, transcribe_audio

StageCallback = Callable[[JobStatus, str, int | None], None]
_TRANSCRIPTION_LOCK = threading.Lock()


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
) -> TranscriptionResult:
    cancel_event = cancel_event or threading.Event()
    output_dir = output_dir or (settings.output_dir / job_id)
    job_temp_dir = settings.temp_dir / job_id
    job_temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        if isinstance(source, URLSource):
            validators.validate_instagram_url(source.url)

            on_stage("downloading", "Preparando la descarga...", 1)

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
            raw_audio_path = download_result.audio_path
            title = download_result.title
            source_label = source.url
            source_type = "url"
            transcription_start = 20
        else:
            raw_audio_path = source.path
            title = source.original_name
            source_label = source.original_name
            source_type = "file"
            transcription_start = 0

        on_stage("transcribing", "Esperando turno de procesamiento...", transcription_start)
        while not _TRANSCRIPTION_LOCK.acquire(timeout=0.25):
            if cancel_event.is_set():
                raise JobCancelledError()

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
                f"Transcribiendo audio: {percent} %. {remaining}",
                overall,
            )

        try:
            if cancel_event.is_set():
                raise JobCancelledError()
            on_stage(
                "transcribing",
                "Analizando el audio para calcular el progreso...",
                transcription_start,
            )
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
            )
        finally:
            _TRANSCRIPTION_LOCK.release()

        on_stage("exporting", "Preparando los archivos...", 99)
        created_at = datetime.now(timezone.utc).isoformat()
        write_txt(result, output_dir / "transcript.txt")
        write_srt(result, output_dir / "subtitles.srt")
        write_json(
            result,
            output_dir / "transcript.json",
            source=source_label,
            title=title,
            created_at=created_at,
            audio_quality=audio_quality,
        )

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

        on_stage("completed", "Transcripción completada.", 100)
        return result
    except TranscriberError:
        raise
    except Exception as exc:  # noqa: BLE001 - single boundary that wraps any unexpected failure
        raise TranscriberError(f"Se produjo un error inesperado: {exc}") from exc
    finally:
        shutil.rmtree(job_temp_dir, ignore_errors=True)
