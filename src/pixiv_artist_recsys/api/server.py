from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..runtime import AppRuntime
from .router import ApiRequest, ApiRouter


class ApiServer:
    def __init__(
        self,
        *,
        runtime: AppRuntime,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self.runtime = runtime
        self.host = host or runtime.settings.api.host
        self.port = runtime.settings.api.port if port is None else port

    def create_handler_class(self):
        router = ApiRouter(runtime=self.runtime)

        class Handler(BaseHTTPRequestHandler):
            server_version = 'PixivArtistRecSysAPI/0.1'

            # Local consumers only: the file:// HTML report (Origin: null) and
            # localhost pages. Anything else gets no CORS grant.
            _ALLOWED_ORIGINS = {'null'}
            _ALLOWED_ORIGIN_PREFIXES = ('http://127.0.0.1', 'http://localhost')

            def do_GET(self) -> None:  # noqa: N802
                self._handle('GET')

            def do_POST(self) -> None:  # noqa: N802
                self._handle('POST')

            def do_OPTIONS(self) -> None:  # noqa: N802 - CORS preflight for the HTML report
                self.send_response(204)
                self._send_cors_headers()
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

            def _cors_origin(self) -> str | None:
                origin = str(self.headers.get('Origin', '') or '')
                if not origin:
                    return None
                if origin in self._ALLOWED_ORIGINS or origin.startswith(self._ALLOWED_ORIGIN_PREFIXES):
                    return origin
                return None

            def _send_cors_headers(self) -> None:
                origin = self._cors_origin()
                if origin is None:
                    return
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.send_header('Vary', 'Origin')

            def _handle(self, method: str) -> None:
                content_length = int(self.headers.get('Content-Length', '0') or 0)
                body = self.rfile.read(content_length) if content_length > 0 else b''
                response = router.handle(
                    ApiRequest.from_target(
                        method=method,
                        target=self.path,
                        body=body,
                        headers={key: value for key, value in self.headers.items()},
                    )
                )
                payload_bytes = json.dumps(response.payload, ensure_ascii=False, indent=2).encode('utf-8')
                self.send_response(response.status_code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(payload_bytes)))
                self._send_cors_headers()
                for key, value in response.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload_bytes)

        return Handler

    def create_http_server(self) -> ThreadingHTTPServer:
        self.runtime.prepare()
        server = ThreadingHTTPServer((self.host, self.port), self.create_handler_class())
        server.daemon_threads = True
        return server

    def serve_forever(self) -> None:
        httpd = self.create_http_server()
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()


def serve_api(*, runtime: AppRuntime, host: str | None = None, port: int | None = None) -> None:
    ApiServer(runtime=runtime, host=host, port=port).serve_forever()
