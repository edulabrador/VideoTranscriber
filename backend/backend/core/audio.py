import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from backend.config import REPO_ROOT
from backend.core.errors import AudioExtractionError, JobCancelledError


def find_ffmpeg() -> str | None:
    if ffmpeg := shutil.which("ffmpeg"):
        return ffmpeg
    matches = list(
        (REPO_ROOT / "services" / "cobalt" / "node_modules" / ".pnpm").glob(
            "ffmpeg-static@*/node_modules/ffmpeg-static/ffmpeg.exe"
        )
    )
    return str(matches[0]) if matches else None


def check_ffmpeg_available() -> bool:
    return find_ffmpeg() is not None


def normalize_to_wav16k_mono(
    input_path: Path, output_path: Path,
    cancel_event: threading.Event | None = None, *, timeout: float = 600,
) -> Path:
    return _convert(
        input_path, output_path, ["-ac", "1", "-ar", "16000", "-vn"], cancel_event,
        timeout=timeout, missing="No se encontró FFmpeg para preparar el archivo subido",
    )


def make_listening_copy(
    input_path: Path, output_path: Path,
    cancel_event: threading.Event | None = None, *, timeout: float = 600,
) -> Path:
    """Small mono AAC file (about 20 MB per hour) for playback next to the transcript."""
    return _convert(
        input_path, output_path,
        ["-vn", "-ac", "1", "-ar", "22050", "-c:a", "aac", "-b:a", "40k",
         "-movflags", "+faststart"],
        cancel_event, timeout=timeout, missing="No se encontró FFmpeg para guardar el audio",
    )


def _convert(
    input_path: Path, output_path: Path, output_args: list[str],
    cancel_event: threading.Event | None, *, timeout: float, missing: str,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise AudioExtractionError(missing)
    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelledError()
    # A file, rather than an undrained PIPE, prevents stderr from blocking FFmpeg.
    with tempfile.TemporaryFile() as errors, subprocess.Popen(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i",
         str(input_path), *output_args, str(output_path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        deadline = time.monotonic() + timeout
        succeeded = False
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise JobCancelledError()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AudioExtractionError("La preparación del audio superó el tiempo máximo")
                try:
                    process.wait(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if cancel_event is not None and cancel_event.is_set():
                raise JobCancelledError()
            if process.returncode != 0 or not output_path.exists():
                errors.seek(max(0, errors.seek(0, 2) - 2000))
                detail = errors.read().decode("utf-8", errors="replace").strip()[-500:]
                raise AudioExtractionError(f"No se pudo preparar el audio: {detail}")
            succeeded = True
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if not succeeded:
                output_path.unlink(missing_ok=True)
    return output_path
