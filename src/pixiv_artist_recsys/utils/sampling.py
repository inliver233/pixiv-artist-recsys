from __future__ import annotations

import hashlib
import random
from typing import Sequence


def hash_sample_ids(ids: list[int] | set[int] | Sequence[int], *, seed_user_id: int, limit: int) -> list[int]:
    """Deterministic pseudo-random subset, stable for the same seed_user_id.

    Better than raw sorted[:N] when following list is large (~2600): avoids always
    using the same low user ids as seeds. Use when you need reproducible runs.
    """
    if limit <= 0:
        return []
    unique = sorted({int(item) for item in ids if int(item) > 0})
    if not unique:
        return []
    ranked = sorted(
        unique,
        key=lambda artist_id: hashlib.sha1(f'{seed_user_id}:{artist_id}'.encode('utf-8')).hexdigest(),
    )
    return ranked[:limit]


def random_sample_ids(
    ids: list[int] | set[int] | Sequence[int],
    *,
    limit: int,
    rng: random.Random | None = None,
) -> list[int]:
    """True random subset without replacement (different each process/run).

    Prefer this for daily recommendations so repeated runs explore different
    regions of a large following list. Pass ``rng`` only in tests.
    """
    if limit <= 0:
        return []
    unique = [int(item) for item in {int(x) for x in ids if int(x) > 0}]
    if not unique:
        return []
    picker = rng if rng is not None else random
    if limit >= len(unique):
        shuffled = list(unique)
        picker.shuffle(shuffled)
        return shuffled
    return picker.sample(unique, limit)


def sample_ids(
    ids: list[int] | set[int] | Sequence[int],
    *,
    limit: int,
    mode: str = 'random',
    seed_user_id: int = 0,
    rng: random.Random | None = None,
) -> list[int]:
    """Sample ids by mode: random (default) | hash | first."""
    normalized = (mode or 'random').strip().lower()
    if normalized == 'hash':
        return hash_sample_ids(ids, seed_user_id=seed_user_id, limit=limit)
    if normalized == 'first':
        unique = sorted({int(item) for item in ids if int(item) > 0})
        return unique[: max(0, int(limit))]
    return random_sample_ids(ids, limit=limit, rng=rng)
