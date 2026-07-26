from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..storage.database import SQLiteDatabase

# claimed jobs whose worker died are recycled after this long.
DEFAULT_CLAIM_TIMEOUT_S = 30 * 60.0


@dataclass(slots=True)
class QueuedJob:
    job_id: int
    kind: str
    payload: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    claimed_by: str = ''
    result: dict[str, Any] | None = None
    error: str = ''


class JobQueue:
    """SQLite-backed work queue: pending → claimed → done | failed.

    Claiming is a single UPDATE guarded by status='pending', so concurrent
    workers on one WAL database cannot double-claim. Crash recovery: claimed
    rows older than claim_timeout_s are reset to pending by recover_stale()
    until attempts exhausts max_attempts.
    """

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        now_fn: Callable[[], float] | None = None,
        claim_timeout_s: float = DEFAULT_CLAIM_TIMEOUT_S,
    ) -> None:
        self.database = database
        self.now_fn = now_fn or time.time
        self.claim_timeout_s = float(claim_timeout_s)

    def enqueue(self, *, kind: str, payload: dict[str, Any] | None = None, max_attempts: int = 3) -> int:
        now = int(self.now_fn())
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs (kind, payload, status, max_attempts, created_at_epoch, updated_at_epoch)
                VALUES (?, ?, 'pending', ?, ?, ?)
                """,
                (str(kind), json.dumps(payload or {}, ensure_ascii=False), max(1, int(max_attempts)), now, now),
            )
            return int(cursor.lastrowid)

    def claim(self, *, worker: str, kinds: tuple[str, ...] | None = None) -> QueuedJob | None:
        """Atomically claim the oldest pending job (optionally filtered by kind)."""
        now = int(self.now_fn())
        with self.database.connect() as conn:
            if kinds:
                placeholders = ','.join(['?'] * len(kinds))
                pick = conn.execute(
                    f"SELECT job_id FROM jobs WHERE status = 'pending' AND kind IN ({placeholders}) "
                    "ORDER BY job_id LIMIT 1",
                    tuple(kinds),
                ).fetchone()
            else:
                pick = conn.execute(
                    "SELECT job_id FROM jobs WHERE status = 'pending' ORDER BY job_id LIMIT 1"
                ).fetchone()
            if pick is None:
                return None
            job_id = int(pick['job_id'])
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'claimed', claimed_by = ?, claimed_at_epoch = ?,
                    attempts = attempts + 1, updated_at_epoch = ?
                WHERE job_id = ? AND status = 'pending'
                """,
                (str(worker), now, now, job_id),
            )
            if int(cursor.rowcount or 0) != 1:
                # Lost the race to another worker; caller can retry.
                return None
        return self.get(job_id=job_id)

    def complete(self, *, job_id: int, result: dict[str, Any] | None = None) -> None:
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'done', result = ?, updated_at_epoch = ? WHERE job_id = ?",
                (json.dumps(result or {}, ensure_ascii=False), int(self.now_fn()), int(job_id)),
            )

    def fail(self, *, job_id: int, error: str) -> None:
        """Requeue for retry while attempts remain; terminal 'failed' after that."""
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'pending' END,
                    claimed_by = '', claimed_at_epoch = 0, error = ?, updated_at_epoch = ?
                WHERE job_id = ?
                """,
                (str(error)[:2000], int(self.now_fn()), int(job_id)),
            )

    def recover_stale(self) -> int:
        """Reset claimed jobs whose worker went silent past the claim timeout."""
        cutoff = int(self.now_fn() - self.claim_timeout_s)
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'pending' END,
                    claimed_by = '', claimed_at_epoch = 0, updated_at_epoch = ?
                WHERE status = 'claimed' AND claimed_at_epoch < ?
                """,
                (int(self.now_fn()), cutoff),
            )
            return int(cursor.rowcount or 0)

    def get(self, *, job_id: int) -> QueuedJob | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT job_id, kind, payload, status, attempts, max_attempts, claimed_by, result, error "
                "FROM jobs WHERE job_id = ?",
                (int(job_id),),
            ).fetchone()
        if row is None:
            return None
        result_raw = str(row['result'] or '')
        return QueuedJob(
            job_id=int(row['job_id']),
            kind=str(row['kind']),
            payload=json.loads(str(row['payload']) or '{}'),
            status=str(row['status']),
            attempts=int(row['attempts']),
            max_attempts=int(row['max_attempts']),
            claimed_by=str(row['claimed_by']),
            result=json.loads(result_raw) if result_raw else None,
            error=str(row['error']),
        )

    def counts(self) -> dict[str, int]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status").fetchall()
        return {str(r['status']): int(r['c']) for r in rows}
