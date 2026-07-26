from __future__ import annotations

import http.client
import json
import threading
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib import error, parse, request


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    text: str

    def json(self) -> object:
        return json.loads(self.text)


class HttpTransport(Protocol):
    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
        timeout_s: float = 30.0,
        proxy: str | None = None,
    ) -> HttpResponse: ...


class UrllibHttpTransport:
    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
        timeout_s: float = 30.0,
        proxy: str | None = None,
    ) -> HttpResponse:
        final_url = url
        if params:
            # doseq: list/tuple values become repeated keys (Pixiv array params like seed_illust_ids[]).
            query = parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
            separator = '&' if '?' in final_url else '?'
            final_url = f"{final_url}{separator}{query}"

        body = None
        if data:
            body = parse.urlencode(data).encode('utf-8')

        req = request.Request(final_url, data=body, method=method.upper())
        for key, value in (headers or {}).items():
            req.add_header(key, value)

        opener = request.build_opener(request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout_s) as resp:
                text = resp.read().decode('utf-8')
                return HttpResponse(status_code=int(resp.getcode()), headers=dict(resp.headers.items()), text=text)
        except error.HTTPError as exc:
            text = exc.read().decode('utf-8', errors='replace') if exc.fp is not None else ''
            return HttpResponse(status_code=int(exc.code), headers=dict(exc.headers.items()), text=text)


class PooledHttpTransport:
    """Keep-alive transport on http.client with per-(host, proxy) connection reuse.

    urllib builds a fresh opener per request → full TCP+TLS handshake every
    time (0.3–0.8s wasted per request through a proxy). This transport keeps
    one connection per (scheme, host, proxy) per thread and retries once on a
    stale keep-alive socket. HTTPS through an HTTP proxy uses a CONNECT tunnel.
    """

    _RECONNECT_ERRORS = (
        http.client.RemoteDisconnected,
        http.client.BadStatusLine,
        http.client.CannotSendRequest,
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
    )

    def __init__(self) -> None:
        self._local = threading.local()

    def _connections(self) -> dict[tuple[str, str, str], http.client.HTTPConnection]:
        conns = getattr(self._local, 'conns', None)
        if conns is None:
            conns = {}
            self._local.conns = conns
        return conns

    def close(self) -> None:
        conns = getattr(self._local, 'conns', None) or {}
        for conn in conns.values():
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        self._local.conns = {}

    def _open_connection(
        self, *, scheme: str, host: str, port: int, proxy: str | None, timeout_s: float
    ) -> http.client.HTTPConnection:
        if proxy:
            proxy_parts = parse.urlsplit(proxy if '//' in proxy else f'http://{proxy}')
            proxy_host = proxy_parts.hostname or ''
            proxy_port = proxy_parts.port or (443 if proxy_parts.scheme == 'https' else 80)
            if scheme == 'https':
                conn = http.client.HTTPSConnection(proxy_host, proxy_port, timeout=timeout_s)
                conn.set_tunnel(host, port)
            else:
                conn = http.client.HTTPConnection(proxy_host, proxy_port, timeout=timeout_s)
            return conn
        if scheme == 'https':
            return http.client.HTTPSConnection(host, port, timeout=timeout_s)
        return http.client.HTTPConnection(host, port, timeout=timeout_s)

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
        timeout_s: float = 30.0,
        proxy: str | None = None,
    ) -> HttpResponse:
        split = parse.urlsplit(url)
        scheme = split.scheme or 'https'
        host = split.hostname or ''
        port = split.port or (443 if scheme == 'https' else 80)

        path = split.path or '/'
        query_parts = [split.query] if split.query else []
        if params:
            query_parts.append(
                parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
            )
        if query_parts:
            path = f"{path}?{'&'.join(query_parts)}"

        body = parse.urlencode(data).encode('utf-8') if data else None
        send_headers = dict(headers or {})
        if body is not None and not any(k.lower() == 'content-type' for k in send_headers):
            send_headers['Content-Type'] = 'application/x-www-form-urlencoded'

        key = (scheme, f'{host}:{port}', proxy or '')
        conns = self._connections()
        for attempt in (1, 2):
            conn = conns.get(key)
            if conn is not None:
                sock = getattr(conn, 'sock', None)
                if sock is not None and sock.fileno() == -1:
                    # Pooled socket already closed → rebuild before use.
                    conns.pop(key, None)
                    conn = None
            if conn is None:
                conn = self._open_connection(scheme=scheme, host=host, port=port, proxy=proxy, timeout_s=timeout_s)
                conns[key] = conn
            conn.timeout = timeout_s
            try:
                if getattr(conn, 'sock', None) is not None:
                    conn.sock.settimeout(timeout_s)
                conn.request(method.upper(), path, body=body, headers=send_headers)
                resp = conn.getresponse()
                text = resp.read().decode('utf-8', errors='replace')
                return HttpResponse(
                    status_code=int(resp.status),
                    headers=dict(resp.getheaders()),
                    text=text,
                )
            except self._RECONNECT_ERRORS:
                # Server closed the keep-alive socket; rebuild once, then propagate.
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                conns.pop(key, None)
                if attempt == 2:
                    raise
            except Exception:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                conns.pop(key, None)
                raise
        raise RuntimeError('unreachable')
