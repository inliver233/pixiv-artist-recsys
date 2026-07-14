from __future__ import annotations

import os
from dataclasses import asdict

from ..auth.retry import RetryPolicy, RetryingHttpTransport
from ..auth.transport import HttpTransport, UrllibHttpTransport
from ..utils.pacing import PacingHttpTransport, RequestPacePolicy, RequestPacer
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


def _env_float(env: dict[str, str], key: str, default: float) -> float:
    raw = str(env.get(key, '') or '').strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(env: dict[str, str], key: str, default: int) -> int:
    raw = str(env.get(key, '') or '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _build_retry_policy(env: dict[str, str]) -> RetryPolicy | None:
    # Single child token: prefer slightly more attempts + longer base delay than aggressive parallel.
    max_attempts = _env_int(env, 'PIXIV_ARTIST_RECSYS_HTTP_MAX_ATTEMPTS', 4)
    if max_attempts <= 1:
        return None
    base_delay = max(0.0, _env_float(env, 'PIXIV_ARTIST_RECSYS_HTTP_RETRY_BASE_DELAY_S', 0.8))
    max_delay = max(base_delay, _env_float(env, 'PIXIV_ARTIST_RECSYS_HTTP_RETRY_MAX_DELAY_S', 20.0))
    jitter = max(0.0, _env_float(env, 'PIXIV_ARTIST_RECSYS_HTTP_RETRY_JITTER_S', 0.35))
    return RetryPolicy(
        max_attempts=max_attempts,
        base_delay_s=base_delay,
        max_delay_s=max_delay,
        jitter_s=jitter,
    )


def _build_pace_policy(env: dict[str, str]) -> RequestPacePolicy | None:
    """Steady request spacing for one child token.

    Default ~0.12s + small jitter (~7–8 req/s peak, usually lower with API latency).
    Disable with PIXIV_ARTIST_RECSYS_HTTP_MIN_INTERVAL_S=0.
    """
    if str(env.get('PIXIV_ARTIST_RECSYS_HTTP_PACE_ENABLED', '1')).strip().lower() in {'0', 'false', 'no', 'off'}:
        return None
    min_interval = max(0.0, _env_float(env, 'PIXIV_ARTIST_RECSYS_HTTP_MIN_INTERVAL_S', 0.12))
    if min_interval <= 0:
        return None
    jitter = max(0.0, _env_float(env, 'PIXIV_ARTIST_RECSYS_HTTP_PACE_JITTER_S', 0.04))
    return RequestPacePolicy(min_interval_s=min_interval, jitter_s=jitter, enabled=True)


def build_http_transport_from_env(
    env: dict[str, str] | None = None,
    *,
    base_transport: HttpTransport | None = None,
    now_fn=None,
) -> tuple[HttpTransport, ProxyPool | None]:
    env = env or os.environ
    base_transport = base_transport or UrllibHttpTransport()
    # Order: base -> retry -> pace -> (optional) proxy failover
    # Pace outermost of retry so each attempt is also spaced (safer on 429 storms).
    retry_policy = _build_retry_policy(dict(env))
    if retry_policy is not None:
        base_transport = RetryingHttpTransport(base_transport=base_transport, policy=retry_policy)
    pace_policy = _build_pace_policy(dict(env))
    if pace_policy is not None:
        base_transport = PacingHttpTransport(base_transport=base_transport, pacer=RequestPacer(policy=pace_policy))
    proxy_pool = build_proxy_pool_from_env(env, now_fn=now_fn)
    if proxy_pool is None or not proxy_pool.has_proxies():
        return base_transport, None
    return FailoverHttpTransport(base_transport=base_transport, proxy_pool=proxy_pool), proxy_pool
