from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations

from ..storage.repositories import RecommendationRepository


# Tags that appear on almost every anime-style illustration and drown rare taste signals.
DEFAULT_STOP_WORDS: frozenset[str] = frozenset(
    {
        '女の子',
        'オリジナル',
        'original',
        'girl',
        'girls',
        '男性',
        '男の子',
        'boy',
        'boys',
        '風景',
        '背景',
        'illustration',
        'イラスト',
        '創作',
        'oc',
        'r-18',
        'r18',
        'nsfw',
        'safe',
        'ai',
        'ai生成',
        'ai-generated',
        'ハイレゾ',
        'highres',
        '作品',
        '描いてみた',
        '落書き',
        '練習',
        '習作',
        'fanart',
        'ファンアート',
        # meta / shop / status noise often attached to portfolio posts
        'お品書き',
        'skeb',
        'request',
        'リクエスト',
        'commission',
        'コミッション',
    }
)

# Soft-downweight (not hard-stop) ultra-generic tags that still carry weak genre signal.
GENERIC_TAG_MULTIPLIER = 0.35

# Popularity-bookmark meta tags: "1000users入り" etc.
_USERS_IRI_RE = re.compile(r'^\d+users入り$', re.IGNORECASE)
_USERS_IRI_EMBEDDED_RE = re.compile(r'\d+users入り', re.IGNORECASE)


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
        base = set(DEFAULT_STOP_WORDS)
        if stop_words:
            base.update(self.normalize_tag(tag) for tag in stop_words if self.normalize_tag(tag))
        self.stop_words = base

    @staticmethod
    def normalize_tag(tag: str) -> str:
        normalized = str(tag or '').strip().lower().replace(' ', '_')
        if not normalized:
            return ''
        # Strip pure popularity meta tags and embedded "Nusers入り" suffixes.
        if _USERS_IRI_RE.match(normalized):
            return ''
        cleaned = _USERS_IRI_EMBEDDED_RE.sub('', normalized).strip('_')
        return cleaned

    def build_profile(
        self,
        *,
        seed_user_id: int,
        top_n_tags: int = 40,
        top_n_pairs: int = 30,
        min_artist_bookmarks: int = 0,
    ) -> TasteProfileSummary:
        followed = self.repository.fetch_followed_tags(seed_user_id=seed_user_id)
        # Optional quality gate: only artists with local max bookmarks >= threshold
        # contribute to taste (avoids sparse/low-tier follows diluting the profile).
        quality_ids: set[int] | None = None
        if min_artist_bookmarks and min_artist_bookmarks > 0:
            quality_ids = set()
            for artist_id, _ in followed:
                illusts = self.repository.fetch_illusts_for_artist(artist_user_id=artist_id)
                if not illusts:
                    continue
                if max(int(i.total_bookmarks or 0) for i in illusts) >= int(min_artist_bookmarks):
                    quality_ids.add(int(artist_id))
        # Artist-level TF: each followed artist contributes each tag at most once (avoids one
        # prolific artist flooding the profile with 女の子-style mass tags).
        artist_tag_sets: list[set[str]] = []
        pair_counter: Counter[tuple[str, str]] = Counter()
        df: Counter[str] = Counter()

        for artist_id, tags in followed:
            if quality_ids is not None and int(artist_id) not in quality_ids:
                continue
            normalized_tags = sorted(
                {
                    n
                    for tag in tags
                    if (n := self.normalize_tag(tag)) and n not in self.stop_words
                }
            )
            if not normalized_tags:
                continue
            tag_set = set(normalized_tags)
            artist_tag_sets.append(tag_set)
            df.update(tag_set)
            pair_counter.update(combinations(normalized_tags, 2))

        artist_count = len(artist_tag_sets)
        if artist_count == 0:
            self.repository.replace_user_taste_profile(seed_user_id=seed_user_id, weights=[])
            self.repository.replace_user_tag_pairs(seed_user_id=seed_user_id, pairs=[])
            return TasteProfileSummary(seed_user_id=seed_user_id, top_tags=[], top_pairs=[], artist_count=0)

        # TF: fraction of followed artists that carry the tag.
        tf: dict[str, float] = {tag: count / artist_count for tag, count in df.items()}
        # Simple IDF over the followed-artist corpus (rarer tags among follows = more distinctive).
        idf: dict[str, float] = {
            tag: math.log1p(artist_count / max(1, count)) for tag, count in df.items()
        }
        scored: list[tuple[str, float]] = []
        for tag, tf_val in tf.items():
            weight = tf_val * idf.get(tag, 1.0)
            # Mild extra damp for very high-df tags that slipped past stopwords.
            if df[tag] / artist_count >= 0.55:
                weight *= GENERIC_TAG_MULTIPLIER
            scored.append((tag, weight))

        scored.sort(key=lambda item: (-item[1], item[0]))
        # L1-normalize so ranker can treat profile as a probability-like vector.
        total = sum(weight for _, weight in scored) or 1.0
        top_tags = [(tag, weight / total) for tag, weight in scored[: max(1, top_n_tags)]]

        total_pairs = sum(pair_counter.values()) or 1
        top_pairs = [
            TagPairWeight(tag_a=a, tag_b=b, weight=weight / total_pairs)
            for (a, b), weight in pair_counter.most_common(top_n_pairs)
        ]

        self.repository.replace_user_taste_profile(seed_user_id=seed_user_id, weights=top_tags)
        self.repository.replace_user_tag_pairs(
            seed_user_id=seed_user_id,
            pairs=[(p.tag_a, p.tag_b, p.weight) for p in top_pairs],
        )
        return TasteProfileSummary(
            seed_user_id=seed_user_id,
            top_tags=top_tags,
            top_pairs=top_pairs,
            artist_count=artist_count,
        )
