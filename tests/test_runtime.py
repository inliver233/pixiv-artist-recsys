from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.config import load_settings
from pixiv_artist_recsys.runtime import AppRuntime


class RuntimeTests(unittest.TestCase):
    def test_runtime_builds_repository_and_proxy_payload_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                'PIXIV_ARTIST_RECSYS_DATA_DIR': str(Path(tmpdir) / 'data'),
                'PIXIV_ARTIST_RECSYS_PROXY_URLS': 'http://proxy-a:8080,http://proxy-b:8080',
            }
            with patch.dict(os.environ, env, clear=False):
                runtime = AppRuntime.create(now_fn=lambda: 100)
                runtime.prepare()

            self.assertTrue(runtime.db_path.exists())
            proxy_state = runtime.proxy_state_payload()
            self.assertTrue(proxy_state['enabled'])
            self.assertEqual(len(proxy_state['proxies']), 2)

    def test_runtime_builds_static_access_token_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {'PIXIV_ARTIST_RECSYS_DATA_DIR': str(Path(tmpdir) / 'data')}
            with patch.dict(os.environ, env, clear=False):
                runtime = AppRuntime.create(now_fn=lambda: 100)
                runtime.prepare()
                client = runtime.build_pixiv_client(seed_user_id=7, access_token='static-token')

            self.assertIs(client.transport, runtime.transport)
            self.assertEqual(AppRuntime.resolve_refresh_token_ref(access_token='static-token'), 'access-token-only')

    def test_load_settings_reads_typed_api_and_recommendation_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                'PIXIV_ARTIST_RECSYS_DATA_DIR': str(Path(tmpdir) / 'data'),
                'PIXIV_ARTIST_RECSYS_API_HOST': '0.0.0.0',
                'PIXIV_ARTIST_RECSYS_API_PORT': '9911',
                'PIXIV_ARTIST_RECSYS_MAX_RESULTS': '17',
                'PIXIV_ARTIST_RECSYS_ALLOW_AI': 'yes',
                'PIXIV_ARTIST_RECSYS_ALLOW_R18': 'off',
                'PIXIV_ARTIST_RECSYS_MIN_BOOKMARKS': '66',
                'PIXIV_ARTIST_RECSYS_MIN_SCORE': '1.75',
                'PIXIV_ARTIST_RECSYS_DIVERSITY_PER_TAG': '4',
            }

            settings = load_settings(env=env)

            self.assertEqual(settings.api.host, '0.0.0.0')
            self.assertEqual(settings.api.port, 9911)
            self.assertEqual(settings.recommendation.max_results, 17)
            self.assertTrue(settings.recommendation.allow_ai)
            self.assertFalse(settings.recommendation.allow_r18)
            self.assertEqual(settings.recommendation.min_bookmarks, 66)
            self.assertEqual(settings.recommendation.min_score, 1.75)
            self.assertEqual(settings.recommendation.diversity_per_tag, 4)

    def test_resolve_refresh_token_accepts_project_and_alias_env_names(self) -> None:
        self.assertEqual(
            AppRuntime.resolve_refresh_token(env={'PIXIV_ARTIST_RECSYS_REFRESH_TOKEN': 'primary-token'}),
            'primary-token',
        )
        self.assertEqual(
            AppRuntime.resolve_refresh_token(env={'PIXIV_REFRESH_TOKEN': 'alias-token'}),
            'alias-token',
        )
        self.assertEqual(
            AppRuntime.resolve_refresh_token(
                env={
                    'PIXIV_ARTIST_RECSYS_REFRESH_TOKEN': 'primary-token',
                    'PIXIV_REFRESH_TOKEN': 'alias-token',
                }
            ),
            'primary-token',
        )
        self.assertEqual(
            AppRuntime.resolve_refresh_token(refresh_token='cli-token', env={'PIXIV_REFRESH_TOKEN': 'alias-token'}),
            'cli-token',
        )

    def test_resolve_following_refresh_token_does_not_fallback_to_ops_token(self) -> None:
        self.assertEqual(
            AppRuntime.resolve_following_refresh_token(
                env={
                    'PIXIV_ARTIST_RECSYS_FOLLOWING_REFRESH_TOKEN': 'mother-token',
                    'PIXIV_ARTIST_RECSYS_REFRESH_TOKEN': 'child-token',
                }
            ),
            'mother-token',
        )
        self.assertEqual(
            AppRuntime.resolve_following_refresh_token(env={'PIXIV_FOLLOWING_REFRESH_TOKEN': 'mother-alias'}),
            'mother-alias',
        )
        self.assertEqual(
            AppRuntime.resolve_following_refresh_token(env={'PIXIV_ARTIST_RECSYS_REFRESH_TOKEN': 'child-only'}),
            '',
        )
        self.assertEqual(
            AppRuntime.resolve_following_refresh_token(
                following_refresh_token='cli-mother',
                env={'PIXIV_ARTIST_RECSYS_FOLLOWING_REFRESH_TOKEN': 'env-mother'},
            ),
            'cli-mother',
        )

    def test_runtime_settings_payload_serializes_paths_and_nested_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                'PIXIV_ARTIST_RECSYS_DATA_DIR': str(Path(tmpdir) / 'data'),
                'PIXIV_ARTIST_RECSYS_API_HOST': '127.0.0.2',
                'PIXIV_ARTIST_RECSYS_API_PORT': '8765',
                'PIXIV_ARTIST_RECSYS_MIN_BOOKMARKS': '88',
            }
            runtime = AppRuntime.create(env=env, now_fn=lambda: 100)
            payload = runtime.settings_payload()

            self.assertEqual(payload['api']['host'], '127.0.0.2')
            self.assertEqual(payload['api']['port'], 8765)
            self.assertEqual(payload['recommendation']['min_bookmarks'], 88)
            self.assertTrue(str(payload['storage']['sqlite_path']).endswith('.sqlite3'))
            self.assertIn('runtime_dir', payload['paths'])


if __name__ == '__main__':
    unittest.main()
