from __future__ import annotations

import math
import random
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..profile.service import UserTasteProfileService
from ..rank.service import HeuristicArtistRankService
from ..storage.database import SQLiteDatabase
from ..storage.repositories import RecommendationRepository


@dataclass(slots=True)
class HoldoutEvaluationReport:
    seed_user_id: int
    followed_total: int
    eligible_total: int
    holdout_count: int
    ranked_total: int
    holdout_ranked: int
    recall_at_k: float
    recall_k: int
    ndcg_at_k: float
    ndcg_k: int
    holdout_positions: dict[int, int] = field(default_factory=dict)  # artist_id -> 1-based rank

    def to_dict(self) -> dict[str, Any]:
        return {
            'seed_user_id': self.seed_user_id,
            'followed_total': self.followed_total,
            'eligible_total': self.eligible_total,
            'holdout_count': self.holdout_count,
            'ranked_total': self.ranked_total,
            'holdout_ranked': self.holdout_ranked,
            f'recall@{self.recall_k}': round(self.recall_at_k, 4),
            f'ndcg@{self.ndcg_k}': round(self.ndcg_at_k, 4),
            'holdout_positions': {str(k): v for k, v in sorted(self.holdout_positions.items())},
        }


class LeaveOneOutEvaluator:
    """Offline ranking evaluation via followed-artist holdout.

    A slice of the seed user's followed artists is converted into candidates
    inside a sandbox copy of the database; the profile is rebuilt from the
    remaining follows and the ranker scores the FULL candidate pool (no
    negative sampling — Krichene & Rendle KDD'20). Recall@K / NDCG@K measure
    how highly the ranker places artists the user demonstrably likes.

    Pruning gates that are orthogonal to ranking quality (min_score, absolute
    bookmark floors, diversity truncation) are relaxed so a gate change does
    not masquerade as a ranking change; taste/genre gates stay live because
    they ARE part of ranking behaviour.
    """

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        holdout_ratio: float = 0.2,
        rng_seed: int = 20260726,
        min_local_illusts: int = 2,
    ) -> None:
        self.database = database
        self.holdout_ratio = float(holdout_ratio)
        self.rng_seed = int(rng_seed)
        self.min_local_illusts = int(min_local_illusts)

    def evaluate(
        self,
        *,
        seed_user_id: int,
        recall_k: int = 50,
        ndcg_k: int = 20,
        profile_top_n_tags: int = 40,
        profile_top_n_pairs: int = 30,
        profile_min_bookmarks: int = 0,
    ) -> HoldoutEvaluationReport:
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox_path = Path(tmpdir) / 'eval-sandbox.sqlite3'
            self._clone_database(sandbox_path)
            sandbox = SQLiteDatabase(sandbox_path)
            repo = RecommendationRepository(sandbox)

            followed = repo.list_following_artist_ids(seed_user_id=seed_user_id)
            illusts_by_artist = repo.fetch_illusts_for_artists(artist_user_ids=followed)
            eligible = [
                artist_id
                for artist_id in followed
                if len(illusts_by_artist.get(artist_id, [])) >= self.min_local_illusts
            ]
            rng = random.Random(self.rng_seed)
            holdout_n = max(1, int(round(len(eligible) * self.holdout_ratio))) if eligible else 0
            holdout = sorted(rng.sample(eligible, holdout_n)) if holdout_n else []

            if holdout:
                self._convert_to_candidates(sandbox, seed_user_id=seed_user_id, artist_ids=holdout)

            UserTasteProfileService(repository=repo).build_profile(
                seed_user_id=seed_user_id,
                top_n_tags=profile_top_n_tags,
                top_n_pairs=profile_top_n_pairs,
                min_artist_bookmarks=profile_min_bookmarks,
            )

            ranked = HeuristicArtistRankService(repository=repo).rank_from_store(
                seed_user_id=seed_user_id,
                max_results=10_000_000,
                min_total_bookmarks=0,
                min_score=-1.0,
                diversity_primary_tag_limit=0,
                min_local_illusts=self.min_local_illusts,
                require_tag_overlap=False,
                min_relative_bookmark_ratio=0.0,
            )

            holdout_set = set(holdout)
            positions: dict[int, int] = {}
            for rank_pos, item in enumerate(ranked.items, start=1):
                if item.artist.user_id in holdout_set:
                    positions[item.artist.user_id] = rank_pos

            recall = self._recall_at_k(positions, holdout_set, k=recall_k)
            ndcg = self._ndcg_at_k(positions, holdout_set, k=ndcg_k)
            return HoldoutEvaluationReport(
                seed_user_id=seed_user_id,
                followed_total=len(followed),
                eligible_total=len(eligible),
                holdout_count=len(holdout),
                ranked_total=len(ranked.items),
                holdout_ranked=len(positions),
                recall_at_k=recall,
                recall_k=int(recall_k),
                ndcg_at_k=ndcg,
                ndcg_k=int(ndcg_k),
                holdout_positions=positions,
            )

    def _clone_database(self, target_path: Path) -> None:
        target = sqlite3.connect(target_path)
        try:
            with self.database.connect() as source:
                source.backup(target)
            target.commit()
        finally:
            target.close()

    @staticmethod
    def _convert_to_candidates(sandbox: SQLiteDatabase, *, seed_user_id: int, artist_ids: list[int]) -> None:
        """Remove holdout follows and register them as ordinary candidates.

        Evidence uses a fixed neutral row (user_related, weight 1.0) so every
        holdout artist enters the ranker on identical footing; the metric then
        reflects taste/quality scoring, not evidence-source luck.

        seed_artist_following evidence is stripped for ALL candidates: holdout
        artists structurally cannot have co-follow rows (recall excluded them
        while they were followed), so leaving the signal live for ordinary
        candidates would bias the metric against every holdout artist.
        """
        with sandbox.transaction() as conn:
            conn.execute(
                "DELETE FROM artist_candidates WHERE seed_user_id = ? AND source_type = 'seed_artist_following'",
                (seed_user_id,),
            )
            for artist_id in artist_ids:
                conn.execute(
                    "DELETE FROM seed_user_following_artists WHERE seed_user_id = ? AND artist_user_id = ?",
                    (seed_user_id, artist_id),
                )
                conn.execute(
                    "UPDATE artists SET is_followed = 0 WHERE user_id = ?",
                    (artist_id,),
                )
                conn.execute(
                    """
                    INSERT INTO artist_candidates (seed_user_id, candidate_user_id, source_type, source_key, weight, detail)
                    VALUES (?, ?, 'user_related', 'holdout-eval', 1.0, 'leave-one-out-holdout')
                    ON CONFLICT(seed_user_id, candidate_user_id, source_type, source_key) DO NOTHING
                    """,
                    (seed_user_id, artist_id),
                )

    @staticmethod
    def _recall_at_k(positions: dict[int, int], holdout: set[int], *, k: int) -> float:
        if not holdout:
            return 0.0
        hits = sum(1 for artist_id in holdout if positions.get(artist_id, 10**12) <= k)
        return hits / len(holdout)

    @staticmethod
    def _ndcg_at_k(positions: dict[int, int], holdout: set[int], *, k: int) -> float:
        if not holdout:
            return 0.0
        dcg = sum(
            1.0 / math.log2(pos + 1)
            for artist_id in holdout
            if (pos := positions.get(artist_id, 10**12)) <= k
        )
        ideal_hits = min(len(holdout), k)
        idcg = sum(1.0 / math.log2(pos + 1) for pos in range(1, ideal_hits + 1))
        return dcg / idcg if idcg > 0 else 0.0
