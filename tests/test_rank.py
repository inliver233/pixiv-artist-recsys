from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, Illust, SeedUser
from pixiv_artist_recsys.rank import HeuristicArtistRankService
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class RankServiceTests(unittest.TestCase):
    def test_rank_from_store_uses_profile_candidates_and_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'rank.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.replace_user_taste_profile(seed_user_id=7, weights=[('blue_hair', 0.8), ('制服', 0.2)])
            repo.upsert_artist(Artist(user_id=2001, name='candidate-a'))
            repo.upsert_illust(Illust(illust_id=9001, user_id=2001, title='c1', total_bookmarks=100, total_view=1000, total_comments=10))
            repo.replace_illust_tags(illust_id=9001, tags=['blue hair', '制服'])
            repo.replace_artist_candidates(seed_user_id=7, candidates=[(2001, 'user_related', 'user:1001', 1.0, 'rel')])

            result = HeuristicArtistRankService(repository=repo).rank_from_store(seed_user_id=7)

            self.assertEqual(len(result.items), 1)
            self.assertEqual(result.items[0].artist.user_id, 2001)
            self.assertGreater(result.items[0].score, 0)
            self.assertTrue(result.items[0].reasons)

    def test_rank_guardrails_filter_ai_r18_and_low_bookmark_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'rank-guardrails.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token', allow_ai=False, allow_r18=False))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.replace_user_taste_profile(seed_user_id=7, weights=[('blue_hair', 0.7), ('制服', 0.3)])

            repo.upsert_artist(Artist(user_id=2001, name='normal-good'))
            repo.upsert_illust(Illust(illust_id=9001, user_id=2001, title='good', total_bookmarks=120, total_view=1200, total_comments=12, ai_type=0, x_restrict=0))
            repo.replace_illust_tags(illust_id=9001, tags=['blue hair', '制服'])

            repo.upsert_artist(Artist(user_id=2002, name='ai-candidate'))
            repo.upsert_illust(Illust(illust_id=9002, user_id=2002, title='ai', total_bookmarks=300, total_view=2000, total_comments=20, ai_type=1, x_restrict=0))
            repo.replace_illust_tags(illust_id=9002, tags=['blue hair'])

            repo.upsert_artist(Artist(user_id=2003, name='r18-candidate'))
            repo.upsert_illust(Illust(illust_id=9003, user_id=2003, title='r18', total_bookmarks=300, total_view=2000, total_comments=20, ai_type=0, x_restrict=1))
            repo.replace_illust_tags(illust_id=9003, tags=['blue hair'])

            repo.upsert_artist(Artist(user_id=2004, name='low-bookmark'))
            repo.upsert_illust(Illust(illust_id=9004, user_id=2004, title='low', total_bookmarks=5, total_view=80, total_comments=1, ai_type=0, x_restrict=0))
            repo.replace_illust_tags(illust_id=9004, tags=['blue hair'])

            repo.replace_artist_candidates(
                seed_user_id=7,
                candidates=[
                    (2001, 'user_related', 'user:1001', 1.0, 'good'),
                    (2002, 'user_related', 'user:1001', 1.0, 'ai'),
                    (2003, 'user_related', 'user:1001', 1.0, 'r18'),
                    (2004, 'user_related', 'user:1001', 1.0, 'low'),
                ],
            )

            result = HeuristicArtistRankService(repository=repo).rank_from_store(
                seed_user_id=7,
                min_total_bookmarks=30,
                min_score=0.1,
            )

            self.assertEqual([item.artist.user_id for item in result.items], [2001])
            self.assertIn('quality:min_bookmarks>=30', result.items[0].reasons)


if __name__ == '__main__':
    unittest.main()
