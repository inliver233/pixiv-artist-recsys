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

            def do_GET(self) -> None:  # noqa: N802
                self._handle('GET')

            def do_POST(self) -> None:  # noqa: N802
                self._handle('POST')

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

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
