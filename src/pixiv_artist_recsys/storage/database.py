from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .schema import SCHEMA_STATEMENTS


class SQLiteDatabase:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            self._migrate_illust_columns(conn)

    @staticmethod
    def _migrate_illust_columns(conn: sqlite3.Connection) -> None:
        """Add columns introduced after first deploy without rebuilding the DB."""
        rows = conn.execute("PRAGMA table_info(illusts)").fetchall()
        existing = {str(row[1]) for row in rows}
        if 'illust_type' not in existing:
            conn.execute("ALTER TABLE illusts ADD COLUMN illust_type TEXT NOT NULL DEFAULT ''")
        if 'page_count' not in existing:
            conn.execute("ALTER TABLE illusts ADD COLUMN page_count INTEGER NOT NULL DEFAULT 1")
