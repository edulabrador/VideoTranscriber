import json
from dataclasses import asdict
from pathlib import Path

from backend.core.transcriber import TranscriptSegment, TranscriptWord, TranscriptionResult

PROCESSING_VERSION = 2


def _srt_timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_txt(result: TranscriptionResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.text + "\n", encoding="utf-8")
    return path


def write_srt(result: TranscriptionResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for i, seg in enumerate(result.segments, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(seg.start)} --> {_srt_timestamp(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_json(
    result: TranscriptionResult,
    path: Path,
    *,
    source: str,
    title: str,
    created_at: str,
    audio_quality: str = "best",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source,
        "title": title,
        "created_at": created_at,
        "language": result.language,
        "language_probability": result.language_probability,
        "duration": result.duration,
        "word_count": result.word_count,
        "model_size": result.model_size,
        "device": result.device,
        "compute_type": result.compute_type,
        "batch_size": result.batch_size,
        "profile": result.profile,
        "processing_version": PROCESSING_VERSION,
        "beam_size": result.beam_size,
        "audio_language": result.audio_language,
        "audio_format_id": result.audio_format_id,
        "audio_selection": result.audio_selection,
        "audio_quality": audio_quality,
        "timings": result.timings,
        "text": result.text,
        "segments": [asdict(seg) for seg in result.segments],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_json(path: Path) -> TranscriptionResult:
    return result_from_payload(json.loads(path.read_text(encoding="utf-8")))


def result_from_payload(payload: dict) -> TranscriptionResult:
    return TranscriptionResult(
        segments=[
            TranscriptSegment(
                start=segment["start"],
                end=segment["end"],
                text=segment["text"],
                words=[
                    TranscriptWord(start=word["start"], end=word["end"], word=word["word"])
                    for word in segment.get("words", [])
                ],
            )
            for segment in payload["segments"]
        ],
        language=payload["language"],
        language_probability=payload["language_probability"],
        duration=payload["duration"],
        text=payload["text"],
        model_size=payload["model_size"],
        device=payload["device"],
        compute_type=payload.get("compute_type", "unknown"),
        batch_size=payload.get("batch_size", 1),
        profile=payload.get("profile", "balanced"),
        beam_size=payload.get("beam_size", 1),
        audio_language=payload.get("audio_language"),
        audio_format_id=payload.get("audio_format_id"),
        audio_selection=payload.get("audio_selection"),
        timings=payload.get("timings", {}),
    )
