from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProxyEndpoint:
    proxy_id: str
    proxy_url: str
    label: str = ''
    weight: int = 1


@dataclass(frozen=True, slots=True)
class ProxyPolicy:
    max_consecutive_failures: int = 1
    cooldown_seconds: int = 60
    retryable_status_codes: tuple[int, ...] = (403, 429, 500, 502, 503, 504)
    allow_direct_fallback: bool = True


@dataclass(slots=True)
class ProxyState:
    endpoint: ProxyEndpoint
    total_successes: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    cooldown_until_epoch: int = 0
    last_error: str = ''


@dataclass(frozen=True, slots=True)
class ProxySnapshot:
    proxy_id: str
    proxy_url: str
    label: str
    total_successes: int
    total_failures: int
    consecutive_failures: int
    cooldown_until_epoch: int
    healthy: bool
    last_error: str
