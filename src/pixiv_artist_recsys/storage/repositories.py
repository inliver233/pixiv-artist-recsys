from __future__ import annotations

import json
from dataclasses import asdict

from ..auth.models import PixivTokenRecord
from ..domain.models import Artist, Illust, RecommendationRun, SeedUser
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

    def upsert_illust(self, illust: Illust) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO illusts (illust_id, user_id, title, create_date, total_bookmarks, total_view, total_comments, ai_type, x_restrict)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(illust_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    title=excluded.title,
                    create_date=excluded.create_date,
                    total_bookmarks=excluded.total_bookmarks,
                    total_view=excluded.total_view,
                    total_comments=excluded.total_comments,
                    ai_type=excluded.ai_type,
                    x_restrict=excluded.x_restrict
                """,
                (
                    illust.illust_id,
                    illust.user_id,
                    illust.title,
                    illust.create_date,
                    illust.total_bookmarks,
                    illust.total_view,
                    illust.total_comments,
                    illust.ai_type,
                    illust.x_restrict,
                ),
            )

    def replace_illust_tags(self, *, illust_id: int, tags: list[str]) -> None:
        tags_clean = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
        with self.database.connect() as conn:
            conn.execute("DELETE FROM illust_tags WHERE illust_id = ?", (illust_id,))
            conn.executemany(
                "INSERT INTO illust_tags (illust_id, tag) VALUES (?, ?)",
                [(illust_id, tag) for tag in tags_clean],
            )

    def list_followed_artists(self, *, seed_user_id: int) -> list[Artist]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT a.user_id, a.name, a.account, a.is_followed, a.profile_image_url
                FROM artists a
                JOIN seed_user_following_artists s ON s.artist_user_id = a.user_id
                WHERE s.seed_user_id = ?
                ORDER BY a.user_id
                """,
                (seed_user_id,),
            ).fetchall()
        return [Artist(user_id=int(r['user_id']), name=str(r['name']), account=str(r['account']), is_followed=bool(r['is_followed']), profile_image_url=str(r['profile_image_url'])) for r in rows]

    def list_illust_ids_for_artist(self, *, artist_user_id: int) -> list[int]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT illust_id FROM illusts WHERE user_id = ? ORDER BY total_bookmarks DESC, illust_id DESC",
                (artist_user_id,),
            ).fetchall()
        return [int(r['illust_id']) for r in rows]

    def fetch_artist_tags(self, *, artist_user_id: int) -> list[str]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT t.tag
                FROM illust_tags t
                JOIN illusts i ON i.illust_id = t.illust_id
                WHERE i.user_id = ?
                ORDER BY t.tag
                """,
                (artist_user_id,),
            ).fetchall()
        return [str(r['tag']) for r in rows]

    def fetch_illusts_for_artist(self, *, artist_user_id: int) -> list[Illust]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT illust_id, user_id, title, create_date, total_bookmarks, total_view, total_comments, ai_type, x_restrict FROM illusts WHERE user_id = ? ORDER BY total_bookmarks DESC, illust_id DESC",
                (artist_user_id,),
            ).fetchall()
        return [Illust(illust_id=int(r['illust_id']), user_id=int(r['user_id']), title=str(r['title']), create_date=str(r['create_date']), total_bookmarks=int(r['total_bookmarks']), total_view=int(r['total_view']), total_comments=int(r['total_comments']), ai_type=int(r['ai_type']), x_restrict=int(r['x_restrict'])) for r in rows]

    def replace_user_taste_profile(self, *, seed_user_id: int, weights: list[tuple[str, float]]) -> None:
        with self.database.connect() as conn:
            conn.execute("DELETE FROM user_taste_profile WHERE seed_user_id = ?", (seed_user_id,))
            conn.executemany(
                "INSERT INTO user_taste_profile (seed_user_id, tag, weight) VALUES (?, ?, ?)",
                [(seed_user_id, tag, float(weight)) for tag, weight in weights],
            )

    def replace_user_tag_pairs(self, *, seed_user_id: int, pairs: list[tuple[str, str, float]]) -> None:
        with self.database.connect() as conn:
            conn.execute("DELETE FROM user_tag_pairs WHERE seed_user_id = ?", (seed_user_id,))
            conn.executemany(
                "INSERT INTO user_tag_pairs (seed_user_id, tag_a, tag_b, weight) VALUES (?, ?, ?, ?)",
                [(seed_user_id, a, b, float(weight)) for a, b, weight in pairs],
            )

    def fetch_user_taste_profile(self, *, seed_user_id: int) -> list[tuple[str, float]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT tag, weight FROM user_taste_profile WHERE seed_user_id = ? ORDER BY weight DESC, tag ASC",
                (seed_user_id,),
            ).fetchall()
        return [(str(r['tag']), float(r['weight'])) for r in rows]

    def fetch_user_tag_pairs(self, *, seed_user_id: int) -> list[tuple[str, str, float]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT tag_a, tag_b, weight FROM user_tag_pairs WHERE seed_user_id = ? ORDER BY weight DESC, tag_a ASC, tag_b ASC",
                (seed_user_id,),
            ).fetchall()
        return [(str(r['tag_a']), str(r['tag_b']), float(r['weight'])) for r in rows]

    def fetch_followed_tags(self, *, seed_user_id: int) -> list[tuple[int, list[str]]]:
        artists = self.list_following_artist_ids(seed_user_id=seed_user_id)
        result: list[tuple[int, list[str]]] = []
        for artist_id in artists:
            result.append((artist_id, self.fetch_artist_tags(artist_user_id=artist_id)))
        return result
