from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests import test_support  # noqa: F401
from pixiv_artist_recsys import cli
from pixiv_artist_recsys.domain.models import Artist, Illust, SeedUser
from pixiv_artist_recsys.pixiv.models import PagedResult, PixivIllustDetail, PixivIllustSummary, PixivUserSummary
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class FakeHydrationClient:
    def fetch_user_illusts(self, *, user_id: int, type_: str = 'illust', offset: int | None = None):
        return PagedResult(items=[PixivIllustSummary(illust_id=user_id * 10 + 1, user_id=user_id, title=f'illust-{user_id}')], next_url=None)

    def fetch_illust_detail(self, *, illust_id: int):
        user_id = illust_id // 10
        return PixivIllustDetail(
            illust=PixivIllustSummary(
                illust_id=illust_id,
                user_id=user_id,
                title=f'illust-{illust_id}',
                create_date='2026-03-01T00:00:00+00:00',
                total_bookmarks=80,
                total_view=800,
                total_comments=8,
            ),
            tags=['blue hair', '制服'],
            original_image_url=f'https://i.pximg.net/{illust_id}.jpg',
            page_count=1,
            ai_type=0,
            x_restrict=0,
        )


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
        mapping = {
            1001: [PixivIllustSummary(illust_id=10011, user_id=1001, title='f-a-1')],
            1002: [PixivIllustSummary(illust_id=10021, user_id=1002, title='f-b-1')],
            2001: [PixivIllustSummary(illust_id=20011, user_id=2001, title='c-a-1')],
            2002: [PixivIllustSummary(illust_id=20021, user_id=2002, title='c-b-1')],
        }
        return PagedResult(items=mapping.get(user_id, []), next_url=None)

    def fetch_illust_detail(self, *, illust_id: int):
        payloads = {
            10011: self._detail(10011, 1001, ['Blue Hair', '制服'], 40, 400, 5),
            10021: self._detail(10021, 1002, ['blue hair', '夜景'], 30, 300, 3),
            20011: self._detail(20011, 2001, ['blue hair', '制服'], 150, 1500, 12),
            20021: self._detail(20021, 2002, ['风景'], 20, 200, 2),
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
            10021: [PixivIllustSummary(illust_id=20021, user_id=2002, title='related-b')],
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


class CLITests(unittest.TestCase):
    def _env_for_tmpdir(self, tmpdir: str) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        env["PIXIV_ARTIST_RECSYS_DATA_DIR"] = str(Path(tmpdir) / "data")
        return env

    def _db_path(self, tmpdir: str) -> Path:
        return Path(tmpdir) / 'data' / 'runtime' / 'pixiv_artist_recsys.sqlite3'

    def _repo(self, tmpdir: str) -> RecommendationRepository:
        db_path = self._db_path(tmpdir)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        repo = RecommendationRepository(SQLiteDatabase(db_path))
        repo.initialize()
        return repo

    def _run_cli(self, *args: str, tmpdir: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pixiv_artist_recsys.cli", *args],
            cwd=ROOT,
            env=self._env_for_tmpdir(tmpdir),
            text=True,
            capture_output=True,
            check=True,
        )

    def _run_main_inprocess(self, *args: str, tmpdir: str) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with patch.dict(os.environ, self._env_for_tmpdir(tmpdir), clear=False):
            with redirect_stdout(stdout):
                exit_code = cli.main(list(args))
        return exit_code, json.loads(stdout.getvalue())

    def test_show_config_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_cli("show-config", tmpdir=tmpdir)
            payload = json.loads(result.stdout)
            self.assertIn("db_path", payload)

    def test_dry_run_recommend_outputs_placeholder_artist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_cli("dry-run-recommend", "--seed-user-id", "11", tmpdir=tmpdir)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["seed_user_id"], 11)
            self.assertTrue(payload["items"])
            self.assertEqual(payload["items"][0]["artist_name"], "dry-run-artist")

    def test_build_profile_outputs_top_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self._repo(tmpdir)
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            for artist_id in [1001, 1002]:
                repo.upsert_artist(Artist(user_id=artist_id, name=f'artist-{artist_id}', is_followed=True))
                repo.upsert_following_edge(seed_user_id=7, artist_user_id=artist_id)
            repo.upsert_illust(Illust(illust_id=1, user_id=1001, title='a'))
            repo.replace_illust_tags(illust_id=1, tags=['Blue Hair', '制服'])
            repo.upsert_illust(Illust(illust_id=2, user_id=1002, title='b'))
            repo.replace_illust_tags(illust_id=2, tags=['blue hair', '夜景'])

            exit_code, payload = self._run_main_inprocess('build-profile', '--seed-user-id', '7', tmpdir=tmpdir)

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['seed_user_id'], 7)
            self.assertEqual(payload['top_tags'][0]['tag'], 'blue_hair')
            self.assertGreater(len(payload['top_pairs']), 0)

    def test_recommend_from_store_outputs_ranked_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self._repo(tmpdir)
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.replace_user_taste_profile(seed_user_id=7, weights=[('blue_hair', 0.8), ('制服', 0.2)])
            repo.upsert_artist(Artist(user_id=2001, name='candidate-a', account='candidate_a'))
            repo.upsert_illust(Illust(illust_id=9001, user_id=2001, title='c1', total_bookmarks=100, total_view=1000, total_comments=10))
            repo.replace_illust_tags(illust_id=9001, tags=['blue hair', '制服'])
            repo.replace_artist_candidates(seed_user_id=7, candidates=[(2001, 'user_related', 'user:1001', 1.0, 'rel')])

            exit_code, payload = self._run_main_inprocess('recommend-from-store', '--seed-user-id', '7', '--max-results', '5', tmpdir=tmpdir)

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['item_count'], 1)
            self.assertEqual(payload['items'][0]['artist_user_id'], 2001)
            self.assertTrue(payload['items'][0]['reasons'])

    def test_hydrate_followed_illusts_persists_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self._repo(tmpdir)
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='artist-1', is_followed=True))
            repo.upsert_artist(Artist(user_id=1002, name='artist-2', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1002)

            with patch('pixiv_artist_recsys.cli._build_pixiv_client', return_value=FakeHydrationClient()):
                exit_code, payload = self._run_main_inprocess(
                    'hydrate-followed-illusts',
                    '--seed-user-id', '7',
                    '--refresh-token', 'dummy-refresh-token',
                    '--per-artist-limit', '2',
                    tmpdir=tmpdir,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['artists_processed'], 2)
            self.assertEqual(payload['illusts_upserted'], 2)
            self.assertEqual(repo.count_rows('illusts'), 2)

    def test_full_recommend_runs_pipeline_and_returns_uid_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('pixiv_artist_recsys.cli._build_pixiv_client', return_value=FakeFullRecommendClient()):
                exit_code, payload = self._run_main_inprocess(
                    'full-recommend',
                    '--seed-user-id', '7',
                    '--refresh-token', 'dummy-refresh-token',
                    '--followed-artist-limit', '1',
                    '--candidate-artist-limit', '1',
                    '--max-results', '5',
                    '--allow-ai',
                    '--min-bookmarks', '100',
                    '--min-score', '1.0',
                    tmpdir=tmpdir,
                )

            repo = self._repo(tmpdir)
            seed_user = repo.fetch_seed_user(user_id=7)
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['seed_user_id'], 7)
            self.assertEqual(payload['filters']['allow_ai'], True)
            self.assertEqual(payload['filters']['allow_r18'], False)
            self.assertEqual(payload['filters']['min_bookmarks'], 100)
            self.assertEqual(payload['filters']['min_score'], 1.0)
            self.assertEqual(payload['recommended_artist_ids'], [2001])
            self.assertEqual(payload['stats']['candidate_count'], 2)
            self.assertTrue(payload['items'])
            self.assertTrue(seed_user.allow_ai)
            self.assertFalse(seed_user.allow_r18)
            self.assertEqual(repo.count_rows('recommendation_runs'), 1)
            self.assertEqual(repo.count_rows('recommendation_items'), len(payload['items']))


if __name__ == "__main__":
    unittest.main()
