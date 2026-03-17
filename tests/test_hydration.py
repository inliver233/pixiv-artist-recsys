from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist
from pixiv_artist_recsys.ingest import ArtistIllustHydrationService
from pixiv_artist_recsys.pixiv.models import PagedResult, PixivIllustDetail, PixivIllustSummary
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class FakeHydrationClient:
    def fetch_user_illusts(self, *, user_id: int, type_: str = 'illust', offset: int | None = None):
        return PagedResult(items=[PixivIllustSummary(illust_id=user_id * 10 + 1, user_id=user_id, title=f'illust-{user_id}')], next_url=None)

    def fetch_illust_detail(self, *, illust_id: int):
        user_id = illust_id // 10
        return PixivIllustDetail(
            illust=PixivIllustSummary(illust_id=illust_id, user_id=user_id, title=f'illust-{illust_id}', create_date='2026-03-01T00:00:00+00:00', total_bookmarks=50, total_view=500, total_comments=5),
            tags=['tag-a', 'tag-b'],
            original_image_url=f'https://i.pximg.net/{illust_id}.jpg',
            page_count=1,
            ai_type=0,
            x_restrict=0,
        )


class HydrationTests(unittest.TestCase):
    def test_hydrate_followed_artists_persists_illusts_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'hydration.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(__import__('pixiv_artist_recsys.domain.models', fromlist=['SeedUser']).SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_artist(Artist(user_id=1002, name='artist-2', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1002)

            result = ArtistIllustHydrationService(repository=repo, pixiv_client=FakeHydrationClient()).hydrate_followed_artists(seed_user_id=7)

            self.assertEqual(result.artists_processed, 2)
            self.assertEqual(result.illusts_upserted, 2)
            self.assertEqual(repo.count_rows('illusts'), 2)
            self.assertEqual(sorted(repo.fetch_artist_tags(artist_user_id=1001)), ['tag-a', 'tag-b'])


if __name__ == '__main__':
    unittest.main()
