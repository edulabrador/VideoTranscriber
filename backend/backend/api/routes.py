import json
import logging
import shutil
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import PureWindowsPath
from typing import Annotated, Literal

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from backend.api.schemas import (
    CreateJobFromUrlRequest,
    HealthResponse,
    HistoryItemSchema,
    JobErrorPayload,
    JobResponse,
    JobStatusResponse,
    SummaryStatusResponse,
    SummaryTaskResponse,
    TranscriptEditRequest,
    TranscriptionOptionsSchema,
    TranscriptResultSchema,
    TranscriptSegmentSchema,
    TranscriptWordSchema,
)
from backend.config import settings
from backend.core.audio import check_ffmpeg_available
from backend.core.downloader import AudioQuality
from backend.core.errors import JobCancelledError, TranscriberError, UnsupportedURLError
from backend.core.fileio import atomic_write_text
from backend.core.history import HistoryItem, _source_key, history_store
from backend.core.job_manager import JobRecord, JobStatus, job_manager
from backend.core.model_manager import (
    get_gpu_memory_mb,
    model_cache,
    resolve_batch_size,
    resolve_compute_type,
    select_device,
)
from backend.core import summarizer
from backend.core.pipeline import LISTENING_COPY, FileSource, Source, URLSource, run_pipeline
from backend.core.transcriber import (
    TranscriptionOptions,
    TranscriptionProfile,
    TranscriptionResult,
)
from backend.core.summarizer import SUMMARY_FILE
from backend.core.validators import validate_supported_url

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

_ALLOWED_EXPORT_FORMATS = {
    "txt": "transcript.txt",
    "srt": "subtitles.srt",
    "vtt": "subtitles.vtt",
    "md": "transcript.md",
    "json": "transcript.json",
    "summary": SUMMARY_FILE,
}
# Browsers often send these as application/octet-stream or with no type at all.
# FFmpeg makes the real decision when it prepares the audio.
_MEDIA_EXTENSIONS = {
    ".aac", ".aiff", ".amr", ".avi", ".flac", ".flv", ".m4a", ".m4v", ".mka", ".mkv",
    ".mov", ".mp3", ".mp4", ".mpeg", ".mpg", ".oga", ".ogg", ".opus", ".ts", ".wav",
    ".weba", ".webm", ".wma", ".wmv", ".3gp",
}
_TERMINAL = {"completed", "failed", "cancelled"}
# Jobs get their own threads. Each one holds a thread while it waits in the queue,
# so sharing asyncio's default pool (cpu_count + 4 threads) let a long queue block
# every other to_thread call: editing, summaries, freeing idle models.
_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=64, thread_name_prefix="transcription-job")


def _log_unexpected(future: Future) -> None:
    if not future.cancelled() and (error := future.exception()) is not None:
        logger.error("Un trabajo terminó con un error inesperado", exc_info=error)


def _start_background(job_id: str, source: Source, profile: TranscriptionProfile,
                      audio_quality: AudioQuality, options: TranscriptionOptions,
                      replaces: str | None = None) -> None:
    future = _JOB_EXECUTOR.submit(
        _run_job, job_id, source, profile, audio_quality, options, replaces,
    )
    future.add_done_callback(_log_unexpected)


def shutdown() -> None:
    """Stop running work quickly when the server closes."""
    job_manager.cancel_all()
    with _SUMMARY_LOCK:
        for task in _SUMMARY_TASKS.values():
            task.cancel_event.set()
    # The executors stay usable: the worker threads see the cancellation and end
    # on their own, and Python joins them at exit.


def _retry_request(
    source: Source, profile: TranscriptionProfile, audio_quality: AudioQuality,
    options: TranscriptionOptions | None,
) -> dict | None:
    """What "Reintentar" must send to repeat a failed link with the same settings."""
    if not isinstance(source, URLSource):
        return None
    return {"profile": profile, "audio_quality": audio_quality,
            **asdict(options or TranscriptionOptions())}


def _record_failure(
    job_id: str, source: Source, message: str, retry: dict | None = None,
) -> None:
    label = source.url if isinstance(source, URLSource) else source.original_name
    history_store.add_entry(
        HistoryItem(
            id=job_id,
            source_type="url" if isinstance(source, URLSource) else "file",
            source=label,
            title=label,
            created_at=datetime.now(timezone.utc).isoformat(),
            duration=0,
            word_count=0,
            language="",
            status="failed",
            error=message,
            retry=retry,
        )
    )


def _run_job(
    job_id: str,
    source: Source,
    profile: TranscriptionProfile,
    audio_quality: AudioQuality = "balanced",
    options: TranscriptionOptions | None = None,
    replaces: str | None = None,
) -> None:
    job = job_manager.get_job(job_id)
    if job is None:
        return

    def on_stage(status: JobStatus, message: str, progress: int | None = None) -> None:
        job_manager.update_status(job_id, status, message, progress)

    try:
        result = run_pipeline(
            job_id,
            source,
            cancel_event=job.cancel_event,
            on_stage=on_stage,
            profile=profile,
            audio_quality=audio_quality,
            options=options,
        )
    except TranscriberError as exc:
        status: JobStatus = "cancelled" if exc.code == "cancelled" else "failed"
        job_manager.set_error(job_id, exc.code, exc.message, status=status)
        if status == "failed":
            try:
                _record_failure(
                    job_id, source, exc.message,
                    _retry_request(source, profile, audio_quality, options),
                )
            except OSError:
                logger.warning("No se pudo guardar el error de %s en el historial", job_id)
        return
    except Exception as exc:  # noqa: BLE001 - a job must always reach a final state
        logger.exception("Error inesperado en el trabajo %s", job_id)
        job_manager.set_error(job_id, "internal_error", f"Se produjo un error inesperado: {exc}")
        return

    job_manager.set_result(job_id, result)
    if replaces and replaces != job_id:
        # "Volver a transcribir" replaces the earlier result instead of duplicating it.
        try:
            if history_store.delete_entry(replaces, delete_files=True):
                job_manager.remove_job(replaces)
        except OSError:
            # Some file is in use; the earlier result stays complete and can be deleted later.
            logger.warning("No se pudo eliminar el resultado anterior %s", replaces, exc_info=True)


def _dedup_key(url: str, profile: str, audio_quality: str, options: TranscriptionOptions) -> str:
    return "|".join(
        [_source_key(url), profile, audio_quality, repr(sorted(options.cache_fields().items()))]
    )


@router.post("/jobs", response_model=JobResponse, status_code=201)
def create_job_from_url(payload: CreateJobFromUrlRequest) -> JobResponse:
    try:
        validate_supported_url(payload.url)
    except UnsupportedURLError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": exc.message}
        ) from exc

    options = payload.to_options()
    cached = history_store.find_cached(
        payload.url, payload.profile, payload.audio_quality, options
    )
    replaces = cached[0] if cached and payload.force else None
    if cached and not payload.force:
        cached_id, result = cached
        job = job_manager.create_job(cached_id, source=payload.url)
        job_manager.set_result(cached_id, result, "Resultado reutilizado del historial.")
        return JobResponse(id=job.id, status="completed", cached=True)

    dedup_key = _dedup_key(payload.url, payload.profile, payload.audio_quality, options)
    running = None if payload.force else job_manager.find_active(dedup_key)
    if running is not None:
        return JobResponse(id=running.id, status=running.status)

    job = job_manager.create_job(source=payload.url, dedup_key=dedup_key)
    _start_background(
        job.id, URLSource(url=payload.url), payload.profile, payload.audio_quality, options,
        replaces,
    )
    return JobResponse(id=job.id, status=job.status)


def _is_media_upload(file: UploadFile) -> bool:
    if file.content_type and file.content_type.startswith(("audio/", "video/")):
        return True
    suffix = PureWindowsPath(file.filename or "").suffix.lower()
    generic_type = not file.content_type or file.content_type == "application/octet-stream"
    return generic_type and suffix in _MEDIA_EXTENSIONS


@router.post("/jobs/upload", response_model=JobResponse, status_code=201)
async def create_job_from_upload(
    file: UploadFile,
    profile: Annotated[TranscriptionProfile, Form()] = "balanced",
    language: Annotated[str | None, Form()] = None,
    task: Annotated[str, Form()] = "transcribe",
    initial_prompt: Annotated[str | None, Form()] = None,
    word_timestamps: Annotated[bool, Form()] = False,
    diarize: Annotated[bool, Form()] = False,
    num_speakers: Annotated[int | None, Form()] = None,
) -> JobResponse:
    job = None
    upload_dir = None
    try:
        try:
            options = TranscriptionOptionsSchema(
                language=language or None, task=task,  # type: ignore[arg-type]
                initial_prompt=initial_prompt or None, word_timestamps=word_timestamps,
                diarize=diarize, num_speakers=num_speakers,
            ).to_options()
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Opciones de transcripción no válidas") from exc
        if not _is_media_upload(file):
            raise HTTPException(status_code=400, detail="Solo se admiten archivos de audio o vídeo")
        if file.size is not None and file.size > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="El archivo supera el tamaño permitido")
        original_name = PureWindowsPath(file.filename or "archivo subido").name
        job = job_manager.create_job(source=original_name)
        upload_dir = settings.temp_dir / job.id
        upload_dir.mkdir(parents=True, exist_ok=True)
        # Never use a client-supplied filename as a filesystem path.
        dest_path = upload_dir / "upload.media"
        size = 0
        with dest_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="El archivo supera el tamaño permitido")
                output.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="El archivo está vacío")
    except BaseException:
        if upload_dir is not None:
            shutil.rmtree(upload_dir, ignore_errors=True)
        if job is not None:
            job_manager.set_error(job.id, "upload_failed", "No se pudo guardar el archivo subido")
        raise
    finally:
        await file.close()

    source = FileSource(path=dest_path, original_name=original_name)
    _start_background(job.id, source, profile, "best", options)
    return JobResponse(id=job.id, status=job.status)


def _get_job(job_id: str) -> JobRecord:
    job = job_manager.get_job(job_id)
    if job is None:
        result = history_store.load_result(job_id)
        if result is not None:
            job = job_manager.create_job(job_id)
            job_manager.set_result(job_id, result, "Resultado recuperado del historial.")
    if job is None:
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
    return job


def _status_response(job: JobRecord) -> JobStatusResponse:
    return JobStatusResponse(
        id=job.id,
        status=job.status,
        stage_message=job.stage_message,
        progress_percent=job.progress_percent,
        error=JobErrorPayload(**job.error) if job.error else None,
        source=job.source,
        created_at=job.created_at,
    )


@router.get("/jobs", response_model=list[JobStatusResponse])
def list_jobs() -> list[JobStatusResponse]:
    """Jobs known to this server run, oldest first, for the batch queue view."""
    return [_status_response(job) for job in job_manager.list_jobs() if job.source]


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    return _status_response(_get_job(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse, status_code=202)
def cancel_job(job_id: str) -> JobResponse:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
    if job.status in _TERMINAL:
        raise HTTPException(status_code=409, detail="La transcripción ya ha terminado")
    job_manager.request_cancel(job_id)
    return JobResponse(id=job.id, status=job.status)


@router.get("/jobs/{job_id}/result", response_model=TranscriptResultSchema)
def get_job_result(job_id: str) -> TranscriptResultSchema:
    job = _get_job(job_id)
    if job.status != "completed" or job.result is None:
        raise HTTPException(status_code=409, detail="La transcripción todavía no ha terminado")
    return _result_schema(job.result, _has_audio(job_id), *_summary(job_id))


def _has_audio(job_id: str) -> bool:
    return (settings.output_dir / job_id / LISTENING_COPY).is_file()


def _summary(job_id: str) -> tuple[str | None, bool]:
    """The saved summary, and whether the transcript was corrected after it."""
    folder = settings.output_dir / job_id
    try:
        summary_path = folder / SUMMARY_FILE
        text = summary_path.read_text(encoding="utf-8")
        outdated = summary_path.stat().st_mtime < (folder / "transcript.json").stat().st_mtime
        return text, outdated
    except OSError:
        return None, False


@router.get("/summary/status", response_model=SummaryStatusResponse)
def summary_status() -> SummaryStatusResponse:
    current = summarizer.status()
    return SummaryStatusResponse(available=current.available, model=current.model)


SummaryState = Literal["idle", "running", "done", "failed", "cancelled"]


@dataclass
class _SummaryTask:
    state: SummaryState = "running"
    message: str = "En cola para resumir..."
    error: dict | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)


# Summaries run in the background: on a CPU they take many minutes, longer than an
# HTTP request should wait. One at a time, because Ollama answers one at a time.
_SUMMARY_TASKS: dict[str, _SummaryTask] = {}
_SUMMARY_LOCK = threading.Lock()
_SUMMARY_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="summary")


def _summary_response(job_id: str, task: _SummaryTask | None) -> SummaryTaskResponse:
    if task is None:
        return SummaryTaskResponse(state="idle", message="")
    return SummaryTaskResponse(
        state=task.state,
        message=task.message,
        error=JobErrorPayload(**task.error) if task.error else None,
        markdown=_summary(job_id)[0] if task.state == "done" else None,
    )


def _run_summary(job_id: str, result: TranscriptionResult, title: str, task: _SummaryTask) -> None:
    folder = settings.output_dir / job_id

    def progress(message: str) -> None:
        task.message = message

    try:
        if task.cancel_event.is_set():
            raise JobCancelledError("Se canceló el resumen")
        progress("Preparando el resumen...")
        markdown = summarizer.summarize(result, title, progress, task.cancel_event)
        if task.cancel_event.is_set():
            raise JobCancelledError("Se canceló el resumen")
        if not folder.is_dir():
            raise summarizer.SummaryError("La transcripción se eliminó mientras se resumía")
        atomic_write_text(folder / SUMMARY_FILE, markdown)
        task.state, task.message = "done", "Resumen listo."
    except JobCancelledError as exc:
        task.state, task.message = "cancelled", exc.message
    except TranscriberError as exc:
        task.state, task.message = "failed", exc.message
        task.error = {"code": exc.code, "message": exc.message}
    except Exception as exc:  # noqa: BLE001 - the task must always reach a final state
        logger.exception("Error inesperado al resumir %s", job_id)
        message = f"No se pudo generar el resumen: {exc}"
        task.state, task.message = "failed", message
        task.error = {"code": "summary_failed", "message": message}


@router.post("/jobs/{job_id}/summary", response_model=SummaryTaskResponse, status_code=202)
def create_summary(job_id: str) -> SummaryTaskResponse:
    """Start summarising with the local Ollama server; poll GET for progress."""
    job = _get_job(job_id)
    if job.status != "completed" or job.result is None:
        raise HTTPException(status_code=409, detail="La transcripción todavía no ha terminado")
    folder = settings.output_dir / job_id
    if not (folder / "transcript.json").is_file():
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
    with _SUMMARY_LOCK:
        task = _SUMMARY_TASKS.get(job_id)
        if task is not None and task.state == "running":
            return _summary_response(job_id, task)  # Never run two summaries of one job.
    current = summarizer.status()
    if not current.available:
        raise HTTPException(status_code=503, detail={
            "code": summarizer.SummaryError.code,
            "message": "Ollama no está disponible. Comprueba que esté abierto y con un modelo "
                       "descargado (por ejemplo 'ollama pull llama3.2').",
        })
    try:
        payload = json.loads((folder / "transcript.json").read_text(encoding="utf-8"))
        title = str(payload.get("title") or "")
    except (OSError, ValueError):
        title = ""
    with _SUMMARY_LOCK:
        task = _SUMMARY_TASKS.get(job_id)
        if task is not None and task.state == "running":
            return _summary_response(job_id, task)
        task = _SummaryTask()
        _SUMMARY_TASKS[job_id] = task
    _SUMMARY_EXECUTOR.submit(_run_summary, job_id, job.result, title or job_id, task)
    return _summary_response(job_id, task)


@router.get("/jobs/{job_id}/summary", response_model=SummaryTaskResponse)
def get_summary_task(job_id: str) -> SummaryTaskResponse:
    with _SUMMARY_LOCK:
        task = _SUMMARY_TASKS.get(job_id)
    return _summary_response(job_id, task)


@router.delete("/jobs/{job_id}/summary", response_model=SummaryTaskResponse, status_code=202)
def cancel_summary(job_id: str) -> SummaryTaskResponse:
    with _SUMMARY_LOCK:
        task = _SUMMARY_TASKS.get(job_id)
        if task is None or task.state != "running":
            raise HTTPException(status_code=409, detail="No hay ningún resumen en curso")
        task.cancel_event.set()
        task.message = "Cancelando el resumen..."
    return _summary_response(job_id, task)


@router.get("/jobs/{job_id}/audio")
def get_job_audio(job_id: str) -> FileResponse:
    """Audio copy for playback. FileResponse honours Range requests, so seeking works."""
    _get_job(job_id)
    path = settings.output_dir / job_id / LISTENING_COPY
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No se guardó el audio de esta transcripción")
    return FileResponse(path, media_type="audio/mp4")


@router.patch("/jobs/{job_id}/transcript", response_model=TranscriptResultSchema)
def edit_transcript(job_id: str, payload: TranscriptEditRequest) -> TranscriptResultSchema:
    """Correct segment text and rename speakers; every export is rewritten."""
    job = _get_job(job_id)
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="La transcripción todavía no ha terminado")
    try:
        result = history_store.update_transcript(
            job_id,
            {edit.index: edit.text for edit in payload.segments},
            payload.speakers,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
    job_manager.set_result(job_id, result, "Transcripción corregida.")
    return _result_schema(result, _has_audio(job_id), *_summary(job_id))


def _result_schema(
    result: TranscriptionResult, has_audio: bool, summary: str | None = None,
    summary_outdated: bool = False,
) -> TranscriptResultSchema:
    return TranscriptResultSchema(
        has_audio=has_audio,
        summary=summary,
        summary_outdated=summary_outdated,
        segments=[
            TranscriptSegmentSchema(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                speaker=seg.speaker,
                words=[
                    TranscriptWordSchema(start=w.start, end=w.end, word=w.word)
                    for w in seg.words
                ],
            )
            for seg in result.segments
        ],
        language=result.language,
        language_probability=result.language_probability,
        duration=result.duration,
        word_count=result.word_count,
        text=result.text,
        model_size=result.model_size,
        device=result.device,
        compute_type=result.compute_type,
        batch_size=result.batch_size,
        profile=result.profile,
        audio_language=result.audio_language,
        audio_format_id=result.audio_format_id,
        audio_selection=result.audio_selection,
        timings=result.timings,
        source=result.source,
        edited=result.edited,
        **result.options.cache_fields(),
    )


@router.get("/jobs/{job_id}/download/{fmt}")
def download_export(job_id: str, fmt: str) -> FileResponse:
    _get_job(job_id)
    filename = _ALLOWED_EXPORT_FORMATS.get(fmt)
    if filename is None:
        raise HTTPException(status_code=404, detail="El formato de exportación no es compatible")
    path = settings.output_dir / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="No se encontró el archivo")
    return FileResponse(path, filename=filename)


@router.get("/history", response_model=list[HistoryItemSchema])
def list_history(q: str = "") -> list[dict]:
    return history_store.list_entries(q)


@router.delete("/history/{item_id}", status_code=204)
def delete_history_item(item_id: str, delete_files: bool = False) -> None:
    job = job_manager.get_job(item_id)
    if job and job.status not in _TERMINAL:
        raise HTTPException(status_code=409, detail="El trabajo sigue en curso")
    try:
        deleted = history_store.delete_entry(item_id, delete_files)
    except OSError as exc:
        raise HTTPException(
            status_code=409,
            detail="No se pudieron borrar los archivos porque alguno está en uso. Detén la "
                   "reproducción del audio o cierra los archivos abiertos y vuelve a intentarlo.",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
    job_manager.remove_job(item_id)
    with _SUMMARY_LOCK:
        task = _SUMMARY_TASKS.pop(item_id, None)
    if task is not None:
        task.cancel_event.set()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    device = select_device(settings.device)
    compute_type = resolve_compute_type(settings.compute_type, device)
    return HealthResponse(
        status="ok",
        ffmpeg=check_ffmpeg_available(),
        device=device,
        compute_type=compute_type,
        gpu_memory_mb=get_gpu_memory_mb() if device == "cuda" else None,
        batch_size=resolve_batch_size(settings.batch_size, device, "balanced"),
        loaded_models=model_cache.loaded(),
        max_upload_bytes=settings.max_upload_bytes,
    )
