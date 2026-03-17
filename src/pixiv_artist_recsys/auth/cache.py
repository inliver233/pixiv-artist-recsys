from __future__ import annotations

from collections.abc import Callable
import time
from dataclasses import replace
from typing import Protocol

from .models import PixivTokenRecord


class TokenRefresher(Protocol):
    def __call__(self, token_key: str, existing: PixivTokenRecord | None) -> PixivTokenRecord: ...


class AccessTokenCache:
    def __init__(self, *, refresh_margin_sec: int = 60, now_fn: Callable[[], int] | None = None) -> None:
        self.refresh_margin_sec = int(refresh_margin_sec)
        self.now_fn = now_fn or (lambda: int(time.time()))
        self._records: dict[str, PixivTokenRecord] = {}

    def get(self, token_key: str) -> PixivTokenRecord | None:
        return self._records.get(token_key)

    def is_valid(self, record: PixivTokenRecord | None) -> bool:
        if record is None or not record.access_token or record.expires_at_epoch <= 0:
            return False
        return int(self.now_fn()) < int(record.expires_at_epoch) - int(self.refresh_margin_sec)

    def get_valid(self, token_key: str) -> PixivTokenRecord | None:
        record = self.get(token_key)
        return record if self.is_valid(record) else None

    def store(self, record: PixivTokenRecord) -> PixivTokenRecord:
        self._records[record.token_key] = record
        return record

    def get_or_refresh(self, token_key: str, refresher: TokenRefresher) -> PixivTokenRecord:
        record = self.get_valid(token_key)
        if record is not None:
            return record
        refreshed = refresher(token_key, self.get(token_key))
        self.store(refreshed)
        return refreshed
