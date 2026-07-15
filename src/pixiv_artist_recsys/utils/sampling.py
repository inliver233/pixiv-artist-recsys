from __future__ import annotations

import hashlib
import random
from typing import Sequence


def _salt_key(seed_user_id: int, sample_salt: int | str | None) -> str:
    if sample_salt is None or sample_salt == '' or sample_salt == 0:
        return str(int(seed_user_id))
    return f'{int(seed_user_id)}:{sample_salt}'


def hash_sample_ids(
    ids: list[int] | set[int] | Sequence[int],
    *,
    seed_user_id: int,
    limit: int,
    sample_salt: int | str | None = None,
) -> list[int]:
    """Deterministic pseudo-random subset, stable for the same seed_user_id (+ optional salt).

    Better than raw sorted[:N] when following list is large (~2600): avoids always
    using the same low user ids as seeds. Use when you need reproducible runs.
    ``sample_salt`` rotates the subset across multi-round campaigns without losing
    determinism within a round.
    """
    if limit <= 0:
        return []
    unique = sorted({int(item) for item in ids if int(item) > 0})
    if not unique:
        return []
    prefix = _salt_key(seed_user_id, sample_salt)
    ranked = sorted(
        unique,
        key=lambda artist_id: hashlib.sha1(f'{prefix}:{artist_id}'.encode('utf-8')).hexdigest(),
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


def quality_first_ids(
    scored_ids: Sequence[tuple[int, float]],
    *,
    limit: int,
    seed_user_id: int = 0,
    explore_ratio: float = 0.25,
    sample_salt: int | str | None = None,
    rng: random.Random | None = None,
) -> list[int]:
    """Prefer high-score ids, keep a small random explore slice for diversity.

    ``scored_ids`` is (id, quality_score) — higher score first. Missing scores
    should be 0. ``explore_ratio`` of the budget is filled from the remaining
    pool so repeated runs (or salted rounds) still broaden coverage.
    """
    if limit <= 0:
        return []
    cleaned: list[tuple[int, float]] = []
    seen: set[int] = set()
    for raw_id, raw_score in scored_ids:
        artist_id = int(raw_id)
        if artist_id <= 0 or artist_id in seen:
            continue
        seen.add(artist_id)
        cleaned.append((artist_id, float(raw_score)))
    if not cleaned:
        return []
    cleaned.sort(key=lambda item: (-item[1], item[0]))
    if limit >= len(cleaned):
        return [artist_id for artist_id, _ in cleaned]

    explore_n = max(0, min(limit, int(round(limit * max(0.0, min(0.5, float(explore_ratio)))))))
    exploit_n = limit - explore_n
    exploit = [artist_id for artist_id, _ in cleaned[:exploit_n]]
    remaining = [artist_id for artist_id, _ in cleaned[exploit_n:]]
    if explore_n <= 0 or not remaining:
        return exploit[:limit]
    # Mix hash-stable + true random explore so tests can pass rng.
    picker = rng if rng is not None else random
    if rng is None and seed_user_id:
        # Stable-ish explore without freezing the whole set: hash rank then random tie-break.
        explore_pool = hash_sample_ids(
            remaining,
            seed_user_id=seed_user_id,
            limit=min(len(remaining), explore_n * 3),
            sample_salt=sample_salt,
        )
        if len(explore_pool) > explore_n:
            explore = picker.sample(explore_pool, explore_n)
        else:
            explore = explore_pool[:explore_n]
            if len(explore) < explore_n:
                leftover = [x for x in remaining if x not in explore]
                explore.extend(picker.sample(leftover, min(explore_n - len(explore), len(leftover))))
    else:
        explore = picker.sample(remaining, min(explore_n, len(remaining)))
    out = exploit + list(explore)
    # Preserve exploit-first order; drop accidental dups.
    ordered: list[int] = []
    used: set[int] = set()
    for artist_id in out:
        if artist_id in used:
            continue
        used.add(artist_id)
        ordered.append(artist_id)
        if len(ordered) >= limit:
            break
    if len(ordered) < limit:
        for artist_id, _ in cleaned:
            if artist_id in used:
                continue
            ordered.append(artist_id)
            if len(ordered) >= limit:
                break
    return ordered[:limit]


def sample_ids(
    ids: list[int] | set[int] | Sequence[int],
    *,
    limit: int,
    mode: str = 'random',
    seed_user_id: int = 0,
    rng: random.Random | None = None,
    quality_scores: dict[int, float] | None = None,
    sample_salt: int | str | None = None,
    explore_ratio: float = 0.25,
) -> list[int]:
    """Sample ids by mode: quality_first | random (default) | hash | first | hydrated_first.

    ``quality_first`` needs ``quality_scores`` (id -> score). Without scores it
    falls back to random so callers stay safe.
    ``sample_salt`` rotates hash / quality explore slices across campaign rounds.
    """
    normalized = (mode or 'random').strip().lower()
    if normalized == 'hash':
        return hash_sample_ids(ids, seed_user_id=seed_user_id, limit=limit, sample_salt=sample_salt)
    if normalized == 'first':
        unique = sorted({int(item) for item in ids if int(item) > 0})
        return unique[: max(0, int(limit))]
    if normalized in {'quality_first', 'quality', 'hydrated_first'}:
        # hydrated_first without scores ≈ random among present ids (caller should pre-filter).
        scores = quality_scores or {}
        if scores:
            scored = [(int(i), float(scores.get(int(i), 0.0))) for i in ids if int(i) > 0]
            return quality_first_ids(
                scored,
                limit=limit,
                seed_user_id=seed_user_id,
                explore_ratio=explore_ratio,
                sample_salt=sample_salt,
                rng=rng,
            )
        if normalized == 'quality_first' or normalized == 'quality':
            return random_sample_ids(ids, limit=limit, rng=rng)
        # hydrated_first without scores: treat as random
        return random_sample_ids(ids, limit=limit, rng=rng)
    return random_sample_ids(ids, limit=limit, rng=rng)
