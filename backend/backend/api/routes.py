import asyncio
import shutil
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.api.schemas import (
    CreateJobFromUrlRequest,
    HealthResponse,
    HistoryItemSchema,
    JobErrorPayload,
    JobResponse,
    JobStatusResponse,
    TranscriptResultSchema,
    TranscriptSegmentSchema,
    TranscriptWordSchema,
)
from backend.config import settings
from backend.core.audio import check_ffmpeg_available
from backend.core.downloader import AudioQuality
from backend.core.errors import TranscriberError, UnsupportedURLError
from backend.core.history import history_store
from backend.core.job_manager import JobStatus, job_manager
from backend.core.model_manager import (
    get_gpu_memory_mb,
    resolve_batch_size,
    resolve_compute_type,
    select_device_and_compute_type,
)
from backend.core.pipeline import FileSource, Source, URLSource, run_pipeline
from backend.core.transcriber import TranscriptionProfile
from backend.core.validators import validate_instagram_url

router = APIRouter(prefix="/api")

_ALLOWED_EXPORT_FORMATS = {
    "txt": "transcript.txt",
    "srt": "subtitles.srt",
    "json": "transcript.json",
}


def _run_job(
    job_id: str,
    source: Source,
    profile: TranscriptionProfile,
    audio_quality: AudioQuality = "balanced",
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
        )
        job_manager.set_result(job_id, result)
    except TranscriberError as exc:
        status: JobStatus = "cancelled" if exc.code == "cancelled" else "failed"
        job_manager.set_error(job_id, exc.code, exc.message, status=status)


@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job_from_url(payload: CreateJobFromUrlRequest) -> JobResponse:
    try:
        validate_instagram_url(payload.url)
    except UnsupportedURLError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": exc.message}
        ) from exc

    cached = history_store.find_cached(payload.url, payload.profile, payload.audio_quality)
    if cached:
        cached_id, result = cached
        job = job_manager.create_job(cached_id)
        job_manager.set_result(cached_id, result, "Resultado reutilizado del historial.")
        return JobResponse(id=job.id, status="completed", cached=True)

    job = job_manager.create_job()
    asyncio.create_task(
        asyncio.to_thread(
            _run_job,
            job.id,
            URLSource(url=payload.url),
            payload.profile,
            payload.audio_quality,
        )
    )
    return JobResponse(id=job.id, status=job.status)


@router.post("/jobs/upload", response_model=JobResponse, status_code=201)
async def create_job_from_upload(
    file: UploadFile,
    profile: Annotated[TranscriptionProfile, Form()] = "balanced",
) -> JobResponse:
    if not file.content_type or not (
        file.content_type.startswith("audio/") or file.content_type.startswith("video/")
    ):
        raise HTTPException(status_code=400, detail="Solo se admiten archivos de audio o vídeo")

    job = job_manager.create_job()
    upload_dir = settings.temp_dir / job.id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / (file.filename or "upload")
    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    source = FileSource(path=dest_path, original_name=file.filename or "archivo subido")
    asyncio.create_task(asyncio.to_thread(_run_job, job.id, source, profile, "best"))
    return JobResponse(id=job.id, status=job.status)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
    return JobStatusResponse(
        id=job.id,
        status=job.status,
        stage_message=job.stage_message,
        progress_percent=job.progress_percent,
        error=JobErrorPayload(**job.error) if job.error else None,
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse, status_code=202)
async def cancel_job(job_id: str) -> JobResponse:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
    if job.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail="La transcripción ya ha terminado")
    job_manager.request_cancel(job_id)
    return JobResponse(id=job.id, status=job.status)


@router.get("/jobs/{job_id}/result", response_model=TranscriptResultSchema)
async def get_job_result(job_id: str) -> TranscriptResultSchema:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No se encontró la transcripción")
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
    )


@router.get("/jobs/{job_id}/download/{fmt}")
async def download_export(job_id: str, fmt: str) -> FileResponse:
    filename = _ALLOWED_EXPORT_FORMATS.get(fmt)
    if filename is None:
        raise HTTPException(status_code=404, detail="El formato de exportación no es compatible")
    path = settings.output_dir / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="No se encontró el archivo")
    return FileResponse(path, filename=filename)


@router.get("/history", response_model=list[HistoryItemSchema])
async def list_history() -> list[dict]:
    return history_store.list_entries()


@router.delete("/history/{item_id}", status_code=204)
async def delete_history_item(item_id: str) -> None:
    history_store.delete_entry(item_id)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    device, _ = select_device_and_compute_type(settings.device)
    compute_type = resolve_compute_type(settings.compute_type, device)
    return HealthResponse(
        status="ok",
        ffmpeg=check_ffmpeg_available(),
        device=device,
        compute_type=compute_type,
        gpu_memory_mb=get_gpu_memory_mb() if device == "cuda" else None,
        batch_size=resolve_batch_size(settings.batch_size, device, "balanced"),
    )
