import json
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yt_dlp

from backend.core import validators
from backend.core.errors import DownloadError, JobCancelledError, PrivateContentError

_PRIVATE_SIGNALS = ("login", "private", "rate-limit", "rate limit", "restricted")
_LOGGER = logging.getLogger(__name__)
_SAFE_FORMAT_ID = re.compile(r"[A-Za-z0-9_.-]+\Z")
_SAFE_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*\Z")
_NON_ORIGINAL_NOTE = re.compile(r"\b(?:dubbed|dub|descriptive|description|audiodescription)\b", re.I)
AudioQuality = Literal["compact", "balanced", "best"]
_AUDIO_BITRATES = {"compact": "64", "balanced": "128", "best": "320"}
_AUDIO_LIMITS = {"compact": 64, "balanced": 128}
# Every selector ends in "best" so sites that only serve combined audio and video
# (some Instagram posts, for example) still download instead of failing.
_YT_DLP_FORMATS = {
    "compact": "bestaudio[abr<=64]/bestaudio/best",
    "balanced": "bestaudio[abr<=128]/bestaudio/best",
    "best": "bestaudio/best",
}
# YouTube needs a JavaScript runtime to unlock its full format list. Deno is
# yt-dlp's default; Node is already a requirement of this project, so enable both.
_JS_RUNTIMES: dict[str, dict] = {"deno": {}, "node": {}}


@dataclass
class DownloadResult:
    audio_path: Path
    title: str
    uploader: str | None
    source_duration: float | None
    audio_language: str | None = None
    audio_format_id: str | None = None
    audio_selection: Literal["original", "default"] = "default"


class _CancelledSentinel(Exception):
    """Raised inside yt-dlp's progress hook to unwind out of its download loop."""


def _language_base(value: object) -> str | None:
    if not isinstance(value, str) or not _SAFE_LANGUAGE.fullmatch(value):
        return None
    return value.split("-", 1)[0].lower()


def _safe_format_id(value: object) -> str | None:
    return value if isinstance(value, str) and _SAFE_FORMAT_ID.fullmatch(value) else None


def _pick_original_audio_format(
    info: dict, audio_quality: AudioQuality = "balanced"
) -> tuple[str | None, str]:
    """Choose a marked original audio format, or explain why the normal selector is safer."""
    formats = info.get("formats")
    if not isinstance(formats, list):
        return None, "sin lista de formatos"
    audio = [
        fmt for fmt in formats
        if isinstance(fmt, dict) and fmt.get("vcodec") == "none"
        and fmt.get("acodec") not in (None, "none")
    ]
    if len(audio) < 2:
        return None, "sin varias pistas de audio"
    marked = [
        fmt for fmt in audio
        if re.search(r"\boriginal\b", str(fmt.get("format_note") or ""), re.I)
    ]
    if not marked:
        return None, "ninguna pista marcada como original"
    if any(_NON_ORIGINAL_NOTE.search(str(fmt.get("format_note") or "")) for fmt in marked):
        return None, "marca original contradictoria con descripción o doblaje"
    languages = {_language_base(fmt.get("language")) for fmt in marked}
    if None in languages or len(languages) != 1:
        return None, "idioma original ausente o contradictorio"
    original_language = next(iter(languages))
    video_language = _language_base(info.get("language"))
    if video_language and video_language != original_language:
        return None, "idioma del vídeo contradice la pista original"
    if any(_safe_format_id(fmt.get("format_id")) is None for fmt in marked):
        return None, "identificador de formato ausente o no válido"

    if any(sum(fmt.get("format_id") == item.get("format_id") for item in audio) != 1 for fmt in marked):
        return None, "identificador de formato ambiguo"

    limit = _AUDIO_LIMITS.get(audio_quality)
    within_limit = (
        [
            fmt for fmt in marked
            if isinstance(fmt.get("abr"), (int, float)) and fmt["abr"] <= limit
        ]
        if limit is not None else []
    )
    selected = (within_limit or marked)[-1]  # yt-dlp orders processed formats worst to best.
    return selected["format_id"], f"pista original identificada ({original_language})"


def download_media(
    url: str,
    dest_dir: Path,
    cookies_file: Path | None,
    cancel_event: threading.Event,
    on_progress: Callable[[str, int | None], None] | None = None,
    cobalt_api_url: str | None = None,
    audio_quality: AudioQuality = "balanced",
) -> DownloadResult:
    dest_dir.mkdir(parents=True, exist_ok=True)

    audio_language = None
    audio_format_id = None
    audio_selection: Literal["original", "default"] = "default"
    audio_status = ""

    def progress_hook(d: dict) -> None:
        if cancel_event.is_set():
            raise _CancelledSentinel()
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            percent = round(d.get("downloaded_bytes", 0) * 100 / total) if total else None
            suffix = f" {percent} %" if percent is not None else ""
            on_progress(f"Descargando audio...{suffix}{audio_status}", percent)

    ydl_opts = {
        "format": _YT_DLP_FORMATS[audio_quality],
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "progress_hooks": [progress_hook],
        "concurrent_fragment_downloads": 4,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreconfig": True,
        "js_runtimes": _JS_RUNTIMES,
    }
    if cookies_file is not None:
        ydl_opts["cookiefile"] = str(cookies_file)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if validators.is_youtube_url(url):
                info = ydl.extract_info(url, download=False)
                if cancel_event.is_set():
                    raise _CancelledSentinel()
                format_id, reason = _pick_original_audio_format(info, audio_quality)
                if format_id:
                    ydl.params["format"] = format_id
                    selected = next(
                        fmt for fmt in info["formats"]
                        if isinstance(fmt, dict) and fmt.get("format_id") == format_id
                    )
                    audio_language = _language_base(selected.get("language"))
                    audio_format_id = format_id
                    audio_selection = "original"
                    _LOGGER.info(
                        "Audio original: language=%s format_id=%s reason=%s profile=%s",
                        _language_base(selected.get("language")), format_id, reason, audio_quality,
                    )
                audio_status = (
                    f" · audio: {audio_language} (original)"
                    if format_id else " · audio: pista por defecto, no identificada"
                )
                info = ydl.process_ie_result(info, download=True)
                if not format_id:
                    _LOGGER.warning(
                        "No se pudo identificar el audio original, se usa el comportamiento "
                        "por defecto: language=%s format_id=%s reason=%s profile=%s",
                        _language_base(info.get("language")) or "unknown",
                        _safe_format_id(info.get("format_id")) or "unknown",
                        reason, audio_quality,
                    )
            else:
                info = ydl.extract_info(url, download=True)
            audio_path = Path(ydl.prepare_filename(info))
    except _CancelledSentinel as exc:
        raise JobCancelledError() from exc
    except yt_dlp.utils.DownloadError as exc:
        if validators.is_cobalt_url(url) and cobalt_api_url:
            # yt-dlp goes first; the optional local Cobalt service is only a fallback.
            _LOGGER.info("yt-dlp no pudo descargar %s, se prueba con Cobalt: %s", url, exc)
            try:
                return _download_with_cobalt(
                    url,
                    dest_dir,
                    cobalt_api_url,
                    cancel_event,
                    on_progress,
                    audio_quality,
                    download_mode="audio" if validators.is_tiktok_url(url) else "auto",
                )
            except DownloadError as cobalt_exc:
                _LOGGER.warning("Cobalt tampoco pudo descargar %s: %s", url, cobalt_exc.message)
        message = str(exc)
        lowered = message.lower()
        if any(signal in lowered for signal in _PRIVATE_SIGNALS):
            raise PrivateContentError(
                "Este contenido requiere iniciar sesión. Exporta un archivo cookies.txt "
                "desde el navegador, configura COOKIES_FILE y vuelve a intentarlo."
            ) from exc
        raise DownloadError(f"No se pudo descargar el contenido: {message}") from exc

    if not audio_path.exists():
        candidates = list(dest_dir.glob(f"{info['id']}.*"))
        if not candidates:
            raise DownloadError("La descarga terminó, pero no se generó ningún archivo multimedia")
        audio_path = candidates[0]

    return DownloadResult(
        audio_path=audio_path,
        title=info.get("title") or info.get("id"),
        uploader=info.get("uploader"),
        source_duration=info.get("duration"),
        audio_language=audio_language,
        audio_format_id=audio_format_id,
        audio_selection=audio_selection,
    )


def _download_with_cobalt(
    url: str,
    dest_dir: Path,
    api_url: str,
    cancel_event: threading.Event,
    on_progress: Callable[[str, int | None], None] | None,
    audio_quality: AudioQuality = "balanced",
    download_mode: str = "audio",
) -> DownloadResult:
    endpoint = f"{api_url.rstrip('/')}/"
    request = Request(
        endpoint,
        data=json.dumps(
            {
                "url": url,
                "alwaysProxy": True,
                "downloadMode": download_mode,
                "audioFormat": "best",
                "audioBitrate": _AUDIO_BITRATES[audio_quality],
                "localProcessing": "disabled",
            }
        ).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise DownloadError(
            "No se pudo conectar con el descargador local Cobalt. Inicia el proyecto con "
            "'pnpm dev' y vuelve a intentarlo."
        ) from exc

    status = result.get("status")
    filename = result.get("filename") or "social-video.mp4"
    media_url = result.get("url")

    if status == "picker":
        video = next(
            (item for item in result.get("picker", []) if item.get("type") == "video"),
            None,
        )
        media_url = video.get("url") if video else result.get("audio")
        filename = result.get("audioFilename") or filename
    elif status == "error":
        error = result.get("error", {})
        code = error.get("code", "error desconocido")
        raise DownloadError(f"Cobalt no pudo descargar este vídeo: {code}")
    elif status not in {"tunnel", "redirect"}:
        raise DownloadError(f"Cobalt devolvió una respuesta no compatible: {status or 'vacía'}")

    parsed_media_url = urlparse(media_url or "")
    if parsed_media_url.scheme not in {"http", "https"}:
        raise DownloadError("Cobalt no devolvió un enlace de descarga válido")

    suffix = Path(filename).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
        suffix = ".media"
    media_path = dest_dir / f"cobalt{suffix}"

    try:
        with urlopen(media_url, timeout=60) as response, media_path.open("wb") as output:
            total_header = response.headers.get("Content-Length")
            total = int(total_header) if total_header and total_header.isdigit() else 0
            downloaded = 0

            while chunk := response.read(1024 * 1024):
                if cancel_event.is_set():
                    raise JobCancelledError()
                output.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    if total:
                        percent = round(downloaded * 100 / total)
                        on_progress(f"Descargando audio... {percent} %", percent)
                    else:
                        on_progress("Descargando audio...", None)
    except JobCancelledError:
        media_path.unlink(missing_ok=True)
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        media_path.unlink(missing_ok=True)
        raise DownloadError(
            f"Cobalt encontró el vídeo, pero falló la descarga: {exc}"
        ) from exc

    if media_path.stat().st_size == 0:
        media_path.unlink(missing_ok=True)
        if download_mode == "audio":
            return _download_with_cobalt(
                url,
                dest_dir,
                api_url,
                cancel_event,
                on_progress,
                audio_quality,
                download_mode="auto",
            )
        raise DownloadError("Cobalt devolvió un archivo vacío")

    return DownloadResult(
        audio_path=media_path,
        title=Path(filename).stem,
        uploader=None,
        source_duration=None,
    )
