import json
from dataclasses import asdict, dataclass
from pathlib import Path

from backend.core.transcriber import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
)

PROCESSING_VERSION = 2

# A silence longer than this starts a new paragraph in TXT and Markdown.
PARAGRAPH_PAUSE_SECONDS = 1.5
# Common subtitle limits: two lines of about 42 characters, at most ~6 seconds on screen.
SUBTITLE_LINE_CHARS = 42
SUBTITLE_MAX_LINES = 2
SUBTITLE_MAX_SECONDS = 6.0


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _timestamp(seconds: float, separator: str) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _srt_timestamp(seconds: float) -> str:
    return _timestamp(seconds, ",")


def _clock(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def paragraphs(segments: list[TranscriptSegment]) -> list[tuple[float, str]]:
    """Group segments into paragraphs separated by pauses. Returns (start, text)."""
    groups: list[tuple[float, list[str]]] = []
    previous_end: float | None = None
    for segment in segments:
        if not segment.text:
            continue
        if not groups or (
            previous_end is not None and segment.start - previous_end > PARAGRAPH_PAUSE_SECONDS
        ):
            groups.append((segment.start, []))
        groups[-1][1].append(segment.text)
        previous_end = segment.end
    return [(start, " ".join(parts)) for start, parts in groups]


def _timed_words(segment: TranscriptSegment) -> list[TranscriptWord]:
    """Real word timings when available, otherwise times spread by character length."""
    if segment.words:
        return [word for word in segment.words if word.word]
    tokens = segment.text.split()
    if not tokens:
        return []
    duration = max(0.0, segment.end - segment.start)
    total_chars = sum(len(token) + 1 for token in tokens)
    words: list[TranscriptWord] = []
    cursor = segment.start
    for token in tokens:
        span = duration * (len(token) + 1) / total_chars
        words.append(TranscriptWord(start=cursor, end=cursor + span, word=token))
        cursor += span
    return words


def _wrap(text: str) -> str:
    if len(text) <= SUBTITLE_LINE_CHARS:
        return text
    # Break at the space closest to the middle so both lines are balanced.
    middle = len(text) // 2
    spaces = [index for index, char in enumerate(text) if char == " "]
    if not spaces:
        return text
    split = min(spaces, key=lambda index: abs(index - middle))
    return f"{text[:split]}\n{text[split + 1:]}"


def subtitle_cues(segments: list[TranscriptSegment]) -> list[Cue]:
    """Split Whisper segments into readable subtitle cues."""
    max_chars = SUBTITLE_LINE_CHARS * SUBTITLE_MAX_LINES
    cues: list[Cue] = []
    for segment in segments:
        current: list[TranscriptWord] = []
        for word in _timed_words(segment):
            candidate = " ".join(w.word for w in [*current, word])
            too_long = len(candidate) > max_chars
            too_slow = bool(current) and word.end - current[0].start > SUBTITLE_MAX_SECONDS
            if current and (too_long or too_slow):
                cues.append(Cue(current[0].start, current[-1].end, " ".join(w.word for w in current)))
                current = []
            current.append(word)
            if word.word.endswith((".", "?", "!", "…")) and len(candidate) > SUBTITLE_LINE_CHARS:
                cues.append(Cue(current[0].start, current[-1].end, " ".join(w.word for w in current)))
                current = []
        if current:
            cues.append(Cue(current[0].start, current[-1].end, " ".join(w.word for w in current)))
    return cues


def write_txt(result: TranscriptionResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = [text for _start, text in paragraphs(result.segments)] or [result.text]
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


def write_srt(result: TranscriptionResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for i, cue in enumerate(subtitle_cues(result.segments), start=1):
        lines.append(str(i))
        lines.append(f"{_timestamp(cue.start, ',')} --> {_timestamp(cue.end, ',')}")
        lines.append(_wrap(cue.text))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_vtt(result: TranscriptionResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["WEBVTT", ""]
    for cue in subtitle_cues(result.segments):
        lines.append(f"{_timestamp(cue.start, '.')} --> {_timestamp(cue.end, '.')}")
        lines.append(_wrap(cue.text))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_markdown(result: TranscriptionResult, path: Path, *, title: str, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", "", f"Fuente: {source}", ""]
    for start, text in paragraphs(result.segments) or [(0.0, result.text)]:
        lines.append(f"**[{_clock(start)}]** {text}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_all(
    result: TranscriptionResult,
    output_dir: Path,
    *,
    source: str,
    title: str,
    created_at: str,
    audio_quality: str,
) -> None:
    write_txt(result, output_dir / "transcript.txt")
    write_srt(result, output_dir / "subtitles.srt")
    write_vtt(result, output_dir / "subtitles.vtt")
    write_markdown(result, output_dir / "transcript.md", title=title, source=source)
    write_json(
        result,
        output_dir / "transcript.json",
        source=source,
        title=title,
        created_at=created_at,
        audio_quality=audio_quality,
    )


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
        **result.options.cache_fields(),
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
        options=TranscriptionOptions(
            language=payload.get("requested_language"),
            task=payload.get("task", "transcribe"),
            initial_prompt=payload.get("initial_prompt"),
            word_timestamps=payload.get("word_timestamps", False),
        ),
    )
