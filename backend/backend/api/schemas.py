from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backend.core.job_manager import JobStatus
from backend.core.transcriber import TranscriptionOptions


LanguageCode = Annotated[str, Field(pattern=r"^[a-z]{2,3}$")]
InitialPrompt = Annotated[str, Field(max_length=500)]


class TranscriptionOptionsSchema(BaseModel):
    language: LanguageCode | None = None
    task: Literal["transcribe", "translate"] = "transcribe"
    initial_prompt: InitialPrompt | None = None
    word_timestamps: bool = False

    def to_options(self) -> TranscriptionOptions:
        return TranscriptionOptions(
            language=self.language,
            task=self.task,
            initial_prompt=(self.initial_prompt or "").strip() or None,
            word_timestamps=self.word_timestamps,
        )


class CreateJobFromUrlRequest(TranscriptionOptionsSchema):
    url: str
    profile: Literal["fast", "balanced", "precise"] = "balanced"
    audio_quality: Literal["compact", "balanced", "best"] = "balanced"
    force: bool = False


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
    source: str = ""
    created_at: str = ""


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
    timings: dict[str, float] = Field(default_factory=dict)
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
    audio_language: str | None = None
    audio_format_id: str | None = None
    audio_selection: Literal["original", "default"] | None = None
    requested_language: str | None = None
    task: Literal["transcribe", "translate"] = "transcribe"
    initial_prompt: str | None = None
    word_timestamps: bool = False


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
    status: Literal["completed", "failed"] = "completed"
    error: str | None = None


class HealthResponse(BaseModel):
    app: Literal["VideoTranscriber"] = "VideoTranscriber"
    status: str
    ffmpeg: bool
    device: str
    compute_type: str
    gpu_memory_mb: int | None
    batch_size: int
    loaded_models: list[str] = Field(default_factory=list)
