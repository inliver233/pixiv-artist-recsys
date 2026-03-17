from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .auth import AccessTokenCache, PixivOAuthService, PixivTokenCoordinator
from .auth.models import PixivTokenRecord
from .auth.transport import HttpTransport, UrllibHttpTransport
from .config import AppSettings, load_settings
from .pixiv import CoordinatorBackedAccessTokenProvider, PixivAppApiClient, StaticAccessTokenProvider
from .proxy import ProxyPool, build_http_transport_from_env
from .storage import RecommendationRepository, SQLiteDatabase


@dataclass(slots=True)
class AppRuntime:
    settings: AppSettings
    repository: RecommendationRepository
    transport: HttpTransport
    proxy_pool: ProxyPool | None = None

    @classmethod
    def create(
        cls,
        *,
        settings: AppSettings | None = None,
        env: Mapping[str, str] | None = None,
        base_transport: HttpTransport | None = None,
        now_fn=None,
    ) -> 'AppRuntime':
        env_mapping = dict(env or os.environ)
        settings = settings or load_settings(env=env_mapping)
        transport, proxy_pool = build_http_transport_from_env(
            env_mapping,
            base_transport=base_transport or UrllibHttpTransport(),
            now_fn=now_fn,
        )
        repository = RecommendationRepository(SQLiteDatabase(settings.storage.sqlite_path))
        return cls(settings=settings, repository=repository, transport=transport, proxy_pool=proxy_pool)

    @property
    def db_path(self) -> Path:
        return self.settings.storage.sqlite_path

    def prepare(self) -> None:
        self.settings.ensure_directories()
        self.repository.initialize()

    @staticmethod
    def resolve_access_token(access_token: str | None = None, env: Mapping[str, str] | None = None) -> str:
        env = env or os.environ
        return (access_token or env.get('PIXIV_ARTIST_RECSYS_ACCESS_TOKEN', '')).strip()

    @staticmethod
    def resolve_refresh_token(refresh_token: str | None = None, env: Mapping[str, str] | None = None) -> str:
        env = env or os.environ
        return (refresh_token or env.get('PIXIV_ARTIST_RECSYS_REFRESH_TOKEN', '')).strip()

    @classmethod
    def resolve_refresh_token_ref(
        cls,
        *,
        refresh_token: str | None = None,
        access_token: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        resolved_refresh_token = cls.resolve_refresh_token(refresh_token, env)
        if resolved_refresh_token:
            return PixivTokenRecord.mask_refresh_token(resolved_refresh_token)
        if cls.resolve_access_token(access_token, env):
            return 'access-token-only'
        return 'masked:'

    def proxy_state_payload(self) -> dict[str, object]:
        return {
            'enabled': self.proxy_pool is not None,
            'proxies': [asdict(snapshot) for snapshot in self.proxy_pool.snapshot()] if self.proxy_pool is not None else [],
            'allow_direct_fallback': bool(self.proxy_pool.policy.allow_direct_fallback) if self.proxy_pool is not None else True,
        }

    def settings_payload(self) -> dict[str, Any]:
        return {
            'mode': self.settings.mode.value,
            'paths': {
                'repo_root': str(self.settings.paths.repo_root),
                'data_dir': str(self.settings.paths.data_dir),
                'runtime_dir': str(self.settings.paths.runtime_dir),
                'logs_dir': str(self.settings.paths.logs_dir),
                'cache_dir': str(self.settings.paths.cache_dir),
            },
            'storage': {
                'sqlite_path': str(self.settings.storage.sqlite_path),
            },
            'api': asdict(self.settings.api),
            'recommendation': asdict(self.settings.recommendation),
        }

    def build_pixiv_client(
        self,
        *,
        seed_user_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> PixivAppApiClient:
        resolved_access_token = self.resolve_access_token(access_token, env)
        if resolved_access_token:
            provider = StaticAccessTokenProvider(access_token=resolved_access_token)
            return PixivAppApiClient(access_token_provider=provider, transport=self.transport)

        resolved_refresh_token = self.resolve_refresh_token(refresh_token, env)
        if not resolved_refresh_token:
            raise ValueError('this command requires --refresh-token or PIXIV_ARTIST_RECSYS_REFRESH_TOKEN (or access token equivalent)')

        provider = CoordinatorBackedAccessTokenProvider(
            coordinator=PixivTokenCoordinator(
                cache=AccessTokenCache(),
                oauth_service=PixivOAuthService(transport=self.transport),
                repository=self.repository,
            ),
            token_key=(token_key or f'seed-user:{seed_user_id}'),
            refresh_token=resolved_refresh_token,
        )
        return PixivAppApiClient(access_token_provider=provider, transport=self.transport)


RuntimeContext = AppRuntime
