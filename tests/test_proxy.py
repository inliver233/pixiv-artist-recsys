from __future__ import annotations

import unittest

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.auth.transport import HttpResponse
from pixiv_artist_recsys.proxy import FailoverHttpTransport, ProxyPolicy, ProxyPool, build_http_transport_from_env, parse_proxy_urls


class FakeBaseTransport:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls: list[str | None] = []

    def send(self, *, method, url, headers=None, data=None, params=None, timeout_s=30.0, proxy=None):
        self.calls.append(proxy)
        outcome = self.behavior.get(proxy)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, HttpResponse):
            return outcome
        return HttpResponse(status_code=200, headers={}, text='{"ok": true}')


class ProxyTransportTests(unittest.TestCase):
    def test_failover_tries_next_proxy_after_exception(self) -> None:
        pool = ProxyPool.from_urls(
            ['http://proxy-a:8080', 'http://proxy-b:8080'],
            policy=ProxyPolicy(max_consecutive_failures=1, cooldown_seconds=60),
            now_fn=lambda: 100,
        )
        base = FakeBaseTransport({
            'http://proxy-a:8080': OSError('proxy-a down'),
            'http://proxy-b:8080': HttpResponse(status_code=200, headers={}, text='{"ok": true}'),
        })
        transport = FailoverHttpTransport(base_transport=base, proxy_pool=pool)

        response = transport.send(method='GET', url='https://example.test')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(base.calls, ['http://proxy-a:8080', 'http://proxy-b:8080'])
        snapshots = {item.proxy_id: item for item in pool.snapshot()}
        self.assertFalse(snapshots['proxy-1'].healthy)
        self.assertEqual(snapshots['proxy-1'].cooldown_until_epoch, 160)
        self.assertEqual(snapshots['proxy-2'].total_successes, 1)

    def test_failover_uses_direct_fallback_after_retryable_status(self) -> None:
        pool = ProxyPool.from_urls(
            ['http://proxy-a:8080'],
            policy=ProxyPolicy(max_consecutive_failures=1, cooldown_seconds=60, allow_direct_fallback=True),
            now_fn=lambda: 100,
        )
        base = FakeBaseTransport({
            'http://proxy-a:8080': HttpResponse(status_code=503, headers={}, text='unavailable'),
            None: HttpResponse(status_code=200, headers={}, text='{"fallback": true}'),
        })
        transport = FailoverHttpTransport(base_transport=base, proxy_pool=pool)

        response = transport.send(method='GET', url='https://example.test')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(base.calls, ['http://proxy-a:8080', None])

    def test_build_http_transport_from_env_parses_proxy_urls(self) -> None:
        transport, pool = build_http_transport_from_env(
            {
                'PIXIV_ARTIST_RECSYS_PROXY_URLS': 'http://proxy-a:8080;http://proxy-b:8080',
                'PIXIV_ARTIST_RECSYS_PROXY_MAX_FAILURES': '2',
                'PIXIV_ARTIST_RECSYS_PROXY_COOLDOWN_SECONDS': '30',
            },
            base_transport=FakeBaseTransport({}),
            now_fn=lambda: 100,
        )

        self.assertIsNotNone(pool)
        self.assertEqual(parse_proxy_urls('http://proxy-a:8080;http://proxy-b:8080'), ['http://proxy-a:8080', 'http://proxy-b:8080'])
        self.assertEqual(pool.policy.max_consecutive_failures, 2)
        self.assertEqual(pool.policy.cooldown_seconds, 30)
        self.assertIsInstance(transport, FailoverHttpTransport)


if __name__ == '__main__':
    unittest.main()
