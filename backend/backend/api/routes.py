import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import PureWindowsPath
from typing import Annotated

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
    TranscriptionOptionsSchema,
    TranscriptResultSchema,
    TranscriptSegmentSchema,
    TranscriptWordSchema,
)
from backend.config import settings
from backend.core.audio import check_ffmpeg_available
from backend.core.downloader import AudioQuality
from backend.core.errors import TranscriberError, UnsupportedURLError
from backend.core.history import HistoryItem, _source_key, history_store
from backend.core.job_manager import JobRecord, JobStatus, job_manager
from backend.core.model_manager import (
    get_gpu_memory_mb,
    model_cache,
    resolve_batch_size,
    resolve_compute_type,
    select_device,
)
from backend.core.pipeline import FileSource, Source, URLSource, run_pipeline
from backend.core.transcriber import TranscriptionOptions, TranscriptionProfile
from backend.core.validators import validate_supported_url

router = APIRouter(prefix="/api")

_ALLOWED_EXPORT_FORMATS = {
    "txt": "transcript.txt",
    "srt": "subtitles.srt",
    "vtt": "subtitles.vtt",
    "md": "transcript.md",
    "json": "transcript.json",
}
# Browsers often send these as application/octet-stream or with no type at all.
# FFmpeg makes the real decision when it prepares the audio.
_MEDIA_EXTENSIONS = {
    ".aac", ".aiff", ".amr", ".avi", ".flac", ".flv", ".m4a", ".m4v", ".mka", ".mkv",
    ".mov", ".mp3", ".mp4", ".mpeg", ".mpg", ".oga", ".ogg", ".opus", ".ts", ".wav",
    ".weba", ".webm", ".wma", ".wmv", ".3gp",
}
_TERMINAL = {"completed", "failed", "cancelled"}
# Strong references keep background jobs alive until they finish.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _start_background(job_id: str, source: Source, profile: TranscriptionProfile,
                      audio_quality: AudioQuality, options: TranscriptionOptions) -> None:
    task = asyncio.create_task(
        asyncio.to_thread(_run_job, job_id, source, profile, audio_quality, options)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _record_failure(job_id: str, source: Source, message: str) -> None:
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
        )
    )


def _run_job(
    job_id: str,
    source: Source,
    profile: TranscriptionProfile,
    audio_quality: AudioQuality = "balanced",
    options: TranscriptionOptions | None = None,
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
        job_manager.set_result(job_id, result)
    except TranscriberError as exc:
        status: JobStatus = "cancelled" if exc.code == "cancelled" else "failed"
        job_manager.set_error(job_id, exc.code, exc.message, status=status)
        if status == "failed":
            try:
                _record_failure(job_id, source, exc.message)
            except OSError:
                pass  # The error is still visible in the job itself.


def _dedup_key(url: str, profile: str, audio_quality: str, options: TranscriptionOptions) -> str:
    return "|".join(
        [_source_key(url), profile, audio_quality, repr(sorted(options.cache_fields().items()))]
    )


@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job_from_url(payload: CreateJobFromUrlRequest) -> JobResponse:
    try:
        validate_supported_url(payload.url)
    except UnsupportedURLError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": exc.message}
        ) from exc

    options = payload.to_options()
    cached = None if payload.force else history_store.find_cached(
        payload.url, payload.profile, payload.audio_quality, options
    )
    if cached:
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
) -> JobResponse:
    job = None
    upload_dir = None
    try:
        try:
            options = TranscriptionOptionsSchema(
                language=language or None, task=task,  # type: ignore[arg-type]
                initial_prompt=initial_prompt or None, word_timestamps=word_timestamps,
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
async def list_jobs() -> list[JobStatusResponse]:
    """Jobs known to this server run, oldest first, for the batch queue view."""
    return [_status_response(job) for job in job_manager.list_jobs() if job.source]


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    return _status_response(_get_job(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse, status_code=202)
async def cancel_job(job_id: str) -> JobResponse:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
    if job.status in _TERMINAL:
        raise HTTPException(status_code=409, detail="La transcripción ya ha terminado")
    job_manager.request_cancel(job_id)
    return JobResponse(id=job.id, status=job.status)


@router.get("/jobs/{job_id}/result", response_model=TranscriptResultSchema)
async def get_job_result(job_id: str) -> TranscriptResultSchema:
    job = _get_job(job_id)
    if job.status != "completed" or job.result is None:
        raise HTTPException(status_code=409, detail="La transcripción todavía no ha terminado")
    result = job.result
    return TranscriptResultSchema(
        segments=[
            TranscriptSegmentSchema(
                start=seg.start,
                end=seg.end,
                text=seg.text,
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
        **result.options.cache_fields(),
    )


@router.get("/jobs/{job_id}/download/{fmt}")
async def download_export(job_id: str, fmt: str) -> FileResponse:
    _get_job(job_id)
    filename = _ALLOWED_EXPORT_FORMATS.get(fmt)
    if filename is None:
        raise HTTPException(status_code=404, detail="El formato de exportación no es compatible")
    path = settings.output_dir / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="No se encontró el archivo")
    return FileResponse(path, filename=filename)


@router.get("/history", response_model=list[HistoryItemSchema])
async def list_history(q: str = "") -> list[dict]:
    return history_store.list_entries(q)


@router.delete("/history/{item_id}", status_code=204)
async def delete_history_item(item_id: str, delete_files: bool = False) -> None:
    job = job_manager.get_job(item_id)
    if job and job.status not in _TERMINAL:
        raise HTTPException(status_code=409, detail="El trabajo sigue en curso")
    if not history_store.delete_entry(item_id, delete_files):
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
    job_manager.remove_job(item_id)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
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
    )
