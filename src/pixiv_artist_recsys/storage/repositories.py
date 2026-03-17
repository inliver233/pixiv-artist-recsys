from __future__ import annotations

import json
from dataclasses import asdict

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
