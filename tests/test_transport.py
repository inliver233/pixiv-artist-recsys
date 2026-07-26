from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.auth.transport import PooledHttpTransport


class _EchoHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'  # keep-alive
    connection_count = 0
    lock = threading.Lock()

    def setup(self) -> None:  # counts distinct TCP connections
        with _EchoHandler.lock:
            _EchoHandler.connection_count += 1
        super().setup()

    def do_GET(self) -> None:
        body = json.dumps({'path': self.path}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence test output
        pass


class PooledTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        _EchoHandler.connection_count = 0
        self.server = HTTPServer(('127.0.0.1', 0), _EchoHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_reuses_connection_across_requests(self) -> None:
        transport = PooledHttpTransport()
        try:
            for i in range(5):
                response = transport.send(method='GET', url=f'{self.base_url}/req/{i}', params={'q': i})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(json.loads(response.text)['path'], f'/req/{i}?q={i}')
        finally:
            transport.close()
        self.assertEqual(_EchoHandler.connection_count, 1)

    def test_recovers_from_server_closed_connection(self) -> None:
        transport = PooledHttpTransport()
        try:
            first = transport.send(method='GET', url=f'{self.base_url}/a')
            self.assertEqual(first.status_code, 200)
            # Simulate a stale keep-alive socket: close it server-side by
            # restarting the server on the same port is racy; instead close the
            # client's pooled socket to force the reconnect path.
            for conn in transport._connections().values():
                conn.sock.close()
            second = transport.send(method='GET', url=f'{self.base_url}/b')
            self.assertEqual(second.status_code, 200)
        finally:
            transport.close()


if __name__ == '__main__':
    unittest.main()
