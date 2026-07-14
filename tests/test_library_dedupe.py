from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, SeedUser
from pixiv_artist_recsys.storage import LibraryDedupeService, RecommendationRepository, SQLiteDatabase


class LibraryDedupeTests(unittest.TestCase):
    def test_removes_orphans_and_aligns_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SQLiteDatabase(Path(tmpdir) / 'dedupe.sqlite3')
            repo = RecommendationRepository(db)
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=1, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=10, name='kept', is_followed=True))
            repo.upsert_artist(Artist(user_id=11, name='edge-only', is_followed=False))
            repo.upsert_following_edge(seed_user_id=1, artist_user_id=10)
            repo.upsert_following_edge(seed_user_id=1, artist_user_id=11)

            with db.connect() as conn:
                conn.execute('PRAGMA foreign_keys=OFF')
                conn.execute(
                    'INSERT INTO seed_user_following_artists (seed_user_id, artist_user_id) VALUES (1, 999)'
                )
                conn.execute(
                    "INSERT INTO illusts (illust_id, user_id, title) VALUES (1, 10, 'ok')"
                )
                conn.execute(
                    "INSERT INTO illusts (illust_id, user_id, title) VALUES (2, 888, 'orphan')"
                )
                conn.execute("INSERT INTO illust_tags (illust_id, tag) VALUES (1, 'ok')")
                conn.execute("INSERT INTO illust_tags (illust_id, tag) VALUES (2, 'gone')")

            result = LibraryDedupeService(database=db).dedupe(vacuum=False)
            self.assertEqual(result.orphan_edges_removed, 1)
            self.assertEqual(result.orphan_illusts_removed, 1)
            self.assertEqual(result.orphan_illust_tags_removed, 1)
            self.assertEqual(result.followed_flags_aligned, 1)
            self.assertEqual(sorted(repo.list_following_artist_ids(seed_user_id=1)), [10, 11])
            self.assertTrue(repo.fetch_artist(artist_user_id=11).is_followed)

            with db.connect() as conn:
                self.assertEqual(
                    conn.execute('SELECT COUNT(*) AS c FROM seed_user_following_artists').fetchone()['c'],
                    2,
                )
                self.assertEqual(conn.execute('SELECT COUNT(*) AS c FROM illusts').fetchone()['c'], 1)
                self.assertEqual(conn.execute('SELECT COUNT(*) AS c FROM illust_tags').fetchone()['c'], 1)
                self.assertEqual(
                    conn.execute('SELECT COUNT(*) AS c FROM artists WHERE is_followed=1').fetchone()['c'],
                    2,
                )


if __name__ == '__main__':
    unittest.main()
