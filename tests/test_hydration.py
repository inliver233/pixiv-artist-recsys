from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, SeedUser
from pixiv_artist_recsys.ingest import ArtistIllustHydrationService
from pixiv_artist_recsys.pixiv.models import PagedResult, PixivIllustDetail, PixivIllustSummary
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class FakeHydrationClient:
    def __init__(self, *, list_tags: list[str] | None = None) -> None:
        self.list_tags = list_tags
        self.detail_calls = 0

    def fetch_user_illusts(self, *, user_id: int, type_: str = 'illust', offset: int | None = None):
        tags = list(self.list_tags) if self.list_tags is not None else []
        return PagedResult(
            items=[
                PixivIllustSummary(
                    illust_id=user_id * 10 + 1,
                    user_id=user_id,
                    title=f'illust-{user_id}',
                    create_date='2026-03-01T00:00:00+00:00',
                    total_bookmarks=50,
                    total_view=500,
                    total_comments=5,
                    tags=tags,
                    ai_type=0,
                    x_restrict=0,
                )
            ],
            next_url=None,
        )

    def fetch_illust_detail(self, *, illust_id: int):
        self.detail_calls += 1
        user_id = illust_id // 10
        return PixivIllustDetail(
            illust=PixivIllustSummary(
                illust_id=illust_id,
                user_id=user_id,
                title=f'illust-{illust_id}',
                create_date='2026-03-01T00:00:00+00:00',
                total_bookmarks=50,
                total_view=500,
                total_comments=5,
            ),
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
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_artist(Artist(user_id=1002, name='artist-2', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1002)

            client = FakeHydrationClient()
            result = ArtistIllustHydrationService(repository=repo, pixiv_client=client).hydrate_followed_artists(seed_user_id=7)

            self.assertEqual(result.scope, 'followed')
            self.assertEqual(result.artists_processed, 2)
            self.assertEqual(result.illusts_upserted, 2)
            self.assertEqual(result.detail_fetches, 2)
            self.assertEqual(client.detail_calls, 2)
            self.assertEqual(repo.count_rows('illusts'), 2)
            self.assertEqual(sorted(repo.fetch_artist_tags(artist_user_id=1001)), ['tag-a', 'tag-b'])

    def test_hydrate_skips_detail_when_list_has_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'hydration-list-only.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)

            client = FakeHydrationClient(list_tags=['tag-a', 'tag-b'])
            result = ArtistIllustHydrationService(repository=repo, pixiv_client=client).hydrate_followed_artists(seed_user_id=7)

            self.assertEqual(result.artists_processed, 1)
            self.assertEqual(result.illusts_upserted, 1)
            self.assertEqual(result.list_only_saves, 1)
            self.assertEqual(result.detail_fetches, 0)
            self.assertEqual(client.detail_calls, 0)
            self.assertEqual(sorted(repo.fetch_artist_tags(artist_user_id=1001)), ['tag-a', 'tag-b'])


class CandidateHydrationTests(unittest.TestCase):
    def test_hydrate_candidate_artists_skips_followed_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'candidate-hydration.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.upsert_artist(Artist(user_id=2001, name='candidate-a'))
            repo.upsert_artist(Artist(user_id=2002, name='candidate-b'))
            repo.replace_artist_candidates(
                seed_user_id=7,
                candidates=[
                    (1001, 'user_related', 'user:1001', 1.0, 'followed-should-skip'),
                    (2001, 'user_related', 'user:1001', 1.0, 'a'),
                    (2001, 'illust_related', 'illust:5001', 0.8, 'dup-a'),
                    (2002, 'illust_related', 'illust:5002', 0.8, 'b'),
                ],
            )

            result = ArtistIllustHydrationService(repository=repo, pixiv_client=FakeHydrationClient()).hydrate_candidate_artists(seed_user_id=7, per_artist_limit=1)

            self.assertEqual(result.scope, 'candidate')
            self.assertEqual(result.artists_processed, 2)
            self.assertEqual(result.illusts_upserted, 2)
            self.assertEqual(repo.list_candidate_artist_ids(seed_user_id=7), [1001, 2001, 2002])
            self.assertEqual(sorted(repo.fetch_artist_tags(artist_user_id=2001)), ['tag-a', 'tag-b'])
            self.assertEqual(repo.list_illust_ids_for_artist(artist_user_id=2002), [20021])


if __name__ == '__main__':
    unittest.main()
