from __future__ import annotations

import math
from collections import Counter, defaultdict
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
        diversity_primary_tag_limit: int = 2,
    ) -> RankedRecommendationResult:
        seed_user = self.repository.fetch_seed_user(user_id=seed_user_id)
        resolved_allow_ai = seed_user.allow_ai if allow_ai is None and seed_user is not None else bool(allow_ai)
        resolved_allow_r18 = seed_user.allow_r18 if allow_r18 is None and seed_user is not None else bool(allow_r18)

        followed_ids = set(self.repository.list_following_artist_ids(seed_user_id=seed_user_id))
        rejected_ids = set(self.repository.list_feedback_artist_ids(seed_user_id=seed_user_id, actions=('dislike', 'block')))
        profile = dict(self.repository.fetch_user_taste_profile(seed_user_id=seed_user_id))
        negative_profile = dict(self.repository.fetch_user_negative_profile(seed_user_id=seed_user_id))
        evidence_map: dict[int, list[tuple[str, str, float, str]]] = defaultdict(list)
        for candidate_user_id, source_type, source_key, weight, detail in self.repository.fetch_artist_candidates(seed_user_id=seed_user_id):
            if candidate_user_id in followed_ids or candidate_user_id in rejected_ids:
                continue
            evidence_map[candidate_user_id].append((source_type, source_key, weight, detail))

        results: list[RecommendationItem] = []
        primary_tags_by_artist: dict[int, str] = {}
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
            normalized_tags = sorted({self._normalize(tag) for tag in tags if self._normalize(tag)}, key=lambda t: profile.get(t, 0.0), reverse=True)
            primary_tags_by_artist[candidate_user_id] = normalized_tags[0] if normalized_tags else ''
            tag_score = sum(profile.get(tag, 0.0) for tag in normalized_tags)
            negative_tag_score = sum(negative_profile.get(tag, 0.0) for tag in normalized_tags)
            if negative_tag_score >= 0.5:
                continue
            evidence_score = sum(weight for _, _, weight, _ in evidences)
            quality_score = self._quality_score(filtered_illusts)
            final_score = 0.45 * tag_score + 0.35 * evidence_score + 0.20 * quality_score - 0.30 * negative_tag_score
            if final_score < min_score:
                continue
            confidence = min(1.0, 0.25 + 0.15 * len(evidences) + 0.1 * min(3, len(filtered_illusts)))
            top_illust_ids = [illust.illust_id for illust in filtered_illusts[:3]]
            top_tags = normalized_tags[:3]
            reasons = [f"evidence:{source_type}" for source_type, _, _, _ in evidences[:2]]
            if top_tags:
                reasons.append(f"tags:{','.join(top_tags)}")
            if negative_tag_score > 0:
                reasons.append(f"negative_penalty:{round(negative_tag_score, 3)}")
            if min_total_bookmarks > 0:
                reasons.append(f"quality:min_bookmarks>={min_total_bookmarks}")
            results.append(RecommendationItem(artist=artist, score=round(final_score, 6), confidence=round(confidence, 6), reasons=reasons, top_illust_ids=top_illust_ids))

        results.sort(key=lambda item: (-item.score, -item.confidence, item.artist.user_id))
        results = self._apply_diversity(
            results,
            primary_tags_by_artist=primary_tags_by_artist,
            max_results=max_results,
            diversity_primary_tag_limit=diversity_primary_tag_limit,
        )
        return RankedRecommendationResult(seed_user_id=seed_user_id, items=results)

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

    @staticmethod
    def _apply_diversity(
        items: list[RecommendationItem],
        *,
        primary_tags_by_artist: dict[int, str],
        max_results: int,
        diversity_primary_tag_limit: int,
    ) -> list[RecommendationItem]:
        if diversity_primary_tag_limit <= 0:
            return items[:max_results]

        selected: list[RecommendationItem] = []
        overflow: list[RecommendationItem] = []
        counts: Counter[str] = Counter()
        for item in items:
            primary_tag = primary_tags_by_artist.get(item.artist.user_id, '')
            if primary_tag and counts[primary_tag] >= diversity_primary_tag_limit:
                overflow.append(item)
                continue
            if primary_tag:
                counts[primary_tag] += 1
                if not any(reason.startswith('diversity:primary_tag=') for reason in item.reasons):
                    item.reasons.append(f'diversity:primary_tag={primary_tag}')
            selected.append(item)
            if len(selected) >= max_results:
                return selected[:max_results]

        for item in overflow:
            selected.append(item)
            if len(selected) >= max_results:
                break
        return selected[:max_results]
