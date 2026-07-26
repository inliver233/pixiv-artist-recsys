from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .schema import SCHEMA_STATEMENTS

# Applied to every new connection. WAL persists in the DB file; the rest are
# per-connection settings.
_CONNECTION_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=5000",
)


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Columns added after first deploy (pre-user_version era) + core indexes."""
    rows = conn.execute("PRAGMA table_info(illusts)").fetchall()
    existing = {str(row[1]) for row in rows}
    if 'illust_type' not in existing:
        conn.execute("ALTER TABLE illusts ADD COLUMN illust_type TEXT NOT NULL DEFAULT ''")
    if 'page_count' not in existing:
        conn.execute("ALTER TABLE illusts ADD COLUMN page_count INTEGER NOT NULL DEFAULT 1")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_illusts_user_id ON illusts(user_id)")


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Freshness columns for hydrate/sync skip-if-fresh (0 = never → always eligible)."""
    artist_cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(artists)").fetchall()}
    if 'hydrated_at_epoch' not in artist_cols:
        conn.execute("ALTER TABLE artists ADD COLUMN hydrated_at_epoch INTEGER NOT NULL DEFAULT 0")
    illust_cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(illusts)").fetchall()}
    if 'fetched_at_epoch' not in illust_cols:
        conn.execute("ALTER TABLE illusts ADD COLUMN fetched_at_epoch INTEGER NOT NULL DEFAULT 0")
    seed_cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(seed_users)").fetchall()}
    if 'last_following_sync_epoch' not in seed_cols:
        conn.execute("ALTER TABLE seed_users ADD COLUMN last_following_sync_epoch INTEGER NOT NULL DEFAULT 0")


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Thumbnail URL for the local HTML report (empty for legacy rows)."""
    illust_cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(illusts)").fetchall()}
    if 'image_url' not in illust_cols:
        conn.execute("ALTER TABLE illusts ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")


# Ordered schema migrations tracked via PRAGMA user_version; each runs at most once.
MIGRATIONS: tuple[tuple[int, Callable[[sqlite3.Connection], None]], ...] = (
    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
)


class SQLiteDatabase:
    """SQLite access with WAL and optional per-thread connection reuse.

    persistent=True keeps one connection per thread for the process lifetime
    (AppRuntime uses this); persistent=False closes after each block so
    short-lived callers do not hold Windows file locks (temp dirs in tests).

    transaction() groups nested connect() calls into a single commit so bulk
    write paths (following sync, hydration) avoid per-statement fsync.
    """

    def __init__(self, db_path: Path, *, persistent: bool = False):
        self.db_path = Path(db_path)
        self.persistent = bool(persistent)
        self._local = threading.local()
        self._dir_ready = False

    def _acquire(self) -> sqlite3.Connection:
        if not self._dir_ready:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._dir_ready = True
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        for pragma in _CONNECTION_PRAGMAS:
            conn.execute(pragma)
        return conn

    def _thread_conn(self) -> sqlite3.Connection | None:
        return getattr(self._local, 'conn', None)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        active = getattr(self._local, 'active', None)
        if active is not None:
            # Nested inside transaction(): reuse it, outer block commits.
            yield active
            return
        conn = self._thread_conn()
        if conn is None:
            conn = self._acquire()
            if self.persistent:
                self._local.conn = conn
        try:
            yield conn
            conn.commit()
        finally:
            if not self.persistent:
                conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One commit for many connect() calls; rolls back on error."""
        if getattr(self._local, 'active', None) is not None:
            yield self._local.active
            return
        conn = self._thread_conn()
        opened_here = conn is None
        if conn is None:
            conn = self._acquire()
            if self.persistent:
                self._local.conn = conn
        self._local.active = conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._local.active = None
            if not self.persistent and opened_here:
                conn.close()

    def close(self) -> None:
        """Close the current thread's cached connection (persistent mode)."""
        conn = self._thread_conn()
        if conn is not None:
            try:
                conn.close()
            finally:
                self._local.conn = None

    def initialize(self) -> None:
        with self.transaction() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            self._apply_migrations(conn)

    @staticmethod
    def _apply_migrations(conn: sqlite3.Connection) -> None:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        for version, migrate in MIGRATIONS:
            if version <= current:
                continue
            migrate(conn)
            conn.execute(f"PRAGMA user_version = {int(version)}")
