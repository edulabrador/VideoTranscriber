import re

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
    return bool(SUPPORTED_URL_PATTERN.match(source.strip()))


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
            "El enlace no es válido. Pega un vídeo de Instagram, TikTok o Twitter (X)."
        )
