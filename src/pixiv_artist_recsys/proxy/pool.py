from __future__ import annotations

import time
from dataclasses import replace

from .models import ProxyEndpoint, ProxyPolicy, ProxySnapshot, ProxyState


class ProxyPool:
    def __init__(
        self,
        *,
        endpoints: list[ProxyEndpoint],
        policy: ProxyPolicy | None = None,
        now_fn=None,
    ) -> None:
        self.endpoints = list(endpoints)
        self.policy = policy or ProxyPolicy()
        self.now_fn = now_fn or (lambda: int(time.time()))
        self._states = {endpoint.proxy_id: ProxyState(endpoint=endpoint) for endpoint in self.endpoints}
        self._cursor = 0

    @classmethod
    def from_urls(cls, urls: list[str], *, policy: ProxyPolicy | None = None, now_fn=None) -> 'ProxyPool':
        endpoints = [
            ProxyEndpoint(proxy_id=f'proxy-{idx}', proxy_url=url.strip(), label=f'proxy-{idx}')
            for idx, url in enumerate(urls, start=1)
            if str(url).strip()
        ]
        return cls(endpoints=endpoints, policy=policy, now_fn=now_fn)

    def has_proxies(self) -> bool:
        return bool(self.endpoints)

    def attempt_order(self) -> list[ProxyEndpoint | None]:
        healthy = self._healthy_endpoints()
        if not healthy:
            return [None] if self.policy.allow_direct_fallback else []
        start = self._cursor % len(healthy)
        ordered = healthy[start:] + healthy[:start]
        self._cursor += 1
        attempts: list[ProxyEndpoint | None] = list(ordered)
        if self.policy.allow_direct_fallback:
            attempts.append(None)
        return attempts

    def record_success(self, proxy_id: str) -> None:
        state = self._states.get(proxy_id)
        if state is None:
            return
        state.total_successes += 1
        state.consecutive_failures = 0
        state.cooldown_until_epoch = 0
        state.last_error = ''

    def record_failure(self, proxy_id: str, error: object) -> None:
        state = self._states.get(proxy_id)
        if state is None:
            return
        state.total_failures += 1
        state.consecutive_failures += 1
        state.last_error = str(error or '')[:300]
        if state.consecutive_failures >= self.policy.max_consecutive_failures:
            state.cooldown_until_epoch = self.now_fn() + self.policy.cooldown_seconds
            state.consecutive_failures = 0

    def snapshot(self) -> list[ProxySnapshot]:
        now = self.now_fn()
        return [
            ProxySnapshot(
                proxy_id=state.endpoint.proxy_id,
                proxy_url=state.endpoint.proxy_url,
                label=state.endpoint.label,
                total_successes=state.total_successes,
                total_failures=state.total_failures,
                consecutive_failures=state.consecutive_failures,
                cooldown_until_epoch=state.cooldown_until_epoch,
                healthy=state.cooldown_until_epoch <= now,
                last_error=state.last_error,
            )
            for state in self._states.values()
        ]

    def _healthy_endpoints(self) -> list[ProxyEndpoint]:
        now = self.now_fn()
        return [
            endpoint
            for endpoint in self.endpoints
            if self._states[endpoint.proxy_id].cooldown_until_epoch <= now
        ]
