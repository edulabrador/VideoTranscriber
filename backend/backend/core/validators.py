import re
from functools import lru_cache
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

# Extractors that match almost any URL. Accepting them would turn every web page
# into a "supported" source and produce confusing download errors instead.
_CATCH_ALL_EXTRACTORS = {"Generic", "GenericEmbed"}
# Playlist and channel pages expand to many videos; this app transcribes one video.
_COLLECTION_HINT = re.compile(r"(?:playlist|channel|user|album|tab|search|feed)", re.I)


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


def is_known_platform_url(source: str) -> bool:
    """YouTube, Instagram, TikTok and X, the platforms with dedicated handling."""
    value = source.strip()
    return bool(SUPPORTED_URL_PATTERN.match(value)) or is_youtube_url(value)


@lru_cache(maxsize=1)
def _site_extractors() -> tuple:
    from yt_dlp.extractor import gen_extractor_classes

    return tuple(
        extractor for extractor in gen_extractor_classes()
        if extractor.ie_key() not in _CATCH_ALL_EXTRACTORS and extractor.working()
    )


def site_extractor_name(source: str) -> str | None:
    """Name of the yt-dlp extractor for a single video on another site, if any."""
    value = source.strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    for extractor in _site_extractors():
        if extractor.suitable(value):
            key = extractor.ie_key()
            return None if _COLLECTION_HINT.search(key) else key
    return None


def is_supported_url(source: str) -> bool:
    return is_known_platform_url(source) or site_extractor_name(source) is not None


def validate_supported_url(url: str) -> None:
    if not is_supported_url(url):
        raise UnsupportedURLError(
            "El enlace no es compatible. Pega un vídeo de YouTube, Instagram, TikTok, "
            "Twitter (X) u otro sitio de vídeo admitido por yt-dlp."
        )
