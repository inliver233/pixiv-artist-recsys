from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.candidate import RelatedArtistCandidateService
from pixiv_artist_recsys.domain.models import Artist, Illust, SeedUser
from pixiv_artist_recsys.pixiv.models import PagedResult, PixivIllustSummary, PixivUserSummary
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class FakeRelatedClient:
    def fetch_user_related(self, *, seed_user_id: int, offset: int | None = None):
        return PagedResult(items=[PixivUserSummary(user_id=2001 + seed_user_id, name=f'user-rel-{seed_user_id}')], next_url=None)

    def fetch_illust_related(self, *, illust_id: int):
        return PagedResult(items=[PixivIllustSummary(illust_id=3000 + illust_id, user_id=4000 + illust_id, title='rel-illust')], next_url=None)

    def fetch_user_recommended(self, *, offset: int | None = None):
        return PagedResult(items=[PixivUserSummary(user_id=9001, name='rec-user', account='rec_user')], next_url=None)

    def fetch_search_illust(self, *, word: str, search_target: str = 'partial_match_for_tags', sort: str = 'popular_desc', offset: int | None = None):
        # Multiple illusts by the same artist under one tag — previously caused UNIQUE IntegrityError.
        return PagedResult(
            items=[
                PixivIllustSummary(illust_id=9101, user_id=9102, title=f'search-{word}-1', total_bookmarks=80, total_view=800),
                PixivIllustSummary(illust_id=9102, user_id=9102, title=f'search-{word}-2', total_bookmarks=70, total_view=700),
                PixivIllustSummary(illust_id=9103, user_id=9102, title=f'search-{word}-3', total_bookmarks=60, total_view=600),
            ],
            next_url=None,
        )


class FakeFollowingExpandClient(FakeRelatedClient):
    def __init__(self) -> None:
        self.following_calls: list[dict[str, object]] = []

    def fetch_following_users(self, *, user_id: int, restrict: str = 'public', offset: int | None = None):
        self.following_calls.append({'user_id': user_id, 'restrict': restrict, 'offset': offset})
        if offset:
            return PagedResult(items=[], next_url=None)
        return PagedResult(
            items=[
                PixivUserSummary(user_id=7, name='seed-self-skip'),  # seed user should be skipped
                PixivUserSummary(user_id=1001, name='already-followed'),  # followed should be skipped
                PixivUserSummary(user_id=7001, name='from-seed-following', account='sf1'),
                PixivUserSummary(user_id=7002, name='from-seed-following-2', account='sf2'),
            ],
            next_url=None,
        )


class CandidateRetrievalTests(unittest.TestCase):
    def test_replace_artist_candidates_dedupes_same_pk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'cand-dedupe.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            # Same PK thrice (tag_search multi-illust case) must not raise IntegrityError.
            repo.replace_artist_candidates(
                seed_user_id=7,
                candidates=[
                    (9102, 'tag_search', 'tag:オリジナル', 0.7, 'a'),
                    (9102, 'tag_search', 'tag:オリジナル', 0.7, 'b'),
                    (9102, 'tag_search', 'tag:オリジナル', 0.9, 'keep-max'),
                    (9103, 'user_related', 'user:1001', 1.0, 'rel'),
                ],
            )
            rows = repo.fetch_artist_candidates(seed_user_id=7)
            self.assertEqual(len(rows), 2)
            tag_row = next(r for r in rows if r[1] == 'tag_search')
            self.assertEqual(tag_row[0], 9102)
            self.assertEqual(tag_row[3], 0.9)
            self.assertEqual(tag_row[4], 'keep-max')

    def test_build_candidates_from_related_users_and_illusts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'cand.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.upsert_illust(Illust(illust_id=501, user_id=1001, title='seed-illust', total_bookmarks=30))

            result = RelatedArtistCandidateService(repository=repo, pixiv_client=FakeRelatedClient()).build_candidates(
                seed_user_id=7,
                enable_user_recommended=False,
                enable_tag_search=False,
                enable_seed_following=False,
            )

            self.assertEqual(result.candidate_count, 2)
            evidence = repo.fetch_artist_candidates(seed_user_id=7)
            self.assertEqual(len(evidence), 2)

    def test_build_candidates_includes_recommended_and_tag_search_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'cand-multi.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.upsert_illust(Illust(illust_id=501, user_id=1001, title='seed-illust', total_bookmarks=30))
            repo.replace_user_taste_profile(seed_user_id=7, weights=[('blue_hair', 1.0)])

            result = RelatedArtistCandidateService(repository=repo, pixiv_client=FakeRelatedClient()).build_candidates(
                seed_user_id=7,
                enable_seed_following=False,
            )

            sources = {row[1] for row in repo.fetch_artist_candidates(seed_user_id=7)}
            self.assertIn('user_related', sources)
            self.assertIn('illust_related', sources)
            self.assertIn('user_recommended', sources)
            self.assertIn('tag_search', sources)
            self.assertGreaterEqual(result.candidate_count, 4)

    def test_build_candidates_includes_seed_artist_following(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'cand-seed-follow.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.upsert_illust(Illust(illust_id=501, user_id=1001, title='seed-illust', total_bookmarks=30))

            client = FakeFollowingExpandClient()
            result = RelatedArtistCandidateService(repository=repo, pixiv_client=client).build_candidates(
                seed_user_id=7,
                enable_user_recommended=False,
                enable_tag_search=False,
                enable_seed_following=True,
                max_seed_following_artists=1,
                max_following_per_seed_artist=2,
                seed_following_sample='hydrated_first',
            )

            evidence = repo.fetch_artist_candidates(seed_user_id=7)
            sources = {row[1] for row in evidence}
            self.assertIn('seed_artist_following', sources)
            following_rows = [row for row in evidence if row[1] == 'seed_artist_following']
            self.assertEqual(len(following_rows), 2)
            self.assertTrue(all(row[3] == 0.55 for row in following_rows))
            artist_ids = {row[0] for row in following_rows}
            self.assertEqual(artist_ids, {7001, 7002})
            self.assertEqual(client.following_calls[0]['user_id'], 1001)
            self.assertEqual(client.following_calls[0]['restrict'], 'public')
            self.assertGreaterEqual(result.candidate_count, 4)

    def test_seed_following_sample_modes(self) -> None:
        service = RelatedArtistCandidateService(repository=object(), pixiv_client=FakeRelatedClient())  # type: ignore[arg-type]
        pool = [101, 102, 103, 104, 105]
        first = service._select_seed_artists_for_following_expand(
            pool_ids=pool,
            seed_user_id=7,
            max_artists=2,
            sample_mode='first',
        )
        self.assertEqual(first, [101, 102])
        hashed = service._select_seed_artists_for_following_expand(
            pool_ids=pool,
            seed_user_id=7,
            max_artists=3,
            sample_mode='hash',
        )
        self.assertEqual(len(hashed), 3)
        self.assertEqual(set(hashed), set(service._hash_sample(pool, seed_user_id=7, limit=3)))
        randomized = service._select_seed_artists_for_following_expand(
            pool_ids=pool,
            seed_user_id=7,
            max_artists=3,
            sample_mode='random',
        )
        self.assertEqual(len(randomized), 3)
        self.assertTrue(set(randomized).issubset(set(pool)))


if __name__ == '__main__':
    unittest.main()
