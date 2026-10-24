"""Keep owner data local; public rider links retain their existing token checks."""
from __future__ import annotations

from ipaddress import ip_address
import hmac
from pathlib import Path
import json
import re
from urllib.parse import urlsplit

_PROXY_HEADERS = {b'forwarded', b'x-forwarded-for', b'x-forwarded-host', b'x-forwarded-proto', b'x-real-ip'}
_RIDER_API = re.compile(r'^/api/rider-view/[A-Za-z0-9_-]{16,64}(?:/outcome)?$')
_RIDER_PAGE = re.compile(r'^/r/[A-Za-z0-9_-]{16,64}$')


def _loopback(value: str) -> bool:
    if value.lower().rstrip('.') == 'localhost':
        return True
    try:
        address = ip_address(value)
        return address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def _authority(value: str) -> str | None:
    try:
        parsed = urlsplit('http://' + value)
        if parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment:
            return None
        if not parsed.hostname or parsed.port == 0:
            return None
        return parsed.hostname
    except ValueError:
        return None


class LocalDataAccess:
    def __init__(self, app, *, rider_views: bool = False, proxy_key_file: str | None = None):
        self.app = app
        self.rider_views = rider_views
        self.proxy_key = Path(proxy_key_file).read_bytes().strip() if proxy_key_file else b''
        if proxy_key_file and len(self.proxy_key) < 32:
            raise ValueError('The local proxy key is missing or invalid.')

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        headers = scope.get('headers', [])
        hosts = [v.decode('latin1') for k, v in headers if k.lower() == b'host']
        origins = [v.decode('latin1') for k, v in headers if k.lower() == b'origin']
        valid = len(hosts) == 1 and _authority(hosts[0]) is not None and len(origins) <= 1
        origin = None
        if origins:
            try:
                origin = urlsplit(origins[0])
                valid = valid and origin.scheme in {'http', 'https'} and origin.username is None and origin.password is None and not origin.path and not origin.query and not origin.fragment and origin.hostname is not None
                if origin.port == 0:
                    valid = False
            except ValueError:
                valid = False
        proxy_keys = [v for k, v in headers if k.lower() == b'x-local-proxy-key']
        trusted_proxy = len(proxy_keys) == 1 and bool(self.proxy_key) and hmac.compare_digest(proxy_keys[0], self.proxy_key)
        valid = valid and (not proxy_keys or trusted_proxy)
        path, method = scope.get('path', ''), scope['method']
        rider_api = self.rider_views and bool(_RIDER_API.fullmatch(path)) and method in {'GET', 'POST', 'HEAD'}
        rider_page = self.rider_views and bool(_RIDER_PAGE.fullmatch(path)) and method in {'GET', 'HEAD'}
        asset = self.rider_views and path.startswith('/assets/') and method in {'GET', 'HEAD'}
        if valid and (rider_api or rider_page):
            # Rider data remains protected by the router's scoped, expiring token.
            client = scope.get('client')
            local_origin = bool(origin and client and (_loopback(client[0]) or trusted_proxy) and _loopback(_authority(hosts[0])) and _loopback(origin.hostname))
            valid = origin is None or origin.netloc.lower() == hosts[0].lower() or local_origin
        elif valid and not asset:
            client = scope.get('client')
            valid = bool(client and (_loopback(client[0]) or trusted_proxy) and _loopback(_authority(hosts[0])))
            valid = valid and not any(k.lower() in _PROXY_HEADERS for k, _ in headers)
            original_peers = [v.decode('latin1') for k, v in headers if k.lower() == b'x-local-client-address']
            valid = valid and len(original_peers) <= 1 and (not original_peers or _loopback(original_peers[0]))
            valid = valid and (origin is None or _loopback(origin.hostname))
            if path.startswith('/api') and origin is None:
                valid = valid and not any(k.lower() == b'sec-fetch-site' and v.lower() == b'cross-site' for k, v in headers)
        if not valid:
            body = json.dumps({'detail': 'Este servicio de datos solo admite acceso local. Los enlaces de reparto requieren su autorización propia.'}).encode()
            await send({'type': 'http.response.start', 'status': 403, 'headers': [(b'content-type', b'application/json'), (b'cache-control', b'no-store')]})
            await send({'type': 'http.response.body', 'body': body})
            return

        async def private_send(message):
            if message['type'] == 'http.response.start':
                response_headers = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'referrer-policy']
                message = {**message, 'headers': response_headers + [(b'referrer-policy', b'no-referrer')]}
            await send(message)
        await self.app(scope, receive, private_send)
