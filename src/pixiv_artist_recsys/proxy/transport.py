from __future__ import annotations

from typing import Mapping

from ..auth.transport import HttpResponse, HttpTransport
from .pool import ProxyPool


class FailoverHttpTransport:
    def __init__(self, *, base_transport: HttpTransport, proxy_pool: ProxyPool) -> None:
        self.base_transport = base_transport
        self.proxy_pool = proxy_pool

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
        attempts = [None] if proxy else self.proxy_pool.attempt_order()
        last_response: HttpResponse | None = None
        last_error: Exception | None = None

        for endpoint in attempts:
            selected_proxy = proxy or (endpoint.proxy_url if endpoint is not None else None)
            try:
                response = self.base_transport.send(
                    method=method,
                    url=url,
                    headers=headers,
                    data=data,
                    params=params,
                    timeout_s=timeout_s,
                    proxy=selected_proxy,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if endpoint is not None:
                    self.proxy_pool.record_failure(endpoint.proxy_id, exc)
                continue

            if endpoint is not None and response.status_code in self.proxy_pool.policy.retryable_status_codes:
                self.proxy_pool.record_failure(endpoint.proxy_id, f'http:{response.status_code}')
                last_response = response
                continue
            if endpoint is not None:
                self.proxy_pool.record_success(endpoint.proxy_id)
            return response

        if last_response is not None:
            return last_response
        if last_error is not None:
            raise last_error
        raise RuntimeError('No transport attempts available')
