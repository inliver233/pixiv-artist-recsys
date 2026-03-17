from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.application import ApplicationFacade
from pixiv_artist_recsys.api import ApiRequest, ApiRouter, ApiServer
from pixiv_artist_recsys.domain.models import Artist, Illust, RecommendationItem, RecommendationRun, SeedUser
from pixiv_artist_recsys.pixiv.models import PagedResult, PixivIllustDetail, PixivIllustSummary, PixivUserSummary
from pixiv_artist_recsys.runtime import AppRuntime


class FakeLiveClient:
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
            1001: [PixivIllustSummary(illust_id=10011, user_id=1001, title='f-a-1')],
            1002: [PixivIllustSummary(illust_id=10021, user_id=1002, title='f-b-1')],
            2001: [PixivIllustSummary(illust_id=20011, user_id=2001, title='c-a-1')],
        }
        return PagedResult(items=mapping.get(user_id, []), next_url=None)

    def fetch_illust_detail(self, *, illust_id: int):
        payloads = {
            10011: self._detail(10011, 1001, ['Blue Hair', '制服'], 40, 400, 5),
            10021: self._detail(10021, 1002, ['blue hair', '夜景'], 30, 300, 3),
            20011: self._detail(20011, 2001, ['blue hair', '制服'], 150, 1500, 12),
        }
        return payloads[illust_id]

    def fetch_user_related(self, *, seed_user_id: int, offset: int | None = None):
        mapping = {
            1001: [PixivUserSummary(user_id=2001, name='candidate-a', account='candidate_a')],
            1002: [],
        }
        return PagedResult(items=mapping.get(seed_user_id, []), next_url=None)

    def fetch_illust_related(self, *, illust_id: int):
        mapping = {
            10011: [PixivIllustSummary(illust_id=20011, user_id=2001, title='related-a')],
            10021: [],
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


class ApiRouterTests(unittest.TestCase):
    def _runtime(self, tmpdir: str, **extra_env: str) -> AppRuntime:
        env = {
            'PIXIV_ARTIST_RECSYS_DATA_DIR': str(Path(tmpdir) / 'data'),
            'PIXIV_ARTIST_RECSYS_API_HOST': '127.0.0.1',
            'PIXIV_ARTIST_RECSYS_API_PORT': '0',
        }
        env.update(extra_env)
        runtime = AppRuntime.create(env=env, now_fn=lambda: 100)
        runtime.prepare()
        return runtime

    @staticmethod
    def _request(router: ApiRouter, method: str, target: str, payload: dict | None = None):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else b''
        return router.handle(ApiRequest.from_target(method=method, target=target, body=body))

    def _seed_rank_data(self, runtime: AppRuntime) -> None:
        repo = runtime.repository
        repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
        repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
        repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
        repo.replace_user_taste_profile(seed_user_id=7, weights=[('blue_hair', 0.8), ('制服', 0.2)])

        repo.upsert_artist(Artist(user_id=2001, name='candidate-a', account='candidate_a'))
        repo.upsert_illust(Illust(illust_id=9001, user_id=2001, title='candidate-illust', total_bookmarks=120, total_view=1500, total_comments=12))
        repo.replace_illust_tags(illust_id=9001, tags=['blue hair', '制服'])
        repo.replace_artist_candidates(seed_user_id=7, candidates=[(2001, 'user_related', 'user:1001', 1.0, 'rel')])

    def test_router_returns_health_config_and_proxy_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir, PIXIV_ARTIST_RECSYS_API_HOST='0.0.0.0', PIXIV_ARTIST_RECSYS_API_PORT='9911')
            router = ApiRouter(runtime=runtime)

            health = self._request(router, 'GET', '/health')
            config = self._request(router, 'GET', '/config')
            proxy_state = self._request(router, 'GET', '/proxy-state')

            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.payload['status'], 'ok')
            self.assertEqual(config.payload['api']['host'], '0.0.0.0')
            self.assertEqual(config.payload['api']['port'], 9911)
            self.assertFalse(proxy_state.payload['enabled'])

    def test_router_supports_runs_feedback_and_recommendation_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir)
            self._seed_rank_data(runtime)
            runtime.repository.record_run(
                RecommendationRun(
                    seed_user_id=7,
                    run_id='run-api-1',
                    mode='live-heuristic',
                    items=[RecommendationItem(artist=Artist(user_id=2001, name='candidate-a'), score=1.2, confidence=0.9, reasons=['ok'], top_illust_ids=[9001])],
                )
            )
            runtime.repository.upsert_run_audit(run_id='run-api-1', seed_user_id=7, summary={'ranked': {'artist_user_ids': [2001]}})
            router = ApiRouter(runtime=runtime)

            runs = self._request(router, 'GET', '/runs?limit=5')
            run_detail = self._request(router, 'GET', '/runs/run-api-1')
            run_audit = self._request(router, 'GET', '/runs/run-api-1/audit')
            recommend = self._request(router, 'GET', '/recommend/from-store?seed_user_id=7&max_results=5&diversity_per_tag=1')

            self.assertEqual(runs.status_code, 200)
            self.assertEqual(runs.payload['count'], 1)
            self.assertTrue(run_detail.payload['found'])
            self.assertEqual(run_detail.payload['run']['run_id'], 'run-api-1')
            self.assertEqual(run_audit.payload['audit']['ranked']['artist_user_ids'], [2001])
            self.assertEqual(recommend.payload['seed_user_id'], 7)
            self.assertEqual(recommend.payload['item_count'], 1)
            self.assertEqual(recommend.payload['items'][0]['artist_user_id'], 2001)

    def test_router_supports_live_hydrate_profile_and_full_recommend_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir)
            application = ApplicationFacade(
                runtime=runtime,
                pixiv_client_factory=lambda **_: FakeLiveClient(),
            )
            router = ApiRouter(runtime=runtime, application=application)

            hydrate = self._request(
                router,
                'POST',
                '/hydrate/followed-illusts',
                payload={
                    'seed_user_id': 7,
                    'refresh_token': 'dummy-refresh-token',
                    'per_artist_limit': 2,
                },
            )
            profile = self._request(
                router,
                'POST',
                '/profile/build',
                payload={
                    'seed_user_id': 7,
                    'top_n_tags': 10,
                    'top_n_pairs': 10,
                },
            )
            full = self._request(
                router,
                'POST',
                '/recommend/full',
                payload={
                    'seed_user_id': 7,
                    'refresh_token': 'dummy-refresh-token',
                    'followed_artist_limit': 1,
                    'candidate_artist_limit': 1,
                    'max_results': 5,
                    'min_bookmarks': 100,
                    'min_score': 1.0,
                    'diversity_per_tag': 1,
                },
            )

            self.assertEqual(hydrate.status_code, 200)
            self.assertEqual(hydrate.payload['artists_processed'], 2)
            self.assertGreaterEqual(hydrate.payload['illusts_upserted'], 2)
            self.assertEqual(profile.status_code, 200)
            self.assertEqual(profile.payload['seed_user_id'], 7)
            self.assertTrue(profile.payload['top_tags'])
            self.assertEqual(full.status_code, 200)
            self.assertEqual(full.payload['recommended_artist_ids'], [2001])
            self.assertEqual(full.payload['filters']['diversity_per_tag'], 1)

    def test_router_post_feedback_records_negative_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir)
            repo = runtime.repository
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=3001, name='feedback-artist'))
            repo.upsert_illust(Illust(illust_id=93001, user_id=3001, title='feedback-illust'))
            repo.replace_illust_tags(illust_id=93001, tags=['gore', 'blue hair'])
            router = ApiRouter(runtime=runtime)

            response = self._request(
                router,
                'POST',
                '/feedback',
                payload={
                    'seed_user_id': 7,
                    'artist_user_id': 3001,
                    'action': 'block',
                    'source_run_id': 'run-feedback-1',
                },
            )
            profile = self._request(router, 'GET', '/feedback/profile?seed_user_id=7&top_n_tags=10')

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.payload['blocked_artist_ids'], [3001])
            self.assertEqual(profile.payload['blocked_artist_ids'], [3001])
            self.assertEqual(profile.payload['negative_tags'][0]['tag'], 'blue_hair')

    def test_router_returns_bad_request_for_missing_required_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir)
            router = ApiRouter(runtime=runtime)

            response = self._request(router, 'GET', '/recommend/from-store')

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.payload['error'], 'bad_request')

    def test_api_server_serves_json_over_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(tmpdir)
            server = ApiServer(runtime=runtime, host='127.0.0.1', port=0)
            httpd = server.create_http_server()
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                opener = build_opener(ProxyHandler({}))
                with opener.open(f'http://127.0.0.1:{httpd.server_port}/health') as response:
                    payload = json.loads(response.read().decode('utf-8'))
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

            self.assertEqual(payload['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
