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
    diarize: bool = False
    num_speakers: Annotated[int, Field(ge=1, le=20)] | None = None

    def to_options(self) -> TranscriptionOptions:
        return TranscriptionOptions(
            language=self.language,
            task=self.task,
            initial_prompt=(self.initial_prompt or "").strip() or None,
            word_timestamps=self.word_timestamps,
            diarize=self.diarize,
            num_speakers=self.num_speakers if self.diarize else None,
        )


class CreateJobFromUrlRequest(TranscriptionOptionsSchema):
    url: str
    profile: Literal["fast", "balanced", "precise"] = "balanced"
    audio_quality: Literal["compact", "balanced", "best"] = "balanced"
    force: bool = False


class SegmentEdit(BaseModel):
    index: int = Field(ge=0)
    text: str = Field(max_length=5000)


SpeakerName = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[^\r\n<>]+$")]


class TranscriptEditRequest(BaseModel):
    segments: list[SegmentEdit] = Field(default_factory=list, max_length=20000)
    speakers: dict[str, SpeakerName] = Field(default_factory=dict, max_length=50)


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
    speaker: str | None = None


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
    diarize: bool = False
    num_speakers: int | None = None
    source: str = ""
    edited: bool = False
    has_audio: bool = False
    summary: str | None = None


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


class SummaryStatusResponse(BaseModel):
    available: bool
    model: str | None = None


class SummaryResponse(BaseModel):
    markdown: str


class HealthResponse(BaseModel):
    app: Literal["VideoTranscriber"] = "VideoTranscriber"
    status: str
    ffmpeg: bool
    device: str
    compute_type: str
    gpu_memory_mb: int | None
    batch_size: int
    loaded_models: list[str] = Field(default_factory=list)
