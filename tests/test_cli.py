from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class CLITests(unittest.TestCase):
    def _run_cli(self, *args: str, tmpdir: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        env["PIXIV_ARTIST_RECSYS_DATA_DIR"] = str(Path(tmpdir) / "data")
        return subprocess.run(
            [sys.executable, "-m", "pixiv_artist_recsys.cli", *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

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


if __name__ == "__main__":
    unittest.main()
