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
    resolve_batch_size,
    resolve_compute_type,
    resolve_model_size,
    select_device_and_compute_type,
)

ProgressCallback = Callable[[int, int | None], None]
TranscriptionProfile = Literal["fast", "balanced", "precise"]


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
) -> TranscriptionResult:
    device, _ = select_device_and_compute_type(device_preference)
    model_size_preference, beam_size = resolve_profile_settings(
        profile,
        model_size_preference,
        beam_size,
    )

    model_size = resolve_model_size(model_size_preference, device)
    compute_type = resolve_compute_type(compute_type_preference, device)
    batch_size = resolve_batch_size(batch_size, device, profile)

    try:
        model = get_model(model_size, device, compute_type)
    except Exception as exc:  # noqa: BLE001 - surface as a typed transcription error
        raise TranscriptionError(f"No se pudo cargar el modelo de transcripción: {exc}") from exc

    try:
        transcriber = BatchedInferencePipeline(model=model) if device == "cuda" and batch_size > 1 else model
        options = {
            "vad_filter": True,
            "word_timestamps": False,
            "beam_size": beam_size,
        }
        if isinstance(transcriber, BatchedInferencePipeline):
            options["batch_size"] = batch_size
        segment_iter, info = transcriber.transcribe(str(audio_path), **options)

        segments: list[TranscriptSegment] = []
        text_parts: list[str] = []
        started_at = time.monotonic()
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
                    elapsed = time.monotonic() - started_at
                    eta = round(elapsed * (100 - progress) / progress) if progress >= 2 else None
                    on_progress(progress, eta)
                    last_progress = progress
        if on_progress:
            on_progress(100, 0)
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
    )
