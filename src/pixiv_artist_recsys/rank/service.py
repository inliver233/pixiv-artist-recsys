from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from ..domain.models import RecommendationItem
from ..storage.repositories import RecommendationRepository


@dataclass(slots=True)
class RankedRecommendationResult:
    seed_user_id: int
    items: list[RecommendationItem]


class HeuristicArtistRankService:
    def __init__(self, *, repository: RecommendationRepository) -> None:
        self.repository = repository

    def rank_from_store(
        self,
        *,
        seed_user_id: int,
        max_results: int = 20,
        allow_ai: bool | None = None,
        allow_r18: bool | None = None,
        min_total_bookmarks: int = 0,
        min_score: float = 0.0,
    ) -> RankedRecommendationResult:
        seed_user = self.repository.fetch_seed_user(user_id=seed_user_id)
        resolved_allow_ai = seed_user.allow_ai if allow_ai is None and seed_user is not None else bool(allow_ai)
        resolved_allow_r18 = seed_user.allow_r18 if allow_r18 is None and seed_user is not None else bool(allow_r18)

        followed_ids = set(self.repository.list_following_artist_ids(seed_user_id=seed_user_id))
        profile = dict(self.repository.fetch_user_taste_profile(seed_user_id=seed_user_id))
        evidence_map: dict[int, list[tuple[str, str, float, str]]] = defaultdict(list)
        for candidate_user_id, source_type, source_key, weight, detail in self.repository.fetch_artist_candidates(seed_user_id=seed_user_id):
            if candidate_user_id in followed_ids:
                continue
            evidence_map[candidate_user_id].append((source_type, source_key, weight, detail))

        results: list[RecommendationItem] = []
        for candidate_user_id, evidences in evidence_map.items():
            artist = self.repository.fetch_artist(artist_user_id=candidate_user_id)
            if artist is None:
                continue
            illusts = self.repository.fetch_illusts_for_artist(artist_user_id=candidate_user_id)
            filtered_illusts = [
                illust for illust in illusts
                if (resolved_allow_ai or illust.ai_type == 0) and (resolved_allow_r18 or illust.x_restrict == 0)
            ]
            if illusts and not filtered_illusts:
                continue
            if filtered_illusts and max(illust.total_bookmarks for illust in filtered_illusts) < min_total_bookmarks:
                continue
            if not filtered_illusts and min_total_bookmarks > 0:
                continue

            tags = self.repository.fetch_tags_for_illust_ids(illust_ids=[illust.illust_id for illust in filtered_illusts])
            tag_score = sum(profile.get(self._normalize(tag), 0.0) for tag in tags)
            evidence_score = sum(weight for _, _, weight, _ in evidences)
            quality_score = self._quality_score(filtered_illusts)
            final_score = 0.45 * tag_score + 0.35 * evidence_score + 0.20 * quality_score
            if final_score < min_score:
                continue
            confidence = min(1.0, 0.25 + 0.15 * len(evidences) + 0.1 * min(3, len(filtered_illusts)))
            top_illust_ids = [illust.illust_id for illust in filtered_illusts[:3]]
            top_tags = sorted({self._normalize(tag) for tag in tags if self._normalize(tag)}, key=lambda t: profile.get(t, 0.0), reverse=True)[:3]
            reasons = [f"evidence:{source_type}" for source_type, _, _, _ in evidences[:2]]
            if top_tags:
                reasons.append(f"tags:{','.join(top_tags)}")
            if min_total_bookmarks > 0:
                reasons.append(f"quality:min_bookmarks>={min_total_bookmarks}")
            results.append(RecommendationItem(artist=artist, score=round(final_score, 6), confidence=round(confidence, 6), reasons=reasons, top_illust_ids=top_illust_ids))

        results.sort(key=lambda item: (-item.score, -item.confidence, item.artist.user_id))
        return RankedRecommendationResult(seed_user_id=seed_user_id, items=results[:max_results])

    @staticmethod
    def _normalize(tag: str) -> str:
        return str(tag or '').strip().lower().replace(' ', '_')

    @staticmethod
    def _quality_score(illusts) -> float:
        if not illusts:
            return 0.0
        values = []
        for illust in illusts[:5]:
            bookmarks = math.log1p(max(0, illust.total_bookmarks))
            views = math.log1p(max(0, illust.total_view)) * 0.2
            comments = math.log1p(max(0, illust.total_comments)) * 0.3
            values.append(bookmarks + views + comments)
        return sum(values) / len(values)
