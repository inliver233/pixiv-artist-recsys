from __future__ import annotations

import unittest

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.auth import HttpResponse
from pixiv_artist_recsys.utils.pacing import PacingHttpTransport, RequestPacePolicy, RequestPacer
import random

from pixiv_artist_recsys.utils.sampling import hash_sample_ids, random_sample_ids, sample_ids


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, float(seconds))


class FakeTransport:
    def __init__(self) -> None:
        self.calls = 0

    def send(self, **kwargs):
        self.calls += 1
        return HttpResponse(200, {}, '{"ok":true}')


class PacingTests(unittest.TestCase):
    def test_pacer_spaces_requests(self) -> None:
        clock = Clock()
        pacer = RequestPacer(
            policy=RequestPacePolicy(min_interval_s=0.2, jitter_s=0.0, enabled=True),
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            random_fn=lambda _a, _b: 0.0,
        )
        pacer.wait()
        first_next = pacer._next_allowed_at
        self.assertGreaterEqual(first_next, 0.2)
        pacer.wait()
        self.assertGreaterEqual(clock.now, 0.2)

    def test_pacing_transport_calls_base(self) -> None:
        clock = Clock()
        base = FakeTransport()
        transport = PacingHttpTransport(
            base_transport=base,
            pacer=RequestPacer(
                policy=RequestPacePolicy(min_interval_s=0.1, jitter_s=0.0),
                sleep_fn=clock.sleep,
                monotonic_fn=clock.monotonic,
                random_fn=lambda _a, _b: 0.0,
            ),
        )
        response = transport.send(method='GET', url='https://example.test/x')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(base.calls, 1)

    def test_hash_sample_is_deterministic_and_capped(self) -> None:
        pool = list(range(1, 101))
        a = hash_sample_ids(pool, seed_user_id=7, limit=10)
        b = hash_sample_ids(pool, seed_user_id=7, limit=10)
        c = hash_sample_ids(pool, seed_user_id=8, limit=10)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 10)
        self.assertNotEqual(a, c)

    def test_random_sample_varies_across_rng(self) -> None:
        pool = list(range(1, 201))
        a = random_sample_ids(pool, limit=20, rng=random.Random(1))
        b = random_sample_ids(pool, limit=20, rng=random.Random(2))
        c = sample_ids(pool, limit=20, mode='random', rng=random.Random(1))
        self.assertEqual(len(a), 20)
        self.assertEqual(len(b), 20)
        self.assertNotEqual(a, b)
        self.assertEqual(a, c)
        self.assertEqual(sample_ids(pool, limit=5, mode='first'), [1, 2, 3, 4, 5])


if __name__ == '__main__':
    unittest.main()
