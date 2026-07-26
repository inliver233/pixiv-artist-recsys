from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import SeedUser
from pixiv_artist_recsys.ingest import FollowingSyncService
from pixiv_artist_recsys.pixiv.models import PagedResult, PixivUserSummary
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class FakeFollowingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int | None]] = []

    def fetch_following_users(self, *, user_id: int, restrict: str = 'public', offset: int | None = None):
        self.calls.append((user_id, offset))
        if not offset:
            return PagedResult(items=[
                PixivUserSummary(user_id=1001, name='artist-1', account='a1', profile_image_url='img1'),
                PixivUserSummary(user_id=1002, name='artist-2', account='a2', profile_image_url='img2'),
            ], next_url='next')
        return PagedResult(items=[PixivUserSummary(user_id=1003, name='artist-3', account='a3', profile_image_url='img3')], next_url=None)


class IngestTests(unittest.TestCase):
    def test_following_sync_persists_seed_user_artists_and_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'ingest.sqlite3'))
            repository.initialize()
            service = FollowingSyncService(repository=repository, pixiv_client=FakeFollowingClient())

            result = service.sync_following(seed_user_id=7, refresh_token_ref='masked:token')

            self.assertEqual(result.synced_count, 3)
            self.assertEqual(result.pages_fetched, 2)
            self.assertEqual(repository.count_rows('seed_users'), 1)
            self.assertEqual(repository.count_rows('artists'), 3)
            self.assertEqual(repository.count_rows('seed_user_following_artists'), 3)
            self.assertEqual(repository.list_following_artist_ids(seed_user_id=7), [1001, 1002, 1003])
            seed_user = repository.fetch_seed_user(user_id=7)
            self.assertIsNotNone(seed_user)
            self.assertFalse(seed_user.allow_ai)
            self.assertFalse(seed_user.allow_r18)

    def test_following_sync_skip_if_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'ingest-fresh.sqlite3'))
            repository.initialize()
            client = FakeFollowingClient()
            clock = {'now': 1_000_000.0}
            service = FollowingSyncService(
                repository=repository, pixiv_client=client, now_fn=lambda: clock['now']
            )

            # First sync always runs and stamps the epoch.
            first = service.sync_following(seed_user_id=7, refresh_token_ref='masked:token', skip_if_fresh_s=86400.0)
            self.assertFalse(first.skipped_fresh)
            self.assertEqual(first.synced_count, 3)

            # Few edges (< MIN_EDGES_FOR_SKIP) → never skips even when fresh.
            clock['now'] += 3600.0
            calls_before = len(client.calls)
            second = service.sync_following(seed_user_id=7, refresh_token_ref='masked:token', skip_if_fresh_s=86400.0)
            self.assertFalse(second.skipped_fresh)
            self.assertGreater(len(client.calls), calls_before)

            # With enough edges and a fresh stamp, the sync is skipped entirely.
            from pixiv_artist_recsys.domain.models import Artist
            for artist_id in range(2000, 2060):
                repository.upsert_artist(Artist(user_id=artist_id, name=f'a-{artist_id}', is_followed=True))
                repository.upsert_following_edge(seed_user_id=7, artist_user_id=artist_id)
            calls_before = len(client.calls)
            third = service.sync_following(seed_user_id=7, refresh_token_ref='masked:token', skip_if_fresh_s=86400.0)
            self.assertTrue(third.skipped_fresh)
            self.assertEqual(len(client.calls), calls_before)

            # After the freshness window the sync runs again.
            clock['now'] += 2 * 86400.0
            fourth = service.sync_following(seed_user_id=7, refresh_token_ref='masked:token', skip_if_fresh_s=86400.0)
            self.assertFalse(fourth.skipped_fresh)

    def test_following_sync_incremental_early_stop(self) -> None:
        class PagedKnownClient:
            """3 pages of 30; page 1 has 5 new + 25 known, rest all known."""

            def __init__(self) -> None:
                self.calls: list[int | None] = []

            def fetch_following_users(self, *, user_id: int, restrict: str = 'public', offset: int | None = None):
                self.calls.append(offset)
                start = offset or 0
                if start >= 90:
                    return PagedResult(items=[], next_url=None)
                items = []
                for i in range(start, start + 30):
                    # First five entries are brand-new follows; everything else known.
                    uid = 9000 + i if i < 5 else 3000 + i
                    items.append(PixivUserSummary(user_id=uid, name=f'a-{uid}'))
                return PagedResult(items=items, next_url='next' if start + 30 < 90 else None)

        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'ingest-incr.sqlite3'))
            repository.initialize()
            from pixiv_artist_recsys.domain.models import Artist
            # Pre-existing known edges 3005..3089 (85 edges ≥ MIN_EDGES_FOR_SKIP).
            for i in range(5, 90):
                repository.upsert_artist(Artist(user_id=3000 + i, name=f'a-{i}', is_followed=True))
                repository.upsert_following_edge(seed_user_id=7, artist_user_id=3000 + i)

            client = PagedKnownClient()
            service = FollowingSyncService(repository=repository, pixiv_client=client)
            result = service.sync_following(
                seed_user_id=7,
                refresh_token_ref='masked:token',
                incremental_stop_after=20,
            )
            # 25 consecutive known on page 1 crosses the threshold → stop after 1 page.
            self.assertEqual(result.pages_fetched, 1)
            self.assertEqual(len(client.calls), 1)
            # New follows were still recorded.
            following = repository.list_following_artist_ids(seed_user_id=7)
            for uid in (9000, 9001, 9002, 9003, 9004):
                self.assertIn(uid, following)

    def test_following_sync_preserves_existing_seed_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'ingest-prefs.sqlite3'))
            repository.initialize()
            repository.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:old', allow_ai=True, allow_r18=True))
            service = FollowingSyncService(repository=repository, pixiv_client=FakeFollowingClient())

            service.sync_following(seed_user_id=7, refresh_token_ref='masked:new')

            seed_user = repository.fetch_seed_user(user_id=7)
            self.assertIsNotNone(seed_user)
            self.assertEqual(seed_user.refresh_token_ref, 'masked:new')
            self.assertTrue(seed_user.allow_ai)
            self.assertTrue(seed_user.allow_r18)


if __name__ == '__main__':
    unittest.main()
