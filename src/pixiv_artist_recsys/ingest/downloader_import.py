from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.models import Illust
from ..storage.repositories import RecommendationRepository


@dataclass(slots=True)
class DownloaderImportResult:
    source_path: str
    source_rows: int
    illusts_imported: int
    illusts_skipped_existing: int
    artists_touched: int

    def to_dict(self) -> dict[str, Any]:
        return {
            'source_path': self.source_path,
            'source_rows': self.source_rows,
            'illusts_imported': self.illusts_imported,
            'illusts_skipped_existing': self.illusts_skipped_existing,
            'artists_touched': self.artists_touched,
        }


class DownloaderStatsImportService:
    """One-shot, optional import of pixiv-downloader's follow-image stats.

    Reads pixiv_follow_image (bookmark/view/like counts the downloader keeps
    up to date for followed artists) from its SQLite in read-only mode and
    copies rows into our own illusts table. A copy, not an ATTACH dependency:
    the pipeline never needs the downloader DB mounted — run this command when
    the drive happens to be there, skip it otherwise.

    Only rows missing locally are inserted (tags stay empty → tag-dependent
    stages still hydrate normally, but bookmark-based priority/quality anchors
    get real numbers for free). Existing rows are never overwritten — live
    hydration data wins.
    """

    def __init__(self, *, repository: RecommendationRepository) -> None:
        self.repository = repository

    def import_stats(
        self,
        *,
        downloader_db_path: str | Path,
        batch_size: int = 500,
    ) -> DownloaderImportResult:
        source_path = Path(downloader_db_path)
        if not source_path.exists():
            raise FileNotFoundError(f'downloader db not found: {source_path}')

        source = sqlite3.connect(f'file:{source_path.as_posix()}?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        try:
            source_rows = int(source.execute('SELECT COUNT(*) FROM pixiv_follow_image').fetchone()[0])
            existing_ids = self._existing_illust_ids()
            imported = 0
            skipped = 0
            artists: set[int] = set()
            batch: list[Illust] = []
            cursor = source.execute(
                """
                SELECT image_id, member_id, title, create_date, page_count, mode,
                       bookmark_count, like_count, view_count
                FROM pixiv_follow_image
                """
            )
            for row in cursor:
                illust_id = int(row['image_id'] or 0)
                user_id = int(row['member_id'] or 0)
                if illust_id <= 0 or user_id <= 0:
                    continue
                if illust_id in existing_ids:
                    skipped += 1
                    continue
                mode = str(row['mode'] or '').strip().lower()
                batch.append(
                    Illust(
                        illust_id=illust_id,
                        user_id=user_id,
                        title=str(row['title'] or ''),
                        create_date=str(row['create_date'] or ''),
                        total_bookmarks=max(0, int(row['bookmark_count'] or 0)),
                        total_view=max(0, int(row['view_count'] or 0)),
                        total_comments=0,
                        ai_type=0,
                        x_restrict=0,
                        illust_type='manga' if mode == 'manga' else ('ugoira' if mode == 'ugoira' else 'illust'),
                        page_count=max(1, int(row['page_count'] or 1)),
                    )
                )
                artists.add(user_id)
                imported += 1
                if len(batch) >= max(1, int(batch_size)):
                    self._flush(batch)
                    batch = []
            if batch:
                self._flush(batch)
        finally:
            source.close()

        return DownloaderImportResult(
            source_path=str(source_path),
            source_rows=source_rows,
            illusts_imported=imported,
            illusts_skipped_existing=skipped,
            artists_touched=len(artists),
        )

    def _existing_illust_ids(self) -> set[int]:
        with self.repository.database.connect() as conn:
            rows = conn.execute('SELECT illust_id FROM illusts').fetchall()
        return {int(r['illust_id']) for r in rows}

    def _flush(self, batch: list[Illust]) -> None:
        with self.repository.transaction():
            for illust in batch:
                self.repository.upsert_illust(illust)
