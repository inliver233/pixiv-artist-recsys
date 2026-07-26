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

    def test_retries_json_body_rate_limit_on_non_429_status(self) -> None:
        # Pixiv reports "Rate Limit" in the JSON body on a 403 (not always HTTP 429).
        sleeps: list[float] = []
        rate_limit_body = '{"error":{"user_message":"","message":"Rate Limit","reason":""}}'
        base = SequenceTransport(
            [
                HttpResponse(403, {}, rate_limit_body),
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
        # Body rate limit backs off like a 429 (base * 2**attempt).
        self.assertEqual(sleeps, [0.2])

    def test_plain_403_without_rate_limit_body_not_retried(self) -> None:
        base = SequenceTransport([HttpResponse(403, {}, '{"error":{"message":"Access denied"}}')])
        transport = RetryingHttpTransport(
            base_transport=base,
            policy=RetryPolicy(max_attempts=3, base_delay_s=0.1, jitter_s=0.0),
            sleep_fn=lambda _: None,
        )
        response = transport.send(method='GET', url='https://example.test/x')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(base.calls, 1)


if __name__ == '__main__':
    unittest.main()
