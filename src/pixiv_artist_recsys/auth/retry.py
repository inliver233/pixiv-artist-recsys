from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from .transport import HttpResponse, HttpTransport


DEFAULT_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_s: float = 0.8
    max_delay_s: float = 20.0
    jitter_s: float = 0.35
    retryable_status_codes: frozenset[int] = DEFAULT_RETRYABLE_STATUS_CODES


class RetryingHttpTransport:
    """Wrap a transport with bounded exponential backoff for transient failures."""

    def __init__(
        self,
        *,
        base_transport: HttpTransport,
        policy: RetryPolicy | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        random_fn: Callable[[float, float], float] | None = None,
    ) -> None:
        self.base_transport = base_transport
        self.policy = policy or RetryPolicy()
        self.sleep_fn = sleep_fn or time.sleep
        self.random_fn = random_fn or random.uniform

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
        timeout_s: float = 30.0,
        proxy: str | None = None,
    ) -> HttpResponse:
        attempts = max(1, int(self.policy.max_attempts))
        last_response: HttpResponse | None = None
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self.base_transport.send(
                    method=method,
                    url=url,
                    headers=headers,
                    data=data,
                    params=params,
                    timeout_s=timeout_s,
                    proxy=proxy,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= attempts:
                    raise
                self._sleep(attempt, response=None)
                continue

            if response.status_code not in self.policy.retryable_status_codes:
                return response

            last_response = response
            if attempt >= attempts:
                return response
            self._sleep(attempt, response=response)

        if last_response is not None:
            return last_response
        if last_error is not None:
            raise last_error
        raise RuntimeError('Retry transport exhausted without response')

    def _sleep(self, attempt: int, *, response: HttpResponse | None) -> None:
        delay = min(self.policy.max_delay_s, self.policy.base_delay_s * (2 ** (attempt - 1)))
        # 429: honour Retry-After when present; otherwise back off more aggressively.
        if response is not None and int(response.status_code) == 429:
            retry_after = self._parse_retry_after(response.headers)
            if retry_after is not None:
                delay = max(delay, retry_after)
            else:
                delay = max(delay, min(self.policy.max_delay_s, self.policy.base_delay_s * (2 ** attempt)))
        if self.policy.jitter_s > 0:
            delay += max(0.0, float(self.random_fn(0.0, self.policy.jitter_s)))
        if delay > 0:
            self.sleep_fn(delay)

    @staticmethod
    def _parse_retry_after(headers: Mapping[str, str] | None) -> float | None:
        if not headers:
            return None
        raw = None
        for key, value in headers.items():
            if str(key).lower() == 'retry-after':
                raw = value
                break
        if raw is None:
            return None
        try:
            seconds = float(str(raw).strip())
        except ValueError:
            return None
        if seconds < 0:
            return None
        return seconds
