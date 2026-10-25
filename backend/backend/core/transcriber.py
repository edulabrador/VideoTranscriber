import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from faster_whisper import BatchedInferencePipeline

from backend.core.errors import JobCancelledError, TranscriptionError
from backend.core.model_manager import (
    get_model,
    is_model_cached,
    resolve_batch_size,
    resolve_compute_type,
    resolve_model_size,
    select_device,
)

ProgressCallback = Callable[[int, int | None], None]
TranscriptionProfile = Literal["fast", "balanced", "precise"]
TranscriptionTask = Literal["transcribe", "translate"]


@dataclass(frozen=True)
class TranscriptionOptions:
    """Per-job choices that change the text, and therefore the cache key."""

    language: str | None = None  # None lets Whisper detect it.
    task: TranscriptionTask = "transcribe"
    initial_prompt: str | None = None
    word_timestamps: bool = False

    def cache_fields(self) -> dict:
        return {
            "requested_language": self.language,
            "task": self.task,
            "initial_prompt": self.initial_prompt,
            "word_timestamps": self.word_timestamps,
        }


@dataclass
class TranscriptWord:
    start: float
    end: float
    word: str


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: list[TranscriptWord] = field(default_factory=list)


@dataclass
class TranscriptionResult:
    segments: list[TranscriptSegment]
    language: str
    language_probability: float
    duration: float
    text: str
    model_size: str
    device: str
    compute_type: str
    batch_size: int
    profile: TranscriptionProfile
    beam_size: int = 1
    audio_language: str | None = None
    audio_format_id: str | None = None
    audio_selection: Literal["original", "default"] | None = None
    timings: dict[str, float] = field(default_factory=dict)
    options: TranscriptionOptions = field(default_factory=TranscriptionOptions)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def resolve_profile_settings(
    profile: TranscriptionProfile,
    configured_model: str,
    configured_beam_size: int,
) -> tuple[str, int]:
    if profile == "fast":
        return "small", 1
    if profile == "precise":
        return "large-v3", 5
    return configured_model, configured_beam_size


def resolve_job_model(
    profile: TranscriptionProfile,
    options: TranscriptionOptions,
    configured_model: str,
    configured_beam_size: int,
    device: str,
) -> tuple[str, int]:
    """Model and beam size a job really uses. Shared with the cache lookup."""
    model_size, beam_size = resolve_profile_settings(profile, configured_model, configured_beam_size)
    model_size = resolve_model_size(model_size, device)
    # The turbo checkpoints were not trained for translation; use full large-v3 instead.
    if options.task == "translate" and "turbo" in model_size:
        model_size = "large-v3"
    return model_size, beam_size


def transcribe_audio(
    audio_path: Path,
    model_size_preference: str,
    device_preference: str,
    compute_type_preference: str,
    cancel_event: threading.Event,
    batch_size: int = 1,
    beam_size: int = 1,
    profile: TranscriptionProfile = "balanced",
    on_progress: ProgressCallback | None = None,
    on_status: Callable[[Literal["loading_model", "transcribing"], str], None] | None = None,
    options: TranscriptionOptions | None = None,
) -> TranscriptionResult:
    options = options or TranscriptionOptions()
    device = select_device(device_preference)
    model_size, beam_size = resolve_job_model(
        profile, options, model_size_preference, beam_size, device,
    )
    compute_type = resolve_compute_type(compute_type_preference, device)
    batch_size = resolve_batch_size(batch_size, device, profile)

    load_started = time.perf_counter()
    try:
        if cancel_event.is_set():
            raise JobCancelledError()
        if on_status:
            message = (
                f"Cargando el modelo {model_size}..."
                if is_model_cached(model_size)
                else f"Descargando y cargando el modelo {model_size}. La primera vez puede tardar varios minutos."
            )
            on_status("loading_model", message)
        model = get_model(model_size, device, compute_type)
        model_loading_seconds = time.perf_counter() - load_started
    except JobCancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface as a typed transcription error
        raise TranscriptionError(f"No se pudo cargar el modelo de transcripción: {exc}") from exc

    try:
        if cancel_event.is_set():
            raise JobCancelledError()
        if on_status:
            on_status("transcribing", "Modelo listo. Analizando el audio...")
        analysis_started = time.perf_counter()
        transcriber = BatchedInferencePipeline(model=model) if device == "cuda" and batch_size > 1 else model
        decode_options: dict = {
            "vad_filter": True,
            "word_timestamps": options.word_timestamps,
            "beam_size": beam_size,
            "task": options.task,
        }
        if options.language:
            decode_options["language"] = options.language
        if options.initial_prompt:
            decode_options["initial_prompt"] = options.initial_prompt
        if isinstance(transcriber, BatchedInferencePipeline):
            decode_options["batch_size"] = batch_size
        segment_iter, info = transcriber.transcribe(str(audio_path), **decode_options)
        audio_analysis_seconds = time.perf_counter() - analysis_started

        segments: list[TranscriptSegment] = []
        text_parts: list[str] = []
        started_at = time.perf_counter()
        last_progress = -1
        for seg in segment_iter:
            if cancel_event.is_set():
                raise JobCancelledError()
            words = [
                TranscriptWord(start=w.start, end=w.end, word=w.word.strip())
                for w in (seg.words or [])
            ]
            segment_text = seg.text.strip()
            segments.append(
                TranscriptSegment(start=seg.start, end=seg.end, text=segment_text, words=words)
            )
            text_parts.append(segment_text)
            if on_progress and info.duration > 0:
                progress = min(99, max(0, round(seg.end * 100 / info.duration)))
                if progress > last_progress:
                    elapsed = time.perf_counter() - started_at
                    eta = round(elapsed * (100 - progress) / progress) if progress >= 2 else None
                    on_progress(progress, eta)
                    last_progress = progress
        if cancel_event.is_set():
            raise JobCancelledError()
        if on_progress:
            on_progress(100, 0)
        transcription_seconds = time.perf_counter() - started_at
    except JobCancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - wrap unexpected whisper/ctranslate2 errors
        raise TranscriptionError(f"La transcripción falló: {exc}") from exc

    return TranscriptionResult(
        segments=segments,
        language=info.language,
        language_probability=info.language_probability,
        duration=info.duration,
        text=" ".join(text_parts).strip(),
        model_size=model_size,
        device=device,
        compute_type=compute_type,
        batch_size=batch_size,
        profile=profile,
        beam_size=beam_size,
        timings={
            "model_loading": model_loading_seconds,
            "audio_analysis": audio_analysis_seconds,
            "transcription": transcription_seconds,
        },
        options=options,
    )
