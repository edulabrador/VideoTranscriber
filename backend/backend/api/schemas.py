from typing import Literal

from pydantic import BaseModel

from backend.core.job_manager import JobStatus


class CreateJobFromUrlRequest(BaseModel):
    url: str
    profile: Literal["fast", "balanced", "precise"] = "balanced"
    audio_quality: Literal["compact", "balanced", "best"] = "balanced"


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    cached: bool = False


class JobErrorPayload(BaseModel):
    code: str
    message: str


class JobStatusResponse(BaseModel):
    id: str
    status: JobStatus
    stage_message: str
    progress_percent: int
    error: JobErrorPayload | None = None


class TranscriptWordSchema(BaseModel):
    start: float
    end: float
    word: str


class TranscriptSegmentSchema(BaseModel):
    start: float
    end: float
    text: str
    words: list[TranscriptWordSchema]


class TranscriptResultSchema(BaseModel):
    segments: list[TranscriptSegmentSchema]
    language: str
    language_probability: float
    duration: float
    word_count: int
    text: str
    model_size: str
    device: str
    compute_type: str
    batch_size: int
    profile: Literal["fast", "balanced", "precise"]


class HistoryItemSchema(BaseModel):
    id: str
    source_type: str
    source: str
    title: str
    created_at: str
    duration: float
    word_count: int
    language: str
    text: str | None = None


class HealthResponse(BaseModel):
    status: str
    ffmpeg: bool
    device: str
    compute_type: str
    gpu_memory_mb: int | None
    batch_size: int
