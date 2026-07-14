from __future__ import annotations

import os
from dataclasses import asdict

from ..auth.retry import RetryPolicy, RetryingHttpTransport
from ..auth.transport import HttpTransport, UrllibHttpTransport
from .models import ProxyPolicy
from .pool import ProxyPool
from .transport import FailoverHttpTransport


def parse_proxy_urls(raw: str | None) -> list[str]:
    if not raw:
        return []
    normalized = raw.replace(';', ',').replace('\n', ',')
    return [part.strip() for part in normalized.split(',') if part.strip()]


def build_proxy_pool_from_env(env: dict[str, str] | None = None, *, now_fn=None) -> ProxyPool | None:
    env = env or os.environ
    urls = parse_proxy_urls(env.get('PIXIV_ARTIST_RECSYS_PROXY_URLS'))
    if not urls:
        return None
    policy = ProxyPolicy(
        max_consecutive_failures=max(1, int(env.get('PIXIV_ARTIST_RECSYS_PROXY_MAX_FAILURES', '1'))),
        cooldown_seconds=max(1, int(env.get('PIXIV_ARTIST_RECSYS_PROXY_COOLDOWN_SECONDS', '60'))),
        allow_direct_fallback=env.get('PIXIV_ARTIST_RECSYS_PROXY_ALLOW_DIRECT', '1') not in {'0', 'false', 'False'},
    )
    return ProxyPool.from_urls(urls, policy=policy, now_fn=now_fn)


def _build_retry_policy(env: dict[str, str]) -> RetryPolicy | None:
    raw_attempts = str(env.get('PIXIV_ARTIST_RECSYS_HTTP_MAX_ATTEMPTS', '3')).strip()
    try:
        max_attempts = int(raw_attempts)
    except ValueError:
        max_attempts = 3
    if max_attempts <= 1:
        return None
    raw_delay = str(env.get('PIXIV_ARTIST_RECSYS_HTTP_RETRY_BASE_DELAY_S', '0.5')).strip()
    try:
        base_delay = float(raw_delay)
    except ValueError:
        base_delay = 0.5
    return RetryPolicy(max_attempts=max_attempts, base_delay_s=max(0.0, base_delay))


def build_http_transport_from_env(
    env: dict[str, str] | None = None,
    *,
    base_transport: HttpTransport | None = None,
    now_fn=None,
) -> tuple[HttpTransport, ProxyPool | None]:
    env = env or os.environ
    base_transport = base_transport or UrllibHttpTransport()
    retry_policy = _build_retry_policy(dict(env))
    if retry_policy is not None:
        base_transport = RetryingHttpTransport(base_transport=base_transport, policy=retry_policy)
    proxy_pool = build_proxy_pool_from_env(env, now_fn=now_fn)
    if proxy_pool is None or not proxy_pool.has_proxies():
        return base_transport, None
    return FailoverHttpTransport(base_transport=base_transport, proxy_pool=proxy_pool), proxy_pool
