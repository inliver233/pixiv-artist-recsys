from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class RequestPacePolicy:
    """Serialize and space out outbound HTTP calls for a single child token.

    True multi-thread concurrency on one Pixiv account tends to raise 429 risk.
    Prefer higher sampling depth + steady pacing over parallel fan-out.
    """

    min_interval_s: float = 0.12
    jitter_s: float = 0.04
    enabled: bool = True


class RequestPacer:
    def __init__(
        self,
        *,
        policy: RequestPacePolicy | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        monotonic_fn: Callable[[], float] | None = None,
        random_fn: Callable[[float, float], float] | None = None,
    ) -> None:
        self.policy = policy or RequestPacePolicy()
        self.sleep_fn = sleep_fn or time.sleep
        self.monotonic_fn = monotonic_fn or time.monotonic
        self.random_fn = random_fn or random.uniform
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0

    def wait(self) -> None:
        policy = self.policy
        if not policy.enabled or policy.min_interval_s <= 0:
            return
        with self._lock:
            now = self.monotonic_fn()
            wait_s = self._next_allowed_at - now
            if wait_s > 0:
                self.sleep_fn(wait_s)
                now = self.monotonic_fn()
            jitter = 0.0
            if policy.jitter_s > 0:
                jitter = max(0.0, float(self.random_fn(0.0, policy.jitter_s)))
            self._next_allowed_at = now + max(0.0, float(policy.min_interval_s)) + jitter


class PacingHttpTransport:
    """Wrap any HttpTransport with outbound request pacing."""

    def __init__(self, *, base_transport, pacer: RequestPacer) -> None:
        self.base_transport = base_transport
        self.pacer = pacer

    def send(
        self,
        *,
        method: str,
        url: str,
        headers=None,
        data=None,
        params=None,
        timeout_s: float = 30.0,
        proxy: str | None = None,
    ):
        self.pacer.wait()
        return self.base_transport.send(
            method=method,
            url=url,
            headers=headers,
            data=data,
            params=params,
            timeout_s=timeout_s,
            proxy=proxy,
        )
