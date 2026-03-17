from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.auth import AccessTokenCache, HttpResponse, PixivOAuthConfig, PixivOAuthService, PixivTokenCoordinator
from pixiv_artist_recsys.auth.models import DEFAULT_HASH_SECRET, PixivTokenRecord
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        return HttpResponse(
            status_code=200,
            headers={},
            text='{"response": {"access_token": "access-123", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "refresh-rotated", "scope": "read", "user": {"id": "42"}}}',
        )


class AuthServiceTests(unittest.TestCase):
    def test_refresh_access_token_builds_signed_headers_and_parses_payload(self) -> None:
        transport = FakeTransport()
        service = PixivOAuthService(config=PixivOAuthConfig(), transport=transport)

        token = service.refresh_access_token(refresh_token='refresh-original', client_time='2026-03-17T00:00:00+00:00')

        self.assertEqual(token.access_token, 'access-123')
        self.assertEqual(token.refresh_token, 'refresh-rotated')
        self.assertEqual(token.user_id, 42)
        call = transport.calls[0]
        headers = call['headers']
        self.assertEqual(headers['X-Client-Time'], '2026-03-17T00:00:00+00:00')
        self.assertIn('X-Client-Hash', headers)
        self.assertEqual(call['data']['grant_type'], 'refresh_token')

    def test_refresh_into_record_and_repository_roundtrip(self) -> None:
        transport = FakeTransport()
        service = PixivOAuthService(config=PixivOAuthConfig(), transport=transport)
        record = service.refresh_into_record(token_key='seed:1', refresh_token='refresh-original')

        self.assertEqual(record.token_key, 'seed:1')
        self.assertTrue(record.access_token)
        self.assertEqual(record.user_id, 42)
        self.assertTrue(record.refresh_token_ref.startswith('masked:'))

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'auth.sqlite3'))
            repo.initialize()
            repo.upsert_token_record(record)
            loaded = repo.get_token_record('seed:1')
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.access_token, 'access-123')
            self.assertEqual(repo.count_rows('pixiv_tokens'), 1)


class AccessTokenCacheTests(unittest.TestCase):
    def test_cache_reuses_valid_record_and_refreshes_expired_one(self) -> None:
        calls: list[str] = []
        cache = AccessTokenCache(refresh_margin_sec=60, now_fn=lambda: 1000)
        valid = PixivTokenRecord(token_key='seed:1', refresh_token_ref='masked:a', access_token='tok-a', expires_at_epoch=2000)
        cache.store(valid)

        reused = cache.get_or_refresh('seed:1', lambda token_key, existing: calls.append(token_key) or existing)
        self.assertEqual(reused.access_token, 'tok-a')
        self.assertEqual(calls, [])

        cache = AccessTokenCache(refresh_margin_sec=60, now_fn=lambda: 1950)
        cache.store(valid)
        refreshed = cache.get_or_refresh('seed:1', lambda token_key, existing: PixivTokenRecord(token_key='seed:1', refresh_token_ref='masked:a', access_token='tok-b', expires_at_epoch=4000))
        self.assertEqual(refreshed.access_token, 'tok-b')

    def test_token_coordinator_uses_repo_then_refreshes_when_needed(self) -> None:
        transport = FakeTransport()
        service = PixivOAuthService(config=PixivOAuthConfig(), transport=transport)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'auth-cache.sqlite3'))
            repo.initialize()
            repo.upsert_token_record(PixivTokenRecord(token_key='seed:1', refresh_token_ref='masked:a', access_token='cached', expires_at_epoch=5000))
            coordinator = PixivTokenCoordinator(cache=AccessTokenCache(refresh_margin_sec=60, now_fn=lambda: 1000), oauth_service=service, repository=repo)
            record = coordinator.get_access_token_record(token_key='seed:1', refresh_token='refresh-original')
            self.assertEqual(record.access_token, 'cached')
            self.assertEqual(len(transport.calls), 0)

            coordinator = PixivTokenCoordinator(cache=AccessTokenCache(refresh_margin_sec=60, now_fn=lambda: 4990), oauth_service=service, repository=repo)
            record = coordinator.get_access_token_record(token_key='seed:1', refresh_token='refresh-original')
            self.assertEqual(record.access_token, 'access-123')
            self.assertEqual(len(transport.calls), 1)


if __name__ == '__main__':
    unittest.main()
