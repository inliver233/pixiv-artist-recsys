from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.pipeline import LiveRecommendationPipeline, LiveRecommendationRequest
from pixiv_artist_recsys.pixiv.models import PagedResult, PixivIllustDetail, PixivIllustSummary, PixivUserSummary
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class FakeLivePixivClient:
    def fetch_following_users(self, *, user_id: int, restrict: str = 'public', offset: int | None = None):
        return PagedResult(
            items=[
                PixivUserSummary(user_id=1001, name='followed-a', account='followed_a'),
                PixivUserSummary(user_id=1002, name='followed-b', account='followed_b'),
            ],
            next_url=None,
        )

    def fetch_user_illusts(self, *, user_id: int, type_: str = 'illust', offset: int | None = None):
        mapping = {
            1001: [
                PixivIllustSummary(illust_id=10011, user_id=1001, title='f-a-1'),
                PixivIllustSummary(illust_id=10012, user_id=1001, title='f-a-2'),
            ],
            1002: [
                PixivIllustSummary(illust_id=10021, user_id=1002, title='f-b-1'),
                PixivIllustSummary(illust_id=10022, user_id=1002, title='f-b-2'),
            ],
            2001: [
                PixivIllustSummary(illust_id=20011, user_id=2001, title='c-a-1'),
                PixivIllustSummary(illust_id=20012, user_id=2001, title='c-a-2'),
            ],
            2002: [
                PixivIllustSummary(illust_id=20021, user_id=2002, title='c-b-1'),
                PixivIllustSummary(illust_id=20022, user_id=2002, title='c-b-2'),
            ],
        }
        return PagedResult(items=mapping.get(user_id, []), next_url=None)

    def fetch_illust_detail(self, *, illust_id: int):
        # Bookmark tiers must clear v3 profile_min_bookmarks (200) and relative quality vs followed median.
        payloads = {
            10011: self._detail(10011, 1001, ['Blue Hair', '制服'], 520, 5200, 25),
            10012: self._detail(10012, 1001, ['Blue Hair'], 480, 4800, 22),
            10021: self._detail(10021, 1002, ['blue hair', '夜景'], 500, 5000, 20),
            10022: self._detail(10022, 1002, ['blue hair'], 460, 4600, 18),
            20011: self._detail(20011, 2001, ['blue hair', '制服'], 650, 6500, 30),
            20012: self._detail(20012, 2001, ['blue hair', '制服'], 600, 6000, 28),
            20021: self._detail(20021, 2002, ['风景'], 40, 400, 2),
            20022: self._detail(20022, 2002, ['风景'], 30, 300, 1),
        }
        return payloads[illust_id]

    def fetch_user_related(self, *, seed_user_id: int, offset: int | None = None):
        mapping = {
            1001: [PixivUserSummary(user_id=2001, name='candidate-a', account='candidate_a')],
            1002: [PixivUserSummary(user_id=2002, name='candidate-b', account='candidate_b')],
        }
        return PagedResult(items=mapping.get(seed_user_id, []), next_url=None)

    def fetch_illust_related(self, *, illust_id: int):
        mapping = {
            10011: [PixivIllustSummary(illust_id=20011, user_id=2001, title='related-a')],
            10012: [PixivIllustSummary(illust_id=20012, user_id=2001, title='related-a-2')],
            10021: [PixivIllustSummary(illust_id=20021, user_id=2002, title='related-b')],
            10022: [PixivIllustSummary(illust_id=20022, user_id=2002, title='related-b-2')],
        }
        return PagedResult(items=mapping.get(illust_id, []), next_url=None)

    @staticmethod
    def _detail(illust_id: int, user_id: int, tags: list[str], bookmarks: int, views: int, comments: int) -> PixivIllustDetail:
        return PixivIllustDetail(
            illust=PixivIllustSummary(
                illust_id=illust_id,
                user_id=user_id,
                title=f'illust-{illust_id}',
                create_date='2026-03-01T00:00:00+00:00',
                total_bookmarks=bookmarks,
                total_view=views,
                total_comments=comments,
            ),
            tags=tags,
            original_image_url=f'https://i.pximg.net/{illust_id}.jpg',
            page_count=1,
            ai_type=0,
            x_restrict=0,
        )


class LivePipelineTests(unittest.TestCase):
    def test_live_pipeline_runs_full_flow_and_persists_recommendation_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'live-pipeline.sqlite3'))
            repo.initialize()
            pipeline = LiveRecommendationPipeline(repository=repo, pixiv_client=FakeLivePixivClient())

            result = pipeline.run(
                LiveRecommendationRequest(
                    seed_user_id=7,
                    refresh_token_ref='masked:token',
                    followed_artist_limit=2,
                    candidate_artist_limit=2,
                    max_related_per_artist=2,
                    max_related_per_illust=2,
                    max_results=5,
                    min_total_bookmarks=30,
                    min_score=0.1,
                )
            )

            self.assertEqual(result.following_result.synced_count, 2)
            self.assertEqual(result.followed_hydration_result.illusts_upserted, 4)
            self.assertEqual(result.profile_summary.artist_count, 2)
            self.assertEqual(result.candidate_result.candidate_count, 2)
            self.assertEqual(result.candidate_hydration_result.artists_processed, 2)
            self.assertEqual([item.artist.user_id for item in result.run.items], [2001])
            self.assertEqual(repo.count_rows('recommendation_runs'), 1)
            self.assertEqual(repo.count_rows('recommendation_items'), len(result.run.items))
            audit = repo.fetch_run_audit(run_id=result.run.run_id)
            self.assertIsNotNone(audit)
            self.assertEqual(audit['candidate']['candidate_count'], 2)
            self.assertEqual(audit['ranked']['artist_user_ids'], [2001])
            self.assertGreaterEqual(repo.count_rows('illusts'), 8)

    def test_live_pipeline_respects_max_seed_and_candidate_caps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'live-pipeline-caps.sqlite3'))
            repo.initialize()
            pipeline = LiveRecommendationPipeline(repository=repo, pixiv_client=FakeLivePixivClient())

            result = pipeline.run(
                LiveRecommendationRequest(
                    seed_user_id=7,
                    refresh_token_ref='masked:token',
                    followed_artist_limit=2,
                    candidate_artist_limit=2,
                    max_related_per_artist=2,
                    max_related_per_illust=2,
                    max_seed_artists=1,
                    max_candidate_artists=1,
                    max_results=5,
                    min_total_bookmarks=30,
                    min_score=0.1,
                )
            )

            self.assertEqual(result.followed_hydration_result.artists_processed, 1)
            self.assertEqual(result.candidate_hydration_result.artists_processed, 1)


if __name__ == '__main__':
    unittest.main()
