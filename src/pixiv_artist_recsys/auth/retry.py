from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Mapping

from .transport import HttpResponse, HttpTransport


DEFAULT_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    retryable_status_codes: frozenset[int] = DEFAULT_RETRYABLE_STATUS_CODES


class RetryingHttpTransport:
    """Wrap a transport with bounded exponential backoff for transient failures."""

    def __init__(
        self,
        *,
        base_transport: HttpTransport,
        policy: RetryPolicy | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.base_transport = base_transport
        self.policy = policy or RetryPolicy()
        self.sleep_fn = sleep_fn or time.sleep

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
                self._sleep(attempt)
                continue

            if response.status_code not in self.policy.retryable_status_codes:
                return response

            last_response = response
            if attempt >= attempts:
                return response
            self._sleep(attempt)

        if last_response is not None:
            return last_response
        if last_error is not None:
            raise last_error
        raise RuntimeError('Retry transport exhausted without response')

    def _sleep(self, attempt: int) -> None:
        delay = min(self.policy.max_delay_s, self.policy.base_delay_s * (2 ** (attempt - 1)))
        if delay > 0:
            self.sleep_fn(delay)
