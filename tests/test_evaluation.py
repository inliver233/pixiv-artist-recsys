from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, Illust, SeedUser
from pixiv_artist_recsys.evaluation import LeaveOneOutEvaluator
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


def _seed_artist(repo: RecommendationRepository, *, artist_id: int, tags: list[str], bookmarks: int, followed: bool) -> None:
    repo.upsert_artist(Artist(user_id=artist_id, name=f'artist-{artist_id}', is_followed=followed))
    if followed:
        repo.upsert_following_edge(seed_user_id=7, artist_user_id=artist_id)
    for i in range(1, 4):
        illust_id = artist_id * 100 + i
        repo.upsert_illust(
            Illust(
                illust_id=illust_id,
                user_id=artist_id,
                title=f'illust-{illust_id}',
                create_date='2026-01-01T00:00:00+00:00',
                total_bookmarks=bookmarks,
                total_view=bookmarks * 10,
                total_comments=2,
                ai_type=0,
                x_restrict=0,
            )
        )
        repo.replace_illust_tags(illust_id=illust_id, tags=tags)


class LeaveOneOutEvaluatorTests(unittest.TestCase):
    def test_holdout_artists_matching_taste_rank_above_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SQLiteDatabase(Path(tmpdir) / 'eval.sqlite3')
            repo = RecommendationRepository(db)
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))

            # 10 followed artists sharing a coherent taste (blue_hair + sword).
            for artist_id in range(1001, 1011):
                _seed_artist(repo, artist_id=artist_id, tags=['blue_hair', 'sword', 'fantasy'], bookmarks=500, followed=True)
            # Off-taste noise candidates already in the store.
            for artist_id in range(2001, 2006):
                _seed_artist(repo, artist_id=artist_id, tags=['mecha', 'robot', 'scifi'], bookmarks=500, followed=False)
                repo.replace_artist_candidates(
                    seed_user_id=7,
                    candidates=[(artist_id, 'user_related', 'noise', 1.0, 'noise')],
                    merge=True,
                )

            evaluator = LeaveOneOutEvaluator(database=db, holdout_ratio=0.2, rng_seed=42)
            report = evaluator.evaluate(seed_user_id=7, recall_k=5, ndcg_k=5)

            self.assertEqual(report.followed_total, 10)
            self.assertEqual(report.holdout_count, 2)
            # Holdout artists share the profile's taste; noise does not — they
            # must be recalled within top-5 of a 7-candidate pool.
            self.assertEqual(report.recall_at_k, 1.0)
            self.assertGreater(report.ndcg_at_k, 0.5)
            self.assertEqual(report.holdout_ranked, 2)

    def test_evaluation_does_not_mutate_source_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SQLiteDatabase(Path(tmpdir) / 'eval-src.sqlite3')
            repo = RecommendationRepository(db)
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            for artist_id in range(1001, 1011):
                _seed_artist(repo, artist_id=artist_id, tags=['blue_hair', 'sword'], bookmarks=300, followed=True)

            edges_before = repo.count_rows('seed_user_following_artists')
            profile_before = repo.fetch_user_taste_profile(seed_user_id=7)
            LeaveOneOutEvaluator(database=db, holdout_ratio=0.3, rng_seed=1).evaluate(seed_user_id=7)

            self.assertEqual(repo.count_rows('seed_user_following_artists'), edges_before)
            self.assertEqual(repo.fetch_user_taste_profile(seed_user_id=7), profile_before)

    def test_deterministic_given_same_rng_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SQLiteDatabase(Path(tmpdir) / 'eval-det.sqlite3')
            repo = RecommendationRepository(db)
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            for artist_id in range(1001, 1021):
                _seed_artist(repo, artist_id=artist_id, tags=['blue_hair', 'sword'], bookmarks=300, followed=True)

            evaluator = LeaveOneOutEvaluator(database=db, holdout_ratio=0.2, rng_seed=99)
            a = evaluator.evaluate(seed_user_id=7)
            b = evaluator.evaluate(seed_user_id=7)
            self.assertEqual(a.holdout_positions, b.holdout_positions)
            self.assertEqual(a.recall_at_k, b.recall_at_k)


if __name__ == '__main__':
    unittest.main()
