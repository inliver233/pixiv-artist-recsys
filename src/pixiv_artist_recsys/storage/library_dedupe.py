from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .database import SQLiteDatabase


@dataclass(slots=True)
class LibraryDedupeResult:
    tables: dict[str, dict[str, int]] = field(default_factory=dict)
    orphan_edges_removed: int = 0
    orphan_illust_tags_removed: int = 0
    orphan_illusts_removed: int = 0
    duplicate_edges_removed: int = 0
    duplicate_artists_removed: int = 0
    duplicate_illusts_removed: int = 0
    duplicate_illust_tags_removed: int = 0
    duplicate_candidates_removed: int = 0
    duplicate_profile_tags_removed: int = 0
    duplicate_profile_pairs_removed: int = 0
    duplicate_negative_tags_removed: int = 0
    duplicate_rec_items_removed: int = 0
    followed_flags_aligned: int = 0
    vacuumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            'tables': self.tables,
            'duplicate_edges_removed': self.duplicate_edges_removed,
            'duplicate_artists_removed': self.duplicate_artists_removed,
            'duplicate_illusts_removed': self.duplicate_illusts_removed,
            'duplicate_illust_tags_removed': self.duplicate_illust_tags_removed,
            'duplicate_candidates_removed': self.duplicate_candidates_removed,
            'duplicate_profile_tags_removed': self.duplicate_profile_tags_removed,
            'duplicate_profile_pairs_removed': self.duplicate_profile_pairs_removed,
            'duplicate_negative_tags_removed': self.duplicate_negative_tags_removed,
            'duplicate_rec_items_removed': self.duplicate_rec_items_removed,
            'orphan_edges_removed': self.orphan_edges_removed,
            'orphan_illusts_removed': self.orphan_illusts_removed,
            'orphan_illust_tags_removed': self.orphan_illust_tags_removed,
            'followed_flags_aligned': self.followed_flags_aligned,
            'vacuumed': self.vacuumed,
        }


class LibraryDedupeService:
    """Idempotent library cleanup: PK-level dups, orphans, followed-flag alignment."""

    def __init__(self, *, database: SQLiteDatabase) -> None:
        self.database = database

    def dedupe(self, *, vacuum: bool = True) -> LibraryDedupeResult:
        result = LibraryDedupeResult()
        with self.database.connect() as conn:
            before = self._table_counts(conn)
            result.tables['before'] = before

            # Defensive rowid cleanup in case older DBs ever lacked primary keys.
            result.duplicate_edges_removed = self._delete_dup_rowids(
                conn,
                table='seed_user_following_artists',
                key_cols=('seed_user_id', 'artist_user_id'),
            )
            result.duplicate_artists_removed = self._delete_dup_rowids(
                conn,
                table='artists',
                key_cols=('user_id',),
            )
            result.duplicate_illusts_removed = self._delete_dup_rowids(
                conn,
                table='illusts',
                key_cols=('illust_id',),
            )
            result.duplicate_illust_tags_removed = self._delete_dup_rowids(
                conn,
                table='illust_tags',
                key_cols=('illust_id', 'tag'),
            )
            result.duplicate_candidates_removed = self._delete_dup_rowids(
                conn,
                table='artist_candidates',
                key_cols=('seed_user_id', 'candidate_user_id', 'source_type', 'source_key'),
            )
            result.duplicate_profile_tags_removed = self._delete_dup_rowids(
                conn,
                table='user_taste_profile',
                key_cols=('seed_user_id', 'tag'),
            )
            result.duplicate_profile_pairs_removed = self._delete_dup_rowids(
                conn,
                table='user_tag_pairs',
                key_cols=('seed_user_id', 'tag_a', 'tag_b'),
            )
            result.duplicate_negative_tags_removed = self._delete_dup_rowids(
                conn,
                table='user_negative_profile',
                key_cols=('seed_user_id', 'tag'),
            )
            result.duplicate_rec_items_removed = self._delete_dup_rowids(
                conn,
                table='recommendation_items',
                key_cols=('run_id', 'artist_user_id'),
            )

            # Orphans: drop edges without artist, illusts without artist, then tags without illust.
            cur = conn.execute(
                """
                DELETE FROM seed_user_following_artists
                WHERE NOT EXISTS (
                    SELECT 1 FROM artists a WHERE a.user_id = seed_user_following_artists.artist_user_id
                )
                """
            )
            result.orphan_edges_removed = int(cur.rowcount or 0)

            cur = conn.execute(
                """
                DELETE FROM illusts
                WHERE NOT EXISTS (
                    SELECT 1 FROM artists a WHERE a.user_id = illusts.user_id
                )
                """
            )
            result.orphan_illusts_removed = int(cur.rowcount or 0)

            cur = conn.execute(
                """
                DELETE FROM illust_tags
                WHERE NOT EXISTS (
                    SELECT 1 FROM illusts i WHERE i.illust_id = illust_tags.illust_id
                )
                """
            )
            result.orphan_illust_tags_removed = int(cur.rowcount or 0)

            # Align is_followed with following edges (any seed).
            cur = conn.execute(
                """
                UPDATE artists
                SET is_followed = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM seed_user_following_artists e
                        WHERE e.artist_user_id = artists.user_id
                    ) THEN 1
                    ELSE 0
                END
                WHERE is_followed != CASE
                    WHEN EXISTS (
                        SELECT 1 FROM seed_user_following_artists e
                        WHERE e.artist_user_id = artists.user_id
                    ) THEN 1
                    ELSE 0
                END
                """
            )
            result.followed_flags_aligned = int(cur.rowcount or 0)

            result.tables['after'] = self._table_counts(conn)

        if vacuum:
            # VACUUM cannot run inside a transaction / with open writer cleanly on all sqlite builds.
            with self.database.connect() as conn:
                conn.isolation_level = None
                conn.execute('VACUUM')
            result.vacuumed = True

        return result

    @staticmethod
    def _table_counts(conn) -> dict[str, int]:
        tables = (
            'seed_user_following_artists',
            'artists',
            'illusts',
            'illust_tags',
            'artist_candidates',
            'user_taste_profile',
            'user_tag_pairs',
            'user_negative_profile',
            'recommendation_runs',
            'recommendation_items',
            'feedback_events',
        )
        out: dict[str, int] = {}
        for table in tables:
            row = conn.execute(f'SELECT COUNT(*) AS c FROM {table}').fetchone()
            out[table] = int(row['c'] if row is not None else 0)
        return out

    @staticmethod
    def _delete_dup_rowids(conn, *, table: str, key_cols: tuple[str, ...]) -> int:
        keys = ', '.join(key_cols)
        sql = f"""
            DELETE FROM {table}
            WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM {table} GROUP BY {keys}
            )
        """
        cur = conn.execute(sql)
        return int(cur.rowcount or 0)
