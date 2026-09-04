import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.core.downloader import _download_with_cobalt


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self.stream = io.BytesIO(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)


class CobaltDownloaderTests(unittest.TestCase):
    def test_downloads_tunnel_response_to_temporary_directory(self):
        api_body = json.dumps(
            {
                "status": "tunnel",
                "url": "http://127.0.0.1:9000/tunnel?id=test",
                "filename": "tiktok_creator_123.mp4",
            }
        ).encode()
        media = b"fake-video"

        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "backend.core.downloader.urlopen",
                side_effect=[
                    FakeResponse(api_body),
                    FakeResponse(media, {"Content-Length": str(len(media))}),
                ],
            ) as mocked_urlopen:
                result = _download_with_cobalt(
                    "https://www.tiktok.com/@creator/video/123",
                    Path(directory),
                    "http://127.0.0.1:9000",
                    threading.Event(),
                    None,
                )

            self.assertEqual(result.audio_path.read_bytes(), media)
            self.assertEqual(result.title, "tiktok_creator_123")
            request_payload = json.loads(mocked_urlopen.call_args_list[0].args[0].data)
            self.assertEqual(request_payload["downloadMode"], "audio")
            self.assertEqual(request_payload["audioFormat"], "best")


if __name__ == "__main__":
    unittest.main()
