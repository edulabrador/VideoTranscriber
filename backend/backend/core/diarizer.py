"""Speaker diarization with sherpa-onnx: pyannote segmentation + WeSpeaker embeddings.

Runs on ONNX Runtime, so it needs neither PyTorch nor a Hugging Face token. The two
models (about 33 MB) are downloaded from the sherpa-onnx releases on first use and
checked against pinned SHA-256 hashes.
"""
import hashlib
import logging
import os
import shutil
import tarfile
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.request import urlopen

from backend.config import settings
from backend.core.errors import DiarizationError, JobCancelledError
from backend.core.transcriber import TranscriptSegment, TranscriptWord

logger = logging.getLogger(__name__)
SAMPLE_RATE = 16000
_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"


@dataclass(frozen=True)
class _ModelFile:
    name: str
    url: str
    sha256: str
    member: str | None = None  # File to extract when the download is a tar archive.


SEGMENTATION_MODEL = _ModelFile(
    "segmentation.onnx",
    f"{_RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
    "sherpa-onnx-pyannote-segmentation-3-0/model.onnx",
)
EMBEDDING_MODEL = _ModelFile(
    "embedding.onnx",
    f"{_RELEASES}/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx",
    "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012",
)


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: int


class _Cancelled(Exception):
    """Raised from the progress callback; sherpa-onnx stops and re-raises it."""


def _models_dir() -> Path:
    return settings.models_dir / "diarization"


def models_ready() -> bool:
    return all((_models_dir() / spec.name).is_file() for spec in (SEGMENTATION_MODEL, EMBEDDING_MODEL))


def _download(spec: _ModelFile, target_dir: Path, cancel_event: threading.Event) -> None:
    target = target_dir / spec.name
    if target.is_file():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target_dir) as scratch:
        download = Path(scratch) / "download"
        digest = hashlib.sha256()
        try:
            with urlopen(spec.url, timeout=60) as response, download.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    if cancel_event.is_set():
                        raise JobCancelledError()
                    digest.update(chunk)
                    output.write(chunk)
        except OSError as exc:
            raise DiarizationError(
                f"No se pudo descargar el modelo de identificación de hablantes: {exc}"
            ) from exc
        if digest.hexdigest() != spec.sha256:
            raise DiarizationError("El modelo de hablantes descargado no supera la verificación")
        source = download
        if spec.member:
            with tarfile.open(download, "r:bz2") as archive:
                member = archive.getmember(spec.member)
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise DiarizationError("El archivo del modelo de hablantes está incompleto")
                source = Path(scratch) / "model.onnx"
                with extracted, source.open("wb") as output:
                    shutil.copyfileobj(extracted, output)
        os.replace(source, target)


def ensure_models(cancel_event: threading.Event) -> tuple[Path, Path]:
    directory = _models_dir()
    for spec in (SEGMENTATION_MODEL, EMBEDDING_MODEL):
        _download(spec, directory, cancel_event)
    return directory / SEGMENTATION_MODEL.name, directory / EMBEDDING_MODEL.name


def diarize(
    audio_path: Path,
    num_speakers: int | None,
    cancel_event: threading.Event,
    on_progress: Callable[[int], None] | None = None,
) -> list[SpeakerTurn]:
    """Who speaks when. ``num_speakers`` of None estimates the count from the audio."""
    import sherpa_onnx
    from faster_whisper import decode_audio

    if cancel_event.is_set():
        raise JobCancelledError()
    segmentation, embedding = ensure_models(cancel_event)
    threads = max(1, min(8, os.cpu_count() or 1))
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(segmentation)
            ),
            num_threads=threads,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(embedding), num_threads=threads,
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=num_speakers or -1,
            threshold=settings.diarization_threshold,
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise DiarizationError("La configuración de identificación de hablantes no es válida")

    try:
        audio = decode_audio(str(audio_path), sampling_rate=SAMPLE_RATE)
        engine = sherpa_onnx.OfflineSpeakerDiarization(config)

        def progress(done: int, total: int) -> int:
            if cancel_event.is_set():
                raise _Cancelled()
            if on_progress and total:
                on_progress(min(100, round(done * 100 / total)))
            return 0

        result = engine.process(audio, callback=progress).sort_by_start_time()
    except _Cancelled as exc:
        raise JobCancelledError() from exc
    except DiarizationError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface native failures as a typed error
        raise DiarizationError(f"No se pudo identificar a los hablantes: {exc}") from exc
    return [SpeakerTurn(float(turn.start), float(turn.end), int(turn.speaker)) for turn in result]


def _overlap(start: float, end: float, turn: SpeakerTurn) -> float:
    return max(0.0, min(end, turn.end) - max(start, turn.start))


def _speaker_at(start: float, end: float, turns: list[SpeakerTurn]) -> int | None:
    """Speaker overlapping the span the most, or the nearest one when none overlaps."""
    if not turns:
        return None
    best = max(turns, key=lambda turn: _overlap(start, end, turn))
    if _overlap(start, end, best) > 0:
        return best.speaker
    middle = (start + end) / 2
    return min(turns, key=lambda turn: min(abs(middle - turn.start), abs(middle - turn.end))).speaker


def speaker_label(index: int) -> str:
    return f"Hablante {index}"


def assign_speakers(
    segments: list[TranscriptSegment], turns: list[SpeakerTurn],
) -> list[TranscriptSegment]:
    """Label each segment with its speaker, splitting segments at word-level changes.

    Speakers are numbered in order of first appearance: "Hablante 1", "Hablante 2"...
    """
    if not turns:
        return segments
    pieces: list[tuple[TranscriptSegment, int | None]] = []
    for segment in segments:
        if not segment.words:
            pieces.append((segment, _speaker_at(segment.start, segment.end, turns)))
            continue
        runs: list[tuple[int | None, list[TranscriptWord]]] = []
        for word in segment.words:
            speaker = _speaker_at(word.start, word.end, turns)
            if runs and runs[-1][0] == speaker:
                runs[-1][1].append(word)
            else:
                runs.append((speaker, [word]))
        for speaker, words in runs:
            text = " ".join(word.word for word in words) if len(runs) > 1 else segment.text
            pieces.append((
                TranscriptSegment(words[0].start, words[-1].end, text, words)
                if len(runs) > 1 else segment,
                speaker,
            ))

    numbering: dict[int, int] = {}
    labelled: list[TranscriptSegment] = []
    for segment, raw in pieces:
        if raw is not None and raw not in numbering:
            numbering[raw] = len(numbering) + 1
        label = speaker_label(numbering[raw]) if raw is not None else None
        labelled.append(replace(segment, speaker=label))
    return labelled
