from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib import error, parse, request


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    text: str

    def json(self) -> object:
        return json.loads(self.text)


class HttpTransport(Protocol):
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
    ) -> HttpResponse: ...


class UrllibHttpTransport:
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
        final_url = url
        if params:
            query = parse.urlencode({k: v for k, v in params.items() if v is not None})
            separator = '&' if '?' in final_url else '?'
            final_url = f"{final_url}{separator}{query}"

        body = None
        if data:
            body = parse.urlencode(data).encode('utf-8')

        req = request.Request(final_url, data=body, method=method.upper())
        for key, value in (headers or {}).items():
            req.add_header(key, value)

        opener = request.build_opener(request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout_s) as resp:
                text = resp.read().decode('utf-8')
                return HttpResponse(status_code=int(resp.getcode()), headers=dict(resp.headers.items()), text=text)
        except error.HTTPError as exc:
            text = exc.read().decode('utf-8', errors='replace') if exc.fp is not None else ''
            return HttpResponse(status_code=int(exc.code), headers=dict(exc.headers.items()), text=text)
