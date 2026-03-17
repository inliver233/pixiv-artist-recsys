from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, RecommendationItem, RecommendationRun, SeedUser
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class StorageTests(unittest.TestCase):
    def test_initialize_and_persist_core_entities(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "app.sqlite3"
            repo = RecommendationRepository(SQLiteDatabase(db_path))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=1, refresh_token_ref="masked:token"))
            repo.upsert_artist(Artist(user_id=100, name="artist-a"))
            repo.record_run(
                RecommendationRun(
                    seed_user_id=1,
                    run_id="run-1",
                    items=[RecommendationItem(artist=Artist(user_id=100, name="artist-a"), score=0.9, confidence=0.8)],
                )
            )

            self.assertEqual(repo.count_rows("seed_users"), 1)
            self.assertEqual(repo.count_rows("artists"), 1)
            self.assertEqual(repo.count_rows("recommendation_runs"), 1)
            self.assertEqual(repo.count_rows("recommendation_items"), 1)


if __name__ == "__main__":
    unittest.main()
