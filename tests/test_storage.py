from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, Illust, RecommendationItem, RecommendationRun, SeedUser
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


def _make_illust(illust_id: int, user_id: int, bookmarks: int) -> Illust:
    return Illust(
        illust_id=illust_id,
        user_id=user_id,
        title=f"illust-{illust_id}",
        create_date="2026-01-01T00:00:00+00:00",
        total_bookmarks=bookmarks,
        total_view=bookmarks * 10,
        total_comments=1,
        ai_type=0,
        x_restrict=0,
    )


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

    def test_initialize_applies_user_version_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SQLiteDatabase(Path(tmpdir) / "app.sqlite3")
            db.initialize()
            # Re-initialize is idempotent.
            db.initialize()
            with db.connect() as conn:
                version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                indexes = {
                    str(row[1])
                    for row in conn.execute("PRAGMA index_list(illusts)").fetchall()
                }
            self.assertGreaterEqual(version, 1)
            self.assertIn("idx_illusts_user_id", indexes)

    def test_fetch_max_bookmarks_by_artist_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / "app.sqlite3"))
            repo.initialize()
            repo.upsert_artist(Artist(user_id=1, name="a"))
            repo.upsert_artist(Artist(user_id=2, name="b"))
            repo.upsert_artist(Artist(user_id=3, name="c-no-illusts"))
            repo.upsert_illust(_make_illust(11, 1, 100))
            repo.upsert_illust(_make_illust(12, 1, 500))
            repo.upsert_illust(_make_illust(21, 2, 40))

            result = repo.fetch_max_bookmarks_by_artist(artist_user_ids=[1, 2, 3])
            self.assertEqual(result, {1: 500, 2: 40})

            all_result = repo.fetch_max_bookmarks_by_artist()
            self.assertEqual(all_result, {1: 500, 2: 40})

    def test_fetch_illusts_and_artists_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / "app.sqlite3"))
            repo.initialize()
            repo.upsert_artist(Artist(user_id=1, name="a"))
            repo.upsert_artist(Artist(user_id=2, name="b"))
            repo.upsert_illust(_make_illust(11, 1, 100))
            repo.upsert_illust(_make_illust(12, 1, 500))
            repo.upsert_illust(_make_illust(21, 2, 40))

            illusts = repo.fetch_illusts_for_artists(artist_user_ids=[1, 2, 999])
            self.assertEqual([i.illust_id for i in illusts[1]], [12, 11])  # bookmarks desc
            self.assertEqual([i.illust_id for i in illusts[2]], [21])
            self.assertNotIn(999, illusts)
            # Batch matches single-artist fetch ordering.
            single = repo.fetch_illusts_for_artist(artist_user_id=1)
            self.assertEqual([i.illust_id for i in single], [i.illust_id for i in illusts[1]])

            artists = repo.fetch_artists_by_ids(artist_user_ids=[1, 2, 999])
            self.assertEqual(set(artists), {1, 2})
            self.assertEqual(artists[1].name, "a")

    def test_transaction_groups_writes_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / "app.sqlite3"))
            repo.initialize()
            with repo.transaction():
                repo.upsert_artist(Artist(user_id=1, name="a"))
                repo.upsert_artist(Artist(user_id=2, name="b"))
            self.assertEqual(repo.count_rows("artists"), 2)

            with self.assertRaises(RuntimeError):
                with repo.transaction():
                    repo.upsert_artist(Artist(user_id=3, name="c"))
                    raise RuntimeError("boom")
            self.assertEqual(repo.count_rows("artists"), 2)

    def test_persistent_database_reuses_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SQLiteDatabase(Path(tmpdir) / "app.sqlite3", persistent=True)
            try:
                db.initialize()
                with db.connect() as conn_a:
                    pass
                with db.connect() as conn_b:
                    pass
                self.assertIs(conn_a, conn_b)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
