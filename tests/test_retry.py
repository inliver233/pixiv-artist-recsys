from __future__ import annotations

import unittest

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.auth import HttpResponse, RetryPolicy, RetryingHttpTransport


class SequenceTransport:
    def __init__(self, responses: list[HttpResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def send(self, **kwargs):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RetryTransportTests(unittest.TestCase):
    def test_retries_retryable_status_then_succeeds(self) -> None:
        sleeps: list[float] = []
        base = SequenceTransport(
            [
                HttpResponse(429, {}, '{"error":"rate"}'),
                HttpResponse(200, {}, '{"ok":true}'),
            ]
        )
        transport = RetryingHttpTransport(
            base_transport=base,
            policy=RetryPolicy(max_attempts=3, base_delay_s=0.1, max_delay_s=1.0, jitter_s=0.0),
            sleep_fn=sleeps.append,
            random_fn=lambda _a, _b: 0.0,
        )
        response = transport.send(method='GET', url='https://example.test/x')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(base.calls, 2)
        # 429 without Retry-After uses stronger backoff: base * 2**attempt (attempt=1 -> 0.2)
        self.assertEqual(sleeps, [0.2])

    def test_respects_retry_after_header(self) -> None:
        sleeps: list[float] = []
        base = SequenceTransport(
            [
                HttpResponse(429, {'Retry-After': '1.5'}, '{"error":"rate"}'),
                HttpResponse(200, {}, '{"ok":true}'),
            ]
        )
        transport = RetryingHttpTransport(
            base_transport=base,
            policy=RetryPolicy(max_attempts=3, base_delay_s=0.1, max_delay_s=10.0, jitter_s=0.0),
            sleep_fn=sleeps.append,
            random_fn=lambda _a, _b: 0.0,
        )
        response = transport.send(method='GET', url='https://example.test/x')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sleeps, [1.5])

    def test_does_not_retry_client_errors(self) -> None:
        base = SequenceTransport([HttpResponse(401, {}, '{"error":"auth"}')])
        transport = RetryingHttpTransport(
            base_transport=base,
            policy=RetryPolicy(max_attempts=4, base_delay_s=0.5, jitter_s=0.0),
            sleep_fn=lambda _: None,
        )
        response = transport.send(method='GET', url='https://example.test/x')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(base.calls, 1)


if __name__ == '__main__':
    unittest.main()
