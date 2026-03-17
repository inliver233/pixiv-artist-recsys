from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_support  # noqa: F401
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


if __name__ == '__main__':
    unittest.main()
