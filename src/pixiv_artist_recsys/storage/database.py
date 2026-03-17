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
