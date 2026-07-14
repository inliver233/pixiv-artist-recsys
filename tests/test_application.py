from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.application import ApplicationFacade
from pixiv_artist_recsys.domain.models import Artist, Illust, RecommendationItem, RecommendationRun, SeedUser
from pixiv_artist_recsys.pixiv.models import PagedResult, PixivIllustDetail, PixivIllustSummary, PixivUserDetail, PixivUserSummary
from pixiv_artist_recsys.runtime import AppRuntime


class FakeFullRecommendClient:
    def fetch_following_users(self, *, user_id: int, restrict: str = 'public', offset: int | None = None):
        return PagedResult(
            items=[
                PixivUserSummary(user_id=1001, name='followed-a', account='followed_a'),
                PixivUserSummary(user_id=1002, name='followed-b', account='followed_b'),
            ],
            next_url=None,
        )

    def fetch_user_illusts(self, *, user_id: int, type_: str = 'illust', offset: int | None = None):
        # ≥2 illusts per artist so rank min_local_illusts=2 can pass.
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
        }
        return PagedResult(items=mapping.get(user_id, []), next_url=None)

    def fetch_illust_detail(self, *, illust_id: int):
        payloads = {
            10011: self._detail(10011, 1001, ['Blue Hair', '制服'], 40, 400, 5),
            10012: self._detail(10012, 1001, ['Blue Hair'], 35, 350, 4),
            10021: self._detail(10021, 1002, ['blue hair', '夜景'], 30, 300, 3),
            10022: self._detail(10022, 1002, ['blue hair'], 28, 280, 2),
            20011: self._detail(20011, 2001, ['blue hair', '制服'], 150, 1500, 12),
            20012: self._detail(20012, 2001, ['blue hair', '制服'], 140, 1400, 11),
        }
        return payloads[illust_id]

    def fetch_user_related(self, *, seed_user_id: int, offset: int | None = None):
        mapping = {
            1001: [PixivUserSummary(user_id=2001, name='candidate-a', account='candidate_a')],
            1002: [],
        }
        return PagedResult(items=mapping.get(seed_user_id, []), next_url=None)

    def fetch_user_detail(self, *, user_id: int):
        return PixivUserDetail(
            user=PixivUserSummary(user_id=user_id, name=f'user-{user_id}', account=f'account_{user_id}', profile_image_url=f'https://img/{user_id}.jpg'),
            total_illusts=12,
            total_manga=3,
            total_illust_bookmarks_public=99,
        )

    def fetch_illust_related(self, *, illust_id: int):
        mapping = {
            10011: [PixivIllustSummary(illust_id=20011, user_id=2001, title='related-a')],
            10012: [PixivIllustSummary(illust_id=20012, user_id=2001, title='related-a-2')],
            10021: [],
            10022: [],
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


class ApplicationFacadeTests(unittest.TestCase):
    def _runtime(self, tmpdir: str, **extra_env: str) -> AppRuntime:
        env = {'PIXIV_ARTIST_RECSYS_DATA_DIR': str(Path(tmpdir) / 'data')}
        env.update(extra_env)
        runtime = AppRuntime.create(env=env, now_fn=lambda: 100)
        runtime.prepare()
        return runtime

    def test_facade_exports_run_payload_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir)
            runtime.repository.record_run(
                RecommendationRun(
                    seed_user_id=7,
                    run_id='run-app-1',
                    mode='live-heuristic',
                    items=[RecommendationItem(artist=Artist(user_id=2001, name='candidate-a'), score=1.2, confidence=0.9, reasons=['ok'], top_illust_ids=[9001])],
                )
            )
            runtime.repository.upsert_run_audit(run_id='run-app-1', seed_user_id=7, summary={'ranked': {'artist_user_ids': [2001]}})
            facade = ApplicationFacade(runtime=runtime)

            output_path = str(Path(tmpdir) / 'exports' / 'run-app-1.json')
            payload = facade.export_run_payload(run_id='run-app-1', output=output_path)

            self.assertTrue(payload['found'])
            self.assertEqual(payload['run']['run_id'], 'run-app-1')
            self.assertTrue(Path(output_path).exists())
            self.assertEqual(json.loads(Path(output_path).read_text(encoding='utf-8'))['run']['run_id'], 'run-app-1')

    def test_facade_full_recommend_payload_supports_injected_pixiv_client_factory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir)
            facade = ApplicationFacade(
                runtime=runtime,
                pixiv_client_factory=lambda **_: FakeFullRecommendClient(),
            )

            payload = facade.full_recommend_payload(
                seed_user_id=7,
                refresh_token='dummy-refresh-token',
                followed_artist_limit=2,
                candidate_artist_limit=2,
                max_results=5,
                min_bookmarks=100,
                min_score=0.1,
                diversity_per_tag=1,
            )

            self.assertEqual(payload['seed_user_id'], 7)
            self.assertEqual(payload['recommended_artist_ids'], [2001])
            self.assertEqual(payload['filters']['min_bookmarks'], 100)
            self.assertEqual(payload['filters']['diversity_per_tag'], 1)
            self.assertTrue(payload['items'])

    def test_facade_full_recommend_uses_separate_mother_token_for_following(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir)
            seen: list[dict[str, object]] = []

            def factory(**kwargs):
                seen.append(
                    {
                        'token_key': kwargs.get('token_key'),
                        'refresh_token': kwargs.get('refresh_token'),
                        'access_token': kwargs.get('access_token'),
                    }
                )
                return FakeFullRecommendClient()

            facade = ApplicationFacade(runtime=runtime, pixiv_client_factory=factory)
            payload = facade.full_recommend_payload(
                seed_user_id=7,
                refresh_token='child-token',
                following_refresh_token='mother-token',
                followed_artist_limit=2,
                candidate_artist_limit=2,
                max_results=5,
                min_bookmarks=100,
                min_score=0.1,
                diversity_per_tag=1,
            )

            self.assertEqual(payload['recommended_artist_ids'], [2001])
            self.assertTrue(payload['token_roles']['following_uses_mother'])
            refresh_tokens = {row['refresh_token'] for row in seen}
            self.assertIn('child-token', refresh_tokens)
            self.assertIn('mother-token', refresh_tokens)
            mother_rows = [row for row in seen if row['refresh_token'] == 'mother-token']
            self.assertTrue(any(str(row['token_key']).startswith('following-seed-user:') for row in mother_rows))

    def test_facade_recommend_from_store_payload_uses_runtime_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir, PIXIV_ARTIST_RECSYS_MIN_BOOKMARKS='10', PIXIV_ARTIST_RECSYS_MIN_SCORE='0.1', PIXIV_ARTIST_RECSYS_DIVERSITY_PER_TAG='3')
            repo = runtime.repository
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.replace_user_taste_profile(seed_user_id=7, weights=[('blue_hair', 0.8), ('制服', 0.2)])
            repo.upsert_artist(Artist(user_id=2001, name='candidate-a', account='candidate_a'))
            repo.upsert_illust(Illust(illust_id=9001, user_id=2001, title='c1', total_bookmarks=100, total_view=1000, total_comments=10))
            repo.upsert_illust(Illust(illust_id=9002, user_id=2001, title='c2', total_bookmarks=90, total_view=900, total_comments=8))
            repo.replace_illust_tags(illust_id=9001, tags=['blue hair', '制服'])
            repo.replace_illust_tags(illust_id=9002, tags=['blue hair'])
            repo.replace_artist_candidates(seed_user_id=7, candidates=[(2001, 'user_related', 'user:1001', 1.0, 'rel')])
            facade = ApplicationFacade(runtime=runtime)

            payload = facade.recommend_from_store_payload(seed_user_id=7, max_results=5, diversity_per_tag=runtime.settings.recommendation.diversity_per_tag)

            self.assertEqual(payload['item_count'], 1)
            self.assertEqual(payload['diversity_per_tag'], 3)
            self.assertEqual(payload['items'][0]['artist_user_id'], 2001)

    def test_facade_pixiv_inspector_payloads_use_injected_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir)
            facade = ApplicationFacade(
                runtime=runtime,
                pixiv_client_factory=lambda **_: FakeFullRecommendClient(),
            )

            following = facade.pixiv_following_payload(seed_user_id=7, refresh_token='dummy-refresh-token')
            detail = facade.pixiv_user_detail_payload(seed_user_id=7, target_user_id=1001, refresh_token='dummy-refresh-token')
            illusts = facade.pixiv_user_illusts_payload(seed_user_id=7, target_user_id=1001, refresh_token='dummy-refresh-token')
            illust_detail = facade.pixiv_illust_detail_payload(seed_user_id=7, illust_id=10011, refresh_token='dummy-refresh-token')
            related_users = facade.pixiv_user_related_payload(seed_user_id=7, target_user_id=1001, refresh_token='dummy-refresh-token')
            related_illusts = facade.pixiv_illust_related_payload(seed_user_id=7, illust_id=10011, refresh_token='dummy-refresh-token')

            self.assertEqual(following['count'], 2)
            self.assertEqual(detail['profile']['total_illusts'], 12)
            self.assertEqual(illusts['items'][0]['illust_id'], 10011)
            self.assertEqual(illust_detail['illust']['illust_id'], 10011)
            self.assertEqual(related_users['items'][0]['user_id'], 2001)
            self.assertEqual(related_illusts['items'][0]['illust_id'], 20011)


if __name__ == '__main__':
    unittest.main()
