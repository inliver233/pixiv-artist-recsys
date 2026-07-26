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


class SkipIfFreshTests(unittest.TestCase):
    def test_recently_hydrated_artist_is_skipped_within_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'fresh.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            for artist_id in (1001, 1002):
                repo.upsert_artist(Artist(user_id=artist_id, name=f'artist-{artist_id}', is_followed=True))
                repo.upsert_following_edge(seed_user_id=7, artist_user_id=artist_id)

            clock = {'now': 1_000_000.0}
            client = FakeHydrationClient(list_tags=['tag-a'])
            service = ArtistIllustHydrationService(
                repository=repo,
                pixiv_client=client,
                now_fn=lambda: clock['now'],
                freshness_max_age_s=7 * 86400.0,
                skip_min_local_illusts=1,
            )
            first = service.hydrate_followed_artists(seed_user_id=7)
            self.assertEqual(first.artists_processed, 2)
            self.assertEqual(first.skipped_fresh, 0)

            # Within TTL both artists are fresh: nothing re-fetched.
            clock['now'] += 3600.0
            second = service.hydrate_followed_artists(seed_user_id=7)
            self.assertEqual(second.artists_processed, 0)
            self.assertEqual(second.skipped_fresh, 2)

            # After TTL expiry hydration resumes.
            clock['now'] += 8 * 86400.0
            third = service.hydrate_followed_artists(seed_user_id=7)
            self.assertEqual(third.artists_processed, 2)

    def test_fresh_artist_without_enough_local_illusts_not_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'fresh-thin.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            # Marked hydrated recently but has zero local illusts → must NOT be skipped.
            repo.mark_artist_hydrated(artist_user_id=1001, now_epoch=1_000_000.0)

            service = ArtistIllustHydrationService(
                repository=repo,
                pixiv_client=FakeHydrationClient(list_tags=['tag-a']),
                now_fn=lambda: 1_000_100.0,
                freshness_max_age_s=7 * 86400.0,
                skip_min_local_illusts=1,
            )
            result = service.hydrate_followed_artists(seed_user_id=7)
            self.assertEqual(result.artists_processed, 1)
            self.assertEqual(result.skipped_fresh, 0)


class FaultToleranceTests(unittest.TestCase):
    def test_one_failing_artist_does_not_sink_the_run(self) -> None:
        class FlakyClient(FakeHydrationClient):
            def fetch_user_illusts(self, *, user_id: int, type_: str = 'illust', offset: int | None = None):
                if user_id == 1002:
                    raise RuntimeError('404 user deleted')
                return super().fetch_user_illusts(user_id=user_id, type_=type_, offset=offset)

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'fault.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            for artist_id in (1001, 1002, 1003):
                repo.upsert_artist(Artist(user_id=artist_id, name=f'artist-{artist_id}', is_followed=True))
                repo.upsert_following_edge(seed_user_id=7, artist_user_id=artist_id)

            result = ArtistIllustHydrationService(
                repository=repo,
                pixiv_client=FlakyClient(list_tags=['tag-a']),
            ).hydrate_followed_artists(seed_user_id=7)

            self.assertEqual(result.failed_artists, 1)
            self.assertEqual(result.illusts_upserted, 2)
            self.assertEqual(sorted(repo.fetch_artist_tags(artist_user_id=1001)), ['tag-a'])
            self.assertEqual(sorted(repo.fetch_artist_tags(artist_user_id=1003)), ['tag-a'])


class SourceQuotaTests(unittest.TestCase):
    def test_quota_reserves_slots_for_minor_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'quota.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            # 8 user_related candidates vs 2 tag_search candidates.
            rows = []
            for artist_id in range(3001, 3009):
                rows.append((artist_id, 'user_related', 'user:1', 1.0, 'ur'))
            for artist_id in (4001, 4002):
                rows.append((artist_id, 'tag_search', 'tag:x', 0.7, 'ts'))
            repo.replace_artist_candidates(seed_user_id=7, candidates=rows)

            service = ArtistIllustHydrationService(repository=repo, pixiv_client=FakeHydrationClient())
            selected = service._select_candidates_with_quota(
                seed_user_id=7,
                candidate_ids=[r[0] for r in rows],
                limit=5,
                seed_sample='first',
                sample_salt=None,
                explore_ratio=0.0,
                source_quotas={'user_related': 0.6, 'tag_search': 0.4},
            )
            self.assertEqual(len(selected), 5)
            tag_hits = [cid for cid in selected if cid in {4001, 4002}]
            # 40% of 5 = 2 slots reserved for tag_search even though user_related
            # dominates the pool.
            self.assertEqual(len(tag_hits), 2)

    def test_quota_spills_unused_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'quota-spill.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            rows = [(artist_id, 'user_related', 'user:1', 1.0, 'ur') for artist_id in range(3001, 3011)]
            repo.replace_artist_candidates(seed_user_id=7, candidates=rows)

            service = ArtistIllustHydrationService(repository=repo, pixiv_client=FakeHydrationClient())
            # tag_search quota exists but its bucket is empty → slots spill to user_related.
            selected = service._select_candidates_with_quota(
                seed_user_id=7,
                candidate_ids=[r[0] for r in rows],
                limit=6,
                seed_sample='first',
                sample_salt=None,
                explore_ratio=0.0,
                source_quotas={'user_related': 0.5, 'tag_search': 0.5},
            )
            self.assertEqual(len(selected), 6)


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
