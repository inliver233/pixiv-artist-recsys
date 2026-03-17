from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from ..storage.repositories import RecommendationRepository


@dataclass(slots=True)
class TagPairWeight:
    tag_a: str
    tag_b: str
    weight: float


@dataclass(slots=True)
class TasteProfileSummary:
    seed_user_id: int
    top_tags: list[tuple[str, float]]
    top_pairs: list[TagPairWeight]
    artist_count: int


class UserTasteProfileService:
    def __init__(self, *, repository: RecommendationRepository, stop_words: set[str] | None = None) -> None:
        self.repository = repository
        self.stop_words = {self.normalize_tag(tag) for tag in (stop_words or set())}

    @staticmethod
    def normalize_tag(tag: str) -> str:
        normalized = str(tag or '').strip().lower().replace(' ', '_')
        return normalized

    def build_profile(self, *, seed_user_id: int, top_n_tags: int = 20, top_n_pairs: int = 20) -> TasteProfileSummary:
        followed = self.repository.fetch_followed_tags(seed_user_id=seed_user_id)
        tag_counter: Counter[str] = Counter()
        pair_counter: Counter[tuple[str, str]] = Counter()

        for _, tags in followed:
            normalized_tags = sorted({self.normalize_tag(tag) for tag in tags if self.normalize_tag(tag) and self.normalize_tag(tag) not in self.stop_words})
            tag_counter.update(normalized_tags)
            pair_counter.update(combinations(normalized_tags, 2))

        total = sum(tag_counter.values()) or 1
        top_tags = [(tag, weight / total) for tag, weight in tag_counter.most_common(top_n_tags)]
        total_pairs = sum(pair_counter.values()) or 1
        top_pairs = [TagPairWeight(tag_a=a, tag_b=b, weight=weight / total_pairs) for (a, b), weight in pair_counter.most_common(top_n_pairs)]

        self.repository.replace_user_taste_profile(seed_user_id=seed_user_id, weights=top_tags)
        self.repository.replace_user_tag_pairs(seed_user_id=seed_user_id, pairs=[(p.tag_a, p.tag_b, p.weight) for p in top_pairs])

        return TasteProfileSummary(seed_user_id=seed_user_id, top_tags=top_tags, top_pairs=top_pairs, artist_count=len(followed))
