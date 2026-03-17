from __future__ import annotations

from .cache import AccessTokenCache
from .models import PixivTokenRecord
from .service import PixivOAuthService


class PixivTokenCoordinator:
    def __init__(self, *, cache: AccessTokenCache, oauth_service: PixivOAuthService, repository) -> None:
        self.cache = cache
        self.oauth_service = oauth_service
        self.repository = repository

    def get_access_token_record(self, *, token_key: str, refresh_token: str) -> PixivTokenRecord:
        cached = self.cache.get_valid(token_key)
        if cached is not None:
            return cached

        existing = self.repository.get_token_record(token_key)
        if self.cache.is_valid(existing):
            return self.cache.store(existing)

        refreshed = self.oauth_service.refresh_into_record(token_key=token_key, refresh_token=refresh_token, existing=existing)
        self.repository.upsert_token_record(refreshed)
        self.cache.store(refreshed)
        return refreshed
