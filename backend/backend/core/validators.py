import re
from urllib.parse import parse_qs, urlsplit

from backend.core.errors import UnsupportedURLError

TIKTOK_URL_PATTERN = re.compile(
    r"^https?://(?:"
    r"(?:www\.|m\.)?tiktok\.com/@[^/]+/video/\d+"
    r"|(?:www\.)?(?:vm|vt)\.tiktok\.com/[A-Za-z0-9_-]+"
    r")/?(?:\?.*)?$"
)

X_URL_PATTERN = re.compile(
    r"^https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/"
    r"[^/]+/status/\d+(?:/(?:video|photo)/\d+|/[Mm]edia[Vv]iewer)?/?(?:\?.*)?$"
)

SUPPORTED_URL_PATTERN = re.compile(
    r"^https?://(?:"
    r"(?:www\.|m\.)?instagram\.com/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+"
    r"|(?:www\.|m\.)?tiktok\.com/@[^/]+/video/\d+"
    r"|(?:www\.)?(?:vm|vt)\.tiktok\.com/[A-Za-z0-9_-]+"
    r"|(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/"
    r"[^/]+/status/\d+(?:/(?:video|photo)/\d+|/[Mm]edia[Vv]iewer)?"
    r")/?(?:\?.*)?$"
)


def is_instagram_url(source: str) -> bool:
    value = source.strip()
    return bool(SUPPORTED_URL_PATTERN.match(value)) or is_youtube_url(value)


def is_youtube_url(source: str) -> bool:
    try:
        parsed = urlsplit(source.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False

    host = (parsed.hostname or "").lower()
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path.rstrip("/") == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
                video_id = parts[1]
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", video_id))


def is_tiktok_url(source: str) -> bool:
    return bool(TIKTOK_URL_PATTERN.match(source.strip()))


def is_x_url(source: str) -> bool:
    return bool(X_URL_PATTERN.match(source.strip()))


def is_cobalt_url(source: str) -> bool:
    value = source.strip()
    return bool(TIKTOK_URL_PATTERN.match(value) or X_URL_PATTERN.match(value))


def validate_instagram_url(url: str) -> None:
    if not is_instagram_url(url):
        raise UnsupportedURLError(
            "El enlace no es válido. Pega un vídeo de YouTube, Instagram, TikTok o Twitter (X)."
        )
