from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.application import ApplicationFacade
from pixiv_artist_recsys.pixiv.models import PagedResult, PixivIllustDetail, PixivIllustSummary, PixivUserDetail, PixivUserSummary
from pixiv_artist_recsys.runtime import AppRuntime
from pixiv_artist_recsys.utils.progress import ProgressEvent, emit


class FakeProgressClient:
    def fetch_following_users(self, *, user_id: int, restrict: str = 'public', offset: int | None = None):
        if offset:
            return PagedResult(items=[], next_url=None)
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
        }
        return PagedResult(items=mapping.get(user_id, []), next_url=None)

    def fetch_illust_detail(self, *, illust_id: int):
        payloads = {
            10011: self._detail(10011, 1001, ['Blue Hair', '制服'], 520, 5200, 25),
            10012: self._detail(10012, 1001, ['Blue Hair'], 480, 4800, 22),
            10021: self._detail(10021, 1002, ['blue hair', '夜景'], 500, 5000, 20),
            10022: self._detail(10022, 1002, ['blue hair'], 460, 4600, 18),
            20011: self._detail(20011, 2001, ['blue hair', '制服'], 650, 6500, 30),
            20012: self._detail(20012, 2001, ['blue hair', '制服'], 600, 6000, 28),
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
            user=PixivUserSummary(user_id=user_id, name=f'user-{user_id}', account=f'account_{user_id}'),
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


class ProgressTests(unittest.TestCase):
    def test_emit_noop_when_callback_missing(self) -> None:
        emit(None, stage='x', event='start', message='noop')

    def test_emit_delivers_event(self) -> None:
        seen: list[ProgressEvent] = []
        emit(seen.append, stage='following_sync', event='progress', current=30, total=0, message='page', pages_fetched=1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].stage, 'following_sync')
        self.assertEqual(seen[0].current, 30)
        self.assertEqual(seen[0].meta['pages_fetched'], 1)

    def test_full_recommend_emits_stage_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {'PIXIV_ARTIST_RECSYS_DATA_DIR': str(Path(tmpdir) / 'data')}
            runtime = AppRuntime.create(env=env, now_fn=lambda: 100)
            runtime.prepare()
            facade = ApplicationFacade(
                runtime=runtime,
                pixiv_client_factory=lambda **_: FakeProgressClient(),
            )
            events: list[ProgressEvent] = []
            payload = facade.full_recommend_payload(
                seed_user_id=7,
                refresh_token='dummy-refresh-token',
                followed_artist_limit=2,
                candidate_artist_limit=2,
                max_results=5,
                min_bookmarks=100,
                min_score=0.1,
                diversity_per_tag=1,
                on_progress=events.append,
            )
            self.assertEqual(payload['recommended_artist_ids'], [2001])
            stages = {e.stage for e in events}
            kinds = {(e.stage, e.event) for e in events}
            self.assertIn('pipeline', stages)
            self.assertIn('following_sync', stages)
            self.assertIn('hydrate_followed', stages)
            self.assertIn('candidates', stages)
            self.assertIn(('pipeline', 'start'), kinds)
            self.assertIn(('pipeline', 'done'), kinds)
            self.assertIn(('following_sync', 'progress'), kinds)
            self.assertTrue(any(e.event == 'progress' for e in events if e.stage == 'hydrate_followed'))


if __name__ == '__main__':
    unittest.main()
