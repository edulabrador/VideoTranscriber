"""Refuse oversized uploads before their body is read.

Starlette stores the whole multipart body in a temporary file before the route runs,
so a size check inside the route only happens after the disk has been filled.
"""
from __future__ import annotations

import json

from backend.config import settings

UPLOAD_PATH = "/api/jobs/upload"
# Room for the multipart boundaries and the small form fields next to the file.
_FORM_OVERHEAD_BYTES = 1024 * 1024
_TOO_LARGE_BODY = json.dumps({"detail": "El archivo supera el tamaño permitido"}).encode()


def declared_length(scope: dict) -> int | None:
    values = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
    if len(values) != 1:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


class UploadSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == UPLOAD_PATH:
            length = declared_length(scope)
            if length is not None and length > settings.max_upload_bytes + _FORM_OVERHEAD_BYTES:
                await send({
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"connection", b"close"),
                    ],
                })
                await send({"type": "http.response.body", "body": _TOO_LARGE_BODY})
                return
        await self.app(scope, receive, send)
