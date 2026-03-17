from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
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


if __name__ == '__main__':
    unittest.main()
