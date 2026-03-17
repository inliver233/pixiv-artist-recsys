from __future__ import annotations

import os
from dataclasses import asdict

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


def build_http_transport_from_env(
    env: dict[str, str] | None = None,
    *,
    base_transport: HttpTransport | None = None,
    now_fn=None,
) -> tuple[HttpTransport, ProxyPool | None]:
    base_transport = base_transport or UrllibHttpTransport()
    proxy_pool = build_proxy_pool_from_env(env, now_fn=now_fn)
    if proxy_pool is None or not proxy_pool.has_proxies():
        return base_transport, None
    return FailoverHttpTransport(base_transport=base_transport, proxy_pool=proxy_pool), proxy_pool
