from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from typing import Callable

from ..storage.repositories import RecommendationRepository

# Taste ages: a 5-year-old follow says less about today's taste than last week's.
PROFILE_TIME_DECAY_DAYS = 180.0


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
    def __init__(
        self,
        *,
        repository: RecommendationRepository,
        stop_words: set[str] | None = None,
        now_fn: Callable[[], float] | None = None,
        time_decay_days: float = PROFILE_TIME_DECAY_DAYS,
    ) -> None:
        self.repository = repository
        base = set(DEFAULT_STOP_WORDS)
        if stop_words:
            base.update(self.normalize_tag(tag) for tag in stop_words if self.normalize_tag(tag))
        self.stop_words = base
        self.now_fn = now_fn or time.time
        self.time_decay_days = float(time_decay_days)

    def _artist_weight(
        self,
        *,
        artist_id: int,
        first_seen_at: str | None,
        max_bookmarks: int,
        now_epoch: float,
    ) -> float:
        # Recency: exp(-days_since_first_seen / decay); unknown first_seen → 1.0
        # (feedback-follows and legacy rows count as fresh).
        recency = 1.0
        if first_seen_at and self.time_decay_days > 0:
            seen_epoch = self._parse_epoch(first_seen_at)
            if seen_epoch is not None:
                days = max(0.0, (now_epoch - seen_epoch) / 86400.0)
                recency = math.exp(-days / self.time_decay_days)
        # Quality: log1p(max_bm) so a 5k-bookmark artist speaks louder than a
        # 50-bookmark one without drowning everyone (quality-weighted TF).
        quality = math.log1p(max(0, int(max_bookmarks)) ) or 1.0
        return max(0.05, recency) * max(1.0, quality)

    @staticmethod
    def _parse_epoch(timestamp: str) -> float | None:
        text = str(timestamp or '').strip()
        if not text:
            return None
        try:
            # SQLite CURRENT_TIMESTAMP: 'YYYY-MM-DD HH:MM:SS' (UTC).
            parsed = datetime.fromisoformat(text.replace(' ', 'T'))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

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
        # follow-action feedback = fresh positive taste signal; those artists may
        # not be in the following edges yet, so merge their tags in explicitly (Q-3a).
        followed_ids = {int(artist_id) for artist_id, _ in followed}
        follow_feedback_ids = [
            artist_id
            for artist_id in self.repository.list_feedback_artist_ids(seed_user_id=seed_user_id, actions=('follow',))
            if int(artist_id) not in followed_ids
        ]
        if follow_feedback_ids:
            feedback_tags = self.repository.fetch_artist_tags_for_artists(artist_user_ids=follow_feedback_ids)
            followed = list(followed) + [(artist_id, feedback_tags.get(artist_id, [])) for artist_id in follow_feedback_ids]

        all_artist_ids = [int(artist_id) for artist_id, _ in followed]
        max_bm = self.repository.fetch_max_bookmarks_by_artist(artist_user_ids=all_artist_ids)
        # Optional quality gate: only artists with local max bookmarks >= threshold
        # contribute to taste (avoids sparse/low-tier follows diluting the profile).
        quality_ids: set[int] | None = None
        if min_artist_bookmarks and min_artist_bookmarks > 0:
            quality_ids = {
                artist_id for artist_id, bm in max_bm.items() if int(bm) >= int(min_artist_bookmarks)
            }
        first_seen = self.repository.fetch_following_first_seen(seed_user_id=seed_user_id)
        now = float(self.now_fn())

        # Artist-level TF: each artist contributes each tag at most once (avoids one
        # prolific artist flooding the profile), weighted by recency of the follow
        # (exp(-days/decay)) and portfolio quality (log1p(max_bm)) — Q-9.
        artist_entries: list[tuple[set[str], float]] = []
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
            artist_weight = self._artist_weight(
                artist_id=int(artist_id),
                first_seen_at=first_seen.get(int(artist_id)),
                max_bookmarks=int(max_bm.get(int(artist_id), 0)),
                now_epoch=now,
            )
            artist_entries.append((tag_set, artist_weight))
            df.update(tag_set)
            pair_counter.update(combinations(normalized_tags, 2))

        artist_count = len(artist_entries)
        if artist_count == 0:
            self.repository.replace_user_taste_profile(seed_user_id=seed_user_id, weights=[])
            self.repository.replace_user_tag_pairs(seed_user_id=seed_user_id, pairs=[])
            return TasteProfileSummary(seed_user_id=seed_user_id, top_tags=[], top_pairs=[], artist_count=0)

        # Weighted TF: share of (recency*quality) artist mass carrying the tag.
        total_weight = sum(weight for _, weight in artist_entries) or 1.0
        tf: Counter[str] = Counter()
        for tag_set, weight in artist_entries:
            for tag in tag_set:
                tf[tag] += weight
        # Simple IDF over the followed-artist corpus (rarer tags among follows = more distinctive).
        idf: dict[str, float] = {
            tag: math.log1p(artist_count / max(1, count)) for tag, count in df.items()
        }
        scored: list[tuple[str, float]] = []
        for tag, tf_mass in tf.items():
            weight = (tf_mass / total_weight) * idf.get(tag, 1.0)
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
