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
            repo.upsert_illust(Illust(illust_id=9002, user_id=2001, title='c2', total_bookmarks=90, total_view=900, total_comments=8))
            repo.replace_illust_tags(illust_id=9001, tags=['blue hair', '制服'])
            repo.replace_illust_tags(illust_id=9002, tags=['blue hair'])
            repo.replace_artist_candidates(seed_user_id=7, candidates=[(2001, 'user_related', 'user:1001', 1.0, 'rel')])

            result = HeuristicArtistRankService(repository=repo).rank_from_store(seed_user_id=7, min_score=0.05)

            self.assertEqual(len(result.items), 1)
            self.assertEqual(result.items[0].artist.user_id, 2001)
            self.assertGreater(result.items[0].score, 0)
            self.assertTrue(result.items[0].reasons)
            self.assertTrue(any(reason.startswith('quality:median_bookmarks=') for reason in result.items[0].reasons))
            self.assertTrue(any(reason.startswith('quality:consistency=') for reason in result.items[0].reasons))
            self.assertTrue(any(reason.startswith('taste:score=') for reason in result.items[0].reasons))

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
            repo.upsert_illust(Illust(illust_id=9011, user_id=2001, title='good-2', total_bookmarks=100, total_view=1000, total_comments=10, ai_type=0, x_restrict=0))
            repo.replace_illust_tags(illust_id=9001, tags=['blue hair', '制服'])
            repo.replace_illust_tags(illust_id=9011, tags=['blue hair'])

            repo.upsert_artist(Artist(user_id=2002, name='ai-candidate'))
            repo.upsert_illust(Illust(illust_id=9002, user_id=2002, title='ai', total_bookmarks=300, total_view=2000, total_comments=20, ai_type=1, x_restrict=0))
            repo.upsert_illust(Illust(illust_id=9022, user_id=2002, title='ai-2', total_bookmarks=280, total_view=1800, total_comments=18, ai_type=1, x_restrict=0))
            repo.replace_illust_tags(illust_id=9002, tags=['blue hair'])
            repo.replace_illust_tags(illust_id=9022, tags=['blue hair'])

            repo.upsert_artist(Artist(user_id=2003, name='r18-candidate'))
            repo.upsert_illust(Illust(illust_id=9003, user_id=2003, title='r18', total_bookmarks=300, total_view=2000, total_comments=20, ai_type=0, x_restrict=1))
            repo.upsert_illust(Illust(illust_id=9033, user_id=2003, title='r18-2', total_bookmarks=280, total_view=1800, total_comments=18, ai_type=0, x_restrict=1))
            repo.replace_illust_tags(illust_id=9003, tags=['blue hair'])
            repo.replace_illust_tags(illust_id=9033, tags=['blue hair'])

            repo.upsert_artist(Artist(user_id=2004, name='low-bookmark'))
            repo.upsert_illust(Illust(illust_id=9004, user_id=2004, title='low', total_bookmarks=5, total_view=80, total_comments=1, ai_type=0, x_restrict=0))
            repo.upsert_illust(Illust(illust_id=9044, user_id=2004, title='low-2', total_bookmarks=4, total_view=70, total_comments=1, ai_type=0, x_restrict=0))
            repo.replace_illust_tags(illust_id=9004, tags=['blue hair'])
            repo.replace_illust_tags(illust_id=9044, tags=['blue hair'])

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
                min_score=0.05,
            )

            self.assertEqual([item.artist.user_id for item in result.items], [2001])
            self.assertIn('quality:min_bookmarks>=30', result.items[0].reasons)

    def test_rank_suppresses_blocked_artists_and_negative_tag_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'rank-feedback.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.replace_user_taste_profile(seed_user_id=7, weights=[('blue_hair', 1.0)])

            repo.upsert_artist(Artist(user_id=2999, name='blocked-source'))
            repo.upsert_illust(Illust(illust_id=9999, user_id=2999, title='blocked-source', total_bookmarks=80))
            repo.replace_illust_tags(illust_id=9999, tags=['gore'])
            repo.record_feedback_event(seed_user_id=7, artist_user_id=2999, action='block', source_run_id='run-1', note='block')
            repo.replace_user_negative_profile(seed_user_id=7, weights=[('gore', 1.0)])

            repo.upsert_artist(Artist(user_id=2001, name='good-candidate'))
            repo.upsert_illust(Illust(illust_id=9001, user_id=2001, title='good', total_bookmarks=120, total_view=1200, total_comments=12, ai_type=0, x_restrict=0))
            repo.upsert_illust(Illust(illust_id=9011, user_id=2001, title='good-2', total_bookmarks=110, total_view=1100, total_comments=10, ai_type=0, x_restrict=0))
            repo.replace_illust_tags(illust_id=9001, tags=['blue hair'])
            repo.replace_illust_tags(illust_id=9011, tags=['blue hair'])

            repo.upsert_artist(Artist(user_id=2002, name='negative-overlap'))
            repo.upsert_illust(Illust(illust_id=9002, user_id=2002, title='bad', total_bookmarks=150, total_view=1400, total_comments=15, ai_type=0, x_restrict=0))
            repo.upsert_illust(Illust(illust_id=9022, user_id=2002, title='bad-2', total_bookmarks=140, total_view=1300, total_comments=14, ai_type=0, x_restrict=0))
            repo.replace_illust_tags(illust_id=9002, tags=['gore'])
            repo.replace_illust_tags(illust_id=9022, tags=['gore'])

            repo.upsert_artist(Artist(user_id=2003, name='explicitly-blocked'))
            repo.upsert_illust(Illust(illust_id=9003, user_id=2003, title='blocked', total_bookmarks=160, total_view=1500, total_comments=16, ai_type=0, x_restrict=0))
            repo.upsert_illust(Illust(illust_id=9033, user_id=2003, title='blocked-2', total_bookmarks=150, total_view=1400, total_comments=15, ai_type=0, x_restrict=0))
            repo.replace_illust_tags(illust_id=9003, tags=['blue hair'])
            repo.replace_illust_tags(illust_id=9033, tags=['blue hair'])
            repo.record_feedback_event(seed_user_id=7, artist_user_id=2003, action='block', source_run_id='run-2', note='block direct')

            repo.replace_artist_candidates(
                seed_user_id=7,
                candidates=[
                    (2001, 'user_related', 'user:1001', 1.0, 'good'),
                    (2002, 'user_related', 'user:1001', 1.0, 'negative-tag'),
                    (2003, 'user_related', 'user:1001', 1.0, 'blocked-artist'),
                ],
            )

            result = HeuristicArtistRankService(repository=repo).rank_from_store(seed_user_id=7, min_score=0.05)

            self.assertEqual([item.artist.user_id for item in result.items], [2001])

    def test_rank_applies_primary_tag_diversity_before_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'rank-diversity.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.replace_user_taste_profile(seed_user_id=7, weights=[('blue_hair', 0.6), ('night_view', 0.4)])

            repo.upsert_artist(Artist(user_id=2001, name='blue-a'))
            repo.upsert_illust(Illust(illust_id=9101, user_id=2001, title='blue-a', total_bookmarks=150, total_view=1500, total_comments=10))
            repo.upsert_illust(Illust(illust_id=9111, user_id=2001, title='blue-a2', total_bookmarks=140, total_view=1400, total_comments=9))
            repo.replace_illust_tags(illust_id=9101, tags=['blue hair'])
            repo.replace_illust_tags(illust_id=9111, tags=['blue hair'])

            repo.upsert_artist(Artist(user_id=2002, name='blue-b'))
            repo.upsert_illust(Illust(illust_id=9102, user_id=2002, title='blue-b', total_bookmarks=140, total_view=1450, total_comments=9))
            repo.upsert_illust(Illust(illust_id=9122, user_id=2002, title='blue-b2', total_bookmarks=130, total_view=1350, total_comments=8))
            repo.replace_illust_tags(illust_id=9102, tags=['blue hair'])
            repo.replace_illust_tags(illust_id=9122, tags=['blue hair'])

            repo.upsert_artist(Artist(user_id=2003, name='night-c'))
            repo.upsert_illust(Illust(illust_id=9103, user_id=2003, title='night-c', total_bookmarks=100, total_view=1200, total_comments=8))
            repo.upsert_illust(Illust(illust_id=9133, user_id=2003, title='night-c2', total_bookmarks=90, total_view=1100, total_comments=7))
            repo.replace_illust_tags(illust_id=9103, tags=['night view'])
            repo.replace_illust_tags(illust_id=9133, tags=['night view'])

            repo.replace_artist_candidates(
                seed_user_id=7,
                candidates=[
                    (2001, 'user_related', 'user:1001', 1.0, 'blue-a'),
                    (2002, 'user_related', 'user:1001', 0.95, 'blue-b'),
                    (2003, 'user_related', 'user:1001', 0.9, 'night-c'),
                ],
            )

            result = HeuristicArtistRankService(repository=repo).rank_from_store(
                seed_user_id=7,
                max_results=2,
                min_score=0.05,
                diversity_primary_tag_limit=1,
            )

            self.assertEqual([item.artist.user_id for item in result.items], [2001, 2003])
            self.assertTrue(any(reason.startswith('diversity:primary_tag=') for reason in result.items[0].reasons))

    def test_rank_blocks_manga_furry_substring_and_requires_tag_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'rank-genre.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            # Distinctive taste tags (not generic stopwords) so overlap is meaningful after profile denoise.
            repo.replace_user_taste_profile(seed_user_id=7, weights=[('blue_hair', 0.5), ('night_view', 0.3)])

            repo.upsert_artist(Artist(user_id=2001, name='good-illust'))
            for i, illust_id in enumerate((9201, 9202), start=1):
                repo.upsert_illust(
                    Illust(
                        illust_id=illust_id,
                        user_id=2001,
                        title=f'g{i}',
                        total_bookmarks=200,
                        total_view=2000,
                        total_comments=10,
                        illust_type='illust',
                        page_count=1,
                    )
                )
                repo.replace_illust_tags(illust_id=illust_id, tags=['blue hair', 'night view'])

            repo.upsert_artist(Artist(user_id=2002, name='manga-artist'))
            for i, illust_id in enumerate((9211, 9212), start=1):
                repo.upsert_illust(
                    Illust(
                        illust_id=illust_id,
                        user_id=2002,
                        title=f'm{i}',
                        total_bookmarks=5000,
                        total_view=20000,
                        total_comments=50,
                        illust_type='manga',
                        page_count=8,
                    )
                )
                repo.replace_illust_tags(illust_id=illust_id, tags=['創作漫画', 'blue hair'])

            repo.upsert_artist(Artist(user_id=2003, name='furry-composite'))
            for i, illust_id in enumerate((9221, 9222), start=1):
                repo.upsert_illust(
                    Illust(
                        illust_id=illust_id,
                        user_id=2003,
                        title=f'f{i}',
                        total_bookmarks=4000,
                        total_view=15000,
                        total_comments=40,
                        illust_type='illust',
                        page_count=1,
                    )
                )
                # Composite tag that exact-match denylist previously missed.
                repo.replace_illust_tags(illust_id=illust_id, tags=['ケモノシスマイク', '創作'])

            repo.upsert_artist(Artist(user_id=2004, name='popular-no-taste'))
            for i, illust_id in enumerate((9231, 9232), start=1):
                repo.upsert_illust(
                    Illust(
                        illust_id=illust_id,
                        user_id=2004,
                        title=f'p{i}',
                        total_bookmarks=8000,
                        total_view=30000,
                        total_comments=80,
                    )
                )
                repo.replace_illust_tags(illust_id=illust_id, tags=['風景', '背景'])

            repo.upsert_artist(Artist(user_id=2005, name='single-illust'))
            repo.upsert_illust(Illust(illust_id=9241, user_id=2005, title='one', total_bookmarks=3000, total_view=10000, total_comments=30))
            repo.replace_illust_tags(illust_id=9241, tags=['blue hair', 'night view'])

            repo.upsert_artist(Artist(user_id=2006, name='partial-furry-fraction'))
            # 2/2 furry-tagged works → genre fraction filter should drop.
            for i, illust_id in enumerate((9251, 9252), start=1):
                repo.upsert_illust(Illust(illust_id=illust_id, user_id=2006, title=f'pf{i}', total_bookmarks=900, total_view=9000))
                repo.replace_illust_tags(illust_id=illust_id, tags=['furry', 'blue hair'])

            repo.replace_artist_candidates(
                seed_user_id=7,
                candidates=[
                    (2001, 'user_related', 'user:1001', 1.0, 'good'),
                    (2002, 'user_related', 'user:1001', 1.2, 'manga'),
                    (2003, 'seed_artist_following', 'user:1001', 0.55, 'furry-composite'),
                    (2004, 'user_recommended', 'rec', 1.1, 'popular'),
                    (2005, 'user_related', 'user:1001', 1.0, 'sparse'),
                    (2006, 'user_related', 'user:1001', 1.0, 'furry-frac'),
                ],
            )

            result = HeuristicArtistRankService(repository=repo).rank_from_store(
                seed_user_id=7,
                min_score=0.05,
                min_local_illusts=2,
                require_tag_overlap=True,
            )

            self.assertEqual([item.artist.user_id for item in result.items], [2001])
            self.assertTrue(any(reason.startswith('taste:score=') for reason in result.items[0].reasons))
            self.assertTrue(any(reason.startswith('purity:score=') for reason in result.items[0].reasons))


if __name__ == '__main__':
    unittest.main()
