"""Only the local owner may reach the API: loopback peer, loopback Host and Origin."""
from __future__ import annotations

import json
from ipaddress import ip_address
from urllib.parse import urlsplit

_PROXY_HEADERS = {b"forwarded", b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-proto", b"x-real-ip"}
_DENIED_BODY = json.dumps(
    {"detail": "VideoTranscriber solo admite acceso desde este ordenador."}
).encode()


def _loopback(value: str | None) -> bool:
    if not value:
        return False
    if value.lower().rstrip(".") == "localhost":
        return True
    try:
        address = ip_address(value)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or bool(mapped and mapped.is_loopback)


def _host_name(value: str) -> str | None:
    """Hostname of a Host header, or None when it carries anything but host[:port]."""
    try:
        parsed = urlsplit("http://" + value)
        if parsed.username is not None or parsed.password is not None:
            return None
        if parsed.path or parsed.query or parsed.fragment:
            return None
        if not parsed.hostname or parsed.port == 0:
            return None
        return parsed.hostname
    except ValueError:
        return None


def _origin_host(value: str) -> str | None:
    """Hostname of a well-formed Origin header, or None."""
    try:
        origin = urlsplit(value)
        if origin.scheme not in {"http", "https"} or origin.port == 0:
            return None
        if origin.username is not None or origin.password is not None:
            return None
        if origin.path or origin.query or origin.fragment:
            return None
        return origin.hostname
    except ValueError:
        return None


def is_local_request(scope: dict) -> bool:
    headers = scope.get("headers", [])
    hosts = [v.decode("latin1") for k, v in headers if k.lower() == b"host"]
    origins = [v.decode("latin1") for k, v in headers if k.lower() == b"origin"]
    if len(hosts) != 1 or len(origins) > 1:
        return False
    if not _loopback(_host_name(hosts[0])):
        return False
    client = scope.get("client")
    if not client or not _loopback(client[0]):
        return False
    if any(k.lower() in _PROXY_HEADERS for k, _ in headers):
        return False
    peers = [v.decode("latin1") for k, v in headers if k.lower() == b"x-local-client-address"]
    if len(peers) > 1 or (peers and not _loopback(peers[0])):
        return False
    if origins:
        return _loopback(_origin_host(origins[0]))
    # Without Origin, a browser still reveals cross-site API calls through Fetch Metadata.
    path = scope.get("path", "")
    cross_site = any(
        k.lower() == b"sec-fetch-site" and v.lower() == b"cross-site" for k, v in headers
    )
    return not (path.startswith("/api") and cross_site)


class LocalDataAccess:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not is_local_request(scope):
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")],
            })
            await send({"type": "http.response.body", "body": _DENIED_BODY})
            return

        async def private_send(message):
            if message["type"] == "http.response.start":
                response_headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"referrer-policy"
                ]
                message = {**message, "headers": [*response_headers, (b"referrer-policy", b"no-referrer")]}
            await send(message)

        await self.app(scope, receive, private_send)
