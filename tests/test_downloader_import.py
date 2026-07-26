from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, Illust
from pixiv_artist_recsys.ingest import DownloaderStatsImportService
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


def _make_downloader_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE pixiv_follow_image (
            image_id INTEGER PRIMARY KEY,
            member_id INTEGER,
            title TEXT,
            caption TEXT,
            create_date TEXT,
            page_count INTEGER,
            mode TEXT,
            bookmark_count INTEGER,
            like_count INTEGER,
            view_count INTEGER,
            created_date TEXT,
            last_update_date TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO pixiv_follow_image (image_id, member_id, title, create_date, page_count, mode, bookmark_count, like_count, view_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


class DownloaderImportTests(unittest.TestCase):
    def test_imports_missing_rows_and_never_overwrites_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dl_path = Path(tmpdir) / 'downloader.sqlite'
            _make_downloader_db(
                dl_path,
                [
                    (9001, 1001, 'new-work', '2026-01-01', 1, 'illust', 500, 50, 5000),
                    (9002, 1001, 'manga-work', '2026-01-02', 8, 'manga', 300, 30, 3000),
                    (9003, 1002, 'existing-work', '2026-01-03', 1, 'illust', 999, 99, 9999),
                    (0, 1001, 'bad-id', '', 1, 'illust', 1, 0, 1),
                ],
            )
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'app.sqlite3'))
            repo.initialize()
            repo.upsert_artist(Artist(user_id=1002, name='a'))
            # 9003 already hydrated live with different (authoritative) numbers.
            repo.upsert_illust(Illust(illust_id=9003, user_id=1002, title='live', total_bookmarks=123))

            result = DownloaderStatsImportService(repository=repo).import_stats(downloader_db_path=dl_path)

            self.assertEqual(result.illusts_imported, 2)
            self.assertEqual(result.illusts_skipped_existing, 1)
            self.assertEqual(result.artists_touched, 1)

            imported = {i.illust_id: i for i in repo.fetch_illusts_for_artist(artist_user_id=1001)}
            self.assertEqual(imported[9001].total_bookmarks, 500)
            self.assertEqual(imported[9002].illust_type, 'manga')
            self.assertEqual(imported[9002].page_count, 8)
            # Existing row untouched.
            live = {i.illust_id: i for i in repo.fetch_illusts_for_artist(artist_user_id=1002)}
            self.assertEqual(live[9003].total_bookmarks, 123)
            self.assertEqual(live[9003].title, 'live')

    def test_missing_db_raises_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'app.sqlite3'))
            repo.initialize()
            with self.assertRaises(FileNotFoundError):
                DownloaderStatsImportService(repository=repo).import_stats(
                    downloader_db_path=Path(tmpdir) / 'nope.sqlite'
                )


if __name__ == '__main__':
    unittest.main()
