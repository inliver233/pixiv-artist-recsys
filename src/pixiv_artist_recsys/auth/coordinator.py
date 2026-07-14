from __future__ import annotations

from dataclasses import replace

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

        # Prefer previously rotated refresh token from DB; fall back to caller-provided token.
        effective_refresh = (refresh_token or '').strip()
        if existing is not None and (existing.refresh_token_rotated or '').strip():
            effective_refresh = existing.refresh_token_rotated.strip()
        if not effective_refresh:
            raise ValueError('refresh_token is required')

        refreshed = self.oauth_service.refresh_into_record(
            token_key=token_key,
            refresh_token=effective_refresh,
            existing=existing,
        )
        # If OAuth response omitted a new refresh token, keep the effective one for next rotation.
        if not (refreshed.refresh_token_rotated or '').strip():
            refreshed = replace(refreshed, refresh_token_rotated=effective_refresh)

        self.repository.upsert_token_record(refreshed)
        self.cache.store(refreshed)
        return refreshed
