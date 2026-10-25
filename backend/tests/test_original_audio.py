import logging
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import yt_dlp

from backend.core.downloader import (
    DownloadResult,
    _YT_DLP_FORMATS,
    _pick_original_audio_format,
    download_media,
)
from backend.core.errors import DownloadError, JobCancelledError, PrivateContentError

YOUTUBE_URL = "https://www.youtube.com/watch?v=pU9sHwNKc2c"
X_URL = "https://x.com/creator/status/123"
TIKTOK_URL = "https://www.tiktok.com/@creator/video/123"


def audio(
    format_id: str,
    language: str | None,
    note: str | None,
    abr: float | None,
    **extra: object,
) -> dict:
    return {
        "format_id": format_id,
        "language": language,
        "format_note": note,
        "abr": abr,
        "acodec": "opus",
        "vcodec": "none",
        **extra,
    }


def metadata(original_language: str = "es", dubbed_language: str = "en") -> dict:
    return {
        "id": "video123",
        "title": "A video",
        "language": original_language,
        "formats": [
            audio("dub-1", dubbed_language, "dubbed-auto", 192),
            audio("orig-64", original_language, "Spanish original (default), low", 60),
            audio("orig-128", original_language, "Spanish original (default), medium", 120),
            audio("orig-320", original_language, "Spanish original (default), high", 256),
        ],
    }


@pytest.mark.parametrize(
    ("profile", "expected"),
    [("compact", "orig-64"), ("balanced", "orig-128"), ("best", "orig-320")],
)
def test_original_wins_over_higher_bitrate_dub(profile, expected):
    selected, reason = _pick_original_audio_format(metadata(), profile)
    assert selected == expected
    assert "es" in reason


def test_english_original_and_regional_language_match():
    info = metadata("en-US", "es-419")
    for fmt in info["formats"][1:]:
        fmt["language"] = "en"
    assert _pick_original_audio_format(info, "best")[0] == "orig-320"
    info["language"] = "es-ES"
    for fmt in info["formats"][1:]:
        fmt["language"] = "es-419"
    assert _pick_original_audio_format(info, "compact")[0] == "orig-64"


def test_profile_falls_back_to_best_original_if_nothing_fits():
    info = metadata()
    info["formats"] = [info["formats"][0], info["formats"][2], info["formats"][3]]
    assert _pick_original_audio_format(info, "compact")[0] == "orig-320"


@pytest.mark.parametrize(
    "change",
    [
        lambda i: i.update(formats=[]),
        lambda i: i.pop("formats"),
        lambda i: i.update(formats=[i["formats"][1]]),
        lambda i: [f.update(language=None) for f in i["formats"][1:]],
        lambda i: [f.update(format_note="default") for f in i["formats"][1:]],
        lambda i: i.update(language="fr"),
        lambda i: i["formats"][2].update(language="en"),
        lambda i: i["formats"][2].update(format_note="original descriptive"),
        lambda i: i["formats"][2].update(format_id="orig-64"),
    ],
)
def test_uncertain_metadata_uses_fallback(change):
    info = metadata()
    change(info)
    selected, reason = _pick_original_audio_format(info)
    assert selected is None
    assert reason


def test_missing_bitrate_does_not_break_selection():
    info = metadata()
    info["formats"][1]["abr"] = None
    assert _pick_original_audio_format(info, "compact")[0] == "orig-320"


def test_two_original_languages_without_video_language_are_ambiguous():
    info = metadata()
    info.pop("language")
    info["formats"][0]["format_note"] = "English original"
    assert _pick_original_audio_format(info)[0] is None


class FakeYDL:
    instances = []
    info = metadata()
    error = None
    send_progress = False

    def __init__(self, opts):
        self.params = opts.copy()
        self.calls = []
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def extract_info(self, _url, download=True):
        self.calls.append(("extract", download))
        if self.error:
            raise self.error
        return self.info

    def process_ie_result(self, info, download=True):
        self.calls.append(("process", download))
        if self.error:
            raise self.error
        if self.send_progress:
            hook = self.params["progress_hooks"][0]
            hook({"status": "downloading", "total_bytes": 100, "downloaded_bytes": 50})
            hook({"status": "downloading", "total_bytes": 100, "downloaded_bytes": 75})
        return info

    def prepare_filename(self, info):
        path = Path(self.params["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", "webm"))
        path.write_bytes(b"audio")
        return str(path)


@pytest.fixture
def fake_ydl(monkeypatch):
    FakeYDL.instances = []
    FakeYDL.info = metadata()
    FakeYDL.error = None
    FakeYDL.send_progress = False
    monkeypatch.setattr("backend.core.downloader.yt_dlp.YoutubeDL", FakeYDL)
    return FakeYDL


def test_youtube_reuses_info_and_preserves_cookies(tmp_path, fake_ydl):
    cookie_file = tmp_path / "cookies.txt"
    result = download_media(YOUTUBE_URL, tmp_path, cookie_file, threading.Event())
    instance = fake_ydl.instances[0]
    assert result.audio_path.exists()
    assert instance.calls == [("extract", False), ("process", True)]
    assert instance.params["format"] == "orig-128"
    assert instance.params["cookiefile"] == str(cookie_file)


@pytest.mark.parametrize("profile", ["compact", "balanced", "best"])
def test_fallback_keeps_exact_format_selector(tmp_path, fake_ydl, profile, caplog):
    assert _YT_DLP_FORMATS == {
        "compact": "bestaudio[abr<=64]/bestaudio/best",
        "balanced": "bestaudio[abr<=128]/bestaudio/best",
        "best": "bestaudio/best",
    }
    fake_ydl.info = metadata()
    fake_ydl.info["language"] = "fr"
    with caplog.at_level(logging.WARNING):
        download_media(YOUTUBE_URL, tmp_path, None, threading.Event(), audio_quality=profile)
    assert fake_ydl.instances[0].params["format"] == _YT_DLP_FORMATS[profile]
    assert "comportamiento por defecto" in caplog.text


def test_logs_only_safe_selection_fields(tmp_path, fake_ydl, caplog):
    fake_ydl.info["formats"][1]["url"] = "https://googlevideo.com/audio?sig=SECRETO"
    fake_ydl.info["formats"][1]["http_headers"] = {"Cookie": "TOKEN"}
    with caplog.at_level(logging.INFO):
        download_media(YOUTUBE_URL, tmp_path, None, threading.Event())
    assert "language=es" in caplog.text
    assert "format_id=orig-128" in caplog.text
    assert "SECRETO" not in caplog.text
    assert "TOKEN" not in caplog.text
    assert "googlevideo.com" not in caplog.text


def test_cancellation_before_download(tmp_path, fake_ydl):
    event = threading.Event()
    event.set()
    with pytest.raises(JobCancelledError):
        download_media(YOUTUBE_URL, tmp_path, None, event)
    assert fake_ydl.instances[0].calls == [("extract", False)]


def test_progress_hook_and_cancellation_during_download(tmp_path, fake_ydl):
    fake_ydl.send_progress = True
    event = threading.Event()
    progress = []

    def on_progress(message, percent):
        progress.append((message, percent))
        event.set()

    with pytest.raises(JobCancelledError):
        download_media(YOUTUBE_URL, tmp_path, None, event, on_progress=on_progress)
    assert progress == [("Descargando audio... 50 % · audio: es (original)", 50)]
    assert fake_ydl.instances[0].calls == [("extract", False), ("process", True)]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("network failed", DownloadError),
        ("login required", PrivateContentError),
    ],
)
def test_download_errors_keep_existing_handling(tmp_path, fake_ydl, error, expected):
    fake_ydl.error = yt_dlp.utils.DownloadError(error)
    with pytest.raises(expected):
        download_media(YOUTUBE_URL, tmp_path, None, threading.Event())


def test_yt_dlp_goes_first_and_cobalt_is_only_a_fallback(tmp_path, fake_ydl):
    cobalt_result = DownloadResult(tmp_path / "cobalt.mp3", "title", None, None)
    with patch("backend.core.downloader._download_with_cobalt", return_value=cobalt_result) as cobalt:
        direct = download_media(
            TIKTOK_URL, tmp_path, None, threading.Event(), cobalt_api_url="http://127.0.0.1:9000"
        )
        assert direct.title == "A video"
        cobalt.assert_not_called()
        fake_ydl.error = yt_dlp.utils.DownloadError("network failed")
        for url, mode in ((TIKTOK_URL, "audio"), (X_URL, "auto")):
            assert download_media(
                url, tmp_path, None, threading.Event(), cobalt_api_url="http://127.0.0.1:9000"
            ) is cobalt_result
            assert cobalt.call_args.kwargs["download_mode"] == mode
        assert cobalt.call_count == 2


def test_cobalt_failure_reports_the_original_download_error(tmp_path, fake_ydl):
    fake_ydl.error = yt_dlp.utils.DownloadError("login required")
    with patch(
        "backend.core.downloader._download_with_cobalt",
        side_effect=DownloadError("Cobalt no disponible"),
    ):
        with pytest.raises(PrivateContentError):
            download_media(
                X_URL, tmp_path, None, threading.Event(), cobalt_api_url="http://127.0.0.1:9000"
            )


def test_youtube_enables_a_javascript_runtime(tmp_path, fake_ydl):
    download_media(YOUTUBE_URL, tmp_path, None, threading.Event())
    assert {"deno", "node"} <= fake_ydl.instances[0].params["js_runtimes"].keys()


@pytest.mark.skipif(not os.environ.get("VIDEO_TRANSCRIBER_LIVE_TEST"), reason="needs network")
def test_public_multitrack_video_live():
    with yt_dlp.YoutubeDL({"quiet": True, "ignoreconfig": True}) as ydl:
        info = ydl.extract_info(YOUTUBE_URL, download=False)
    assert _pick_original_audio_format(info)[0]
