from __future__ import annotations

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS pixiv_tokens (
        token_key TEXT PRIMARY KEY,
        refresh_token_ref TEXT NOT NULL,
        access_token TEXT NOT NULL DEFAULT '',
        token_type TEXT NOT NULL DEFAULT 'Bearer',
        expires_at_epoch INTEGER NOT NULL DEFAULT 0,
        refresh_token_rotated TEXT NOT NULL DEFAULT '',
        user_id INTEGER,
        last_refreshed_at TEXT NOT NULL DEFAULT '',
        last_error TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS seed_users (
        user_id INTEGER PRIMARY KEY,
        refresh_token_ref TEXT NOT NULL,
        allow_ai INTEGER NOT NULL DEFAULT 0,
        allow_r18 INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS seed_user_following_artists (
        seed_user_id INTEGER NOT NULL,
        artist_user_id INTEGER NOT NULL,
        first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(seed_user_id, artist_user_id),
        FOREIGN KEY(seed_user_id) REFERENCES seed_users(user_id),
        FOREIGN KEY(artist_user_id) REFERENCES artists(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artists (
        user_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        account TEXT NOT NULL DEFAULT '',
        is_followed INTEGER NOT NULL DEFAULT 0,
        profile_image_url TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS illusts (
        illust_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        create_date TEXT NOT NULL DEFAULT '',
        total_bookmarks INTEGER NOT NULL DEFAULT 0,
        total_view INTEGER NOT NULL DEFAULT 0,
        total_comments INTEGER NOT NULL DEFAULT 0,
        ai_type INTEGER NOT NULL DEFAULT 0,
        x_restrict INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES artists(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS illust_tags (
        illust_id INTEGER NOT NULL,
        tag TEXT NOT NULL,
        PRIMARY KEY (illust_id, tag),
        FOREIGN KEY(illust_id) REFERENCES illusts(illust_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_taste_profile (
        seed_user_id INTEGER NOT NULL,
        tag TEXT NOT NULL,
        weight REAL NOT NULL,
        PRIMARY KEY(seed_user_id, tag)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_tag_pairs (
        seed_user_id INTEGER NOT NULL,
        tag_a TEXT NOT NULL,
        tag_b TEXT NOT NULL,
        weight REAL NOT NULL,
        PRIMARY KEY(seed_user_id, tag_a, tag_b)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_negative_profile (
        seed_user_id INTEGER NOT NULL,
        tag TEXT NOT NULL,
        weight REAL NOT NULL,
        PRIMARY KEY(seed_user_id, tag)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        seed_user_id INTEGER NOT NULL,
        artist_user_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        source_run_id TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artist_candidates (
        seed_user_id INTEGER NOT NULL,
        candidate_user_id INTEGER NOT NULL,
        source_type TEXT NOT NULL,
        source_key TEXT NOT NULL,
        weight REAL NOT NULL DEFAULT 0,
        detail TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(seed_user_id, candidate_user_id, source_type, source_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_runs (
        run_id TEXT PRIMARY KEY,
        seed_user_id INTEGER NOT NULL,
        mode TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_items (
        run_id TEXT NOT NULL,
        artist_user_id INTEGER NOT NULL,
        score REAL NOT NULL,
        confidence REAL NOT NULL,
        reasons TEXT NOT NULL DEFAULT '',
        top_illust_ids TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(run_id, artist_user_id),
        FOREIGN KEY(run_id) REFERENCES recommendation_runs(run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_run_audit (
        run_id TEXT PRIMARY KEY,
        seed_user_id INTEGER NOT NULL,
        summary_json TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(run_id) REFERENCES recommendation_runs(run_id)
    )
    """,
]
