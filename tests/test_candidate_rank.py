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
        return PagedResult(
            items=[PixivIllustSummary(illust_id=9101, user_id=9102, title=f'search-{word}', total_bookmarks=80, total_view=800)],
            next_url=None,
        )


class CandidateRetrievalTests(unittest.TestCase):
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

            result = RelatedArtistCandidateService(repository=repo, pixiv_client=FakeRelatedClient()).build_candidates(seed_user_id=7)

            sources = {row[1] for row in repo.fetch_artist_candidates(seed_user_id=7)}
            self.assertIn('user_related', sources)
            self.assertIn('illust_related', sources)
            self.assertIn('user_recommended', sources)
            self.assertIn('tag_search', sources)
            self.assertGreaterEqual(result.candidate_count, 4)


if __name__ == '__main__':
    unittest.main()
