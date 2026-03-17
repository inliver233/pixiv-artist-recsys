from __future__ import annotations

import json
from dataclasses import asdict

from ..auth.models import PixivTokenRecord
from ..domain.models import Artist, RecommendationRun, SeedUser
from .database import SQLiteDatabase


class RecommendationRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def initialize(self) -> None:
        self.database.initialize()

    def upsert_seed_user(self, seed_user: SeedUser) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO seed_users (user_id, refresh_token_ref, allow_ai, allow_r18)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    refresh_token_ref=excluded.refresh_token_ref,
                    allow_ai=excluded.allow_ai,
                    allow_r18=excluded.allow_r18
                """,
                (seed_user.user_id, seed_user.refresh_token_ref, int(seed_user.allow_ai), int(seed_user.allow_r18)),
            )

    def upsert_artist(self, artist: Artist) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO artists (user_id, name, account, is_followed, profile_image_url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name=excluded.name,
                    account=excluded.account,
                    is_followed=excluded.is_followed,
                    profile_image_url=excluded.profile_image_url,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (artist.user_id, artist.name, artist.account, int(artist.is_followed), artist.profile_image_url),
            )

    def record_run(self, run: RecommendationRun) -> None:
        with self.database.connect() as conn:
            conn.execute(
                "INSERT INTO recommendation_runs (run_id, seed_user_id, mode) VALUES (?, ?, ?)",
                (run.run_id, run.seed_user_id, run.mode),
            )
            for item in run.items:
                conn.execute(
                    """
                    INSERT INTO recommendation_items (run_id, artist_user_id, score, confidence, reasons, top_illust_ids)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        item.artist.user_id,
                        item.score,
                        item.confidence,
                        json.dumps(item.reasons, ensure_ascii=False),
                        json.dumps(item.top_illust_ids, ensure_ascii=False),
                    ),
                )

    def count_rows(self, table_name: str) -> int:
        with self.database.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS c FROM {table_name}").fetchone()
        return int(row['c'])

    def upsert_token_record(self, record: PixivTokenRecord) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO pixiv_tokens (
                    token_key, refresh_token_ref, access_token, token_type, expires_at_epoch,
                    refresh_token_rotated, user_id, last_refreshed_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_key) DO UPDATE SET
                    refresh_token_ref=excluded.refresh_token_ref,
                    access_token=excluded.access_token,
                    token_type=excluded.token_type,
                    expires_at_epoch=excluded.expires_at_epoch,
                    refresh_token_rotated=excluded.refresh_token_rotated,
                    user_id=excluded.user_id,
                    last_refreshed_at=excluded.last_refreshed_at,
                    last_error=excluded.last_error
                """,
                (
                    record.token_key,
                    record.refresh_token_ref,
                    record.access_token,
                    record.token_type,
                    record.expires_at_epoch,
                    record.refresh_token_rotated,
                    record.user_id,
                    record.last_refreshed_at,
                    record.last_error,
                ),
            )

    def get_token_record(self, token_key: str) -> PixivTokenRecord | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT token_key, refresh_token_ref, access_token, token_type, expires_at_epoch, refresh_token_rotated, user_id, last_refreshed_at, last_error FROM pixiv_tokens WHERE token_key = ?",
                (token_key,),
            ).fetchone()
        if row is None:
            return None
        return PixivTokenRecord(
            token_key=str(row['token_key']),
            refresh_token_ref=str(row['refresh_token_ref']),
            access_token=str(row['access_token']),
            token_type=str(row['token_type']),
            expires_at_epoch=int(row['expires_at_epoch']),
            refresh_token_rotated=str(row['refresh_token_rotated']),
            user_id=int(row['user_id']) if row['user_id'] is not None else None,
            last_refreshed_at=str(row['last_refreshed_at']),
            last_error=str(row['last_error']),
        )

    def upsert_following_edge(self, *, seed_user_id: int, artist_user_id: int) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO seed_user_following_artists (seed_user_id, artist_user_id)
                VALUES (?, ?)
                ON CONFLICT(seed_user_id, artist_user_id) DO UPDATE SET
                    last_seen_at=CURRENT_TIMESTAMP
                """,
                (seed_user_id, artist_user_id),
            )

    def list_following_artist_ids(self, *, seed_user_id: int) -> list[int]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT artist_user_id FROM seed_user_following_artists WHERE seed_user_id = ? ORDER BY artist_user_id",
                (seed_user_id,),
            ).fetchall()
        return [int(row['artist_user_id']) for row in rows]
