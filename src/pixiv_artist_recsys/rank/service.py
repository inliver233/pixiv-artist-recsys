from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from ..domain.models import RecommendationItem
from ..storage.repositories import RecommendationRepository


# Exact-match blocks after normalize (lower + spaces→underscore).
DEFAULT_BLOCKED_TAGS: frozenset[str] = frozenset(
    {
        # manga / comic
        '漫画',
        'manga',
        '創作漫画',
        'オリジナル漫画',
        '漫画作品',
        '4コマ',
        '4koma',
        'コミック',
        'comic',
        # furry / kemono
        'ケモノ',
        'ケモナー',
        'furry',
        'furrys',
        '獣人',
        '獣化',
        'anthro',
        'ケモノ化',
        # BL / yaoi-oriented
        'bl',
        '創作bl',
        '腐',
        '腐向け',
        'やおい',
        'yaoi',
        'boys_love',
        'ボーイズラブ',
        # AI generation markers (artist-level filter also uses ai_type)
        'ai',
        'ai生成',
        'ai-generated',
        'aigenerated',
        'novelai',
        'nai',
        'stable_diffusion',
        'stablediffusion',
        'sdxl',
        'midjourney',
        'aiイラスト',
        'ai绘画',
        'ai繪圖',
        '生成ai',
    }
)

# Substring markers for composite tags like ケモノシスマイク / 創作漫画作品.
DEFAULT_BLOCKED_SUBSTRINGS: tuple[str, ...] = (
    '漫画',
    'manga',
    '4コマ',
    '4koma',
    'コミック',
    'comic',
    'ケモノ',
    'ケモ',
    'furry',
    'anthro',
    '獣人',
    '獣化',
    '創作bl',
    'ボーイズラブ',
    'boys_love',
    'やおい',
    'yaoi',
    'ai生成',
    'ai-generated',
    'aigenerated',
    'novelai',
    'stable_diffusion',
    'stablediffusion',
    'midjourney',
    'aiイラスト',
    'ai绘画',
    'ai繪圖',
    '生成ai',
)

# Soft genre families for purity scoring (fraction of local illusts that hit family).
_GENRE_FAMILIES: dict[str, tuple[str, ...]] = {
    'manga': ('漫画', 'manga', '4コマ', '4koma', 'コミック', 'comic'),
    'furry': ('ケモノ', 'ケモ', 'furry', 'anthro', '獣人', '獣化'),
    'bl': ('創作bl', 'ボーイズラブ', 'boys_love', 'やおい', 'yaoi', '腐向け'),
}

# Source reliability used when aggregating evidence (following is broad/noisy).
_SOURCE_RELIABILITY: dict[str, float] = {
    'user_related': 1.0,
    'user_recommended': 0.9,
    'illust_related': 0.85,
    'tag_search': 0.75,
    'seed_artist_following': 0.55,
}

_USERS_IRI_RE = re.compile(r'^\d+users入り$', re.IGNORECASE)
_USERS_IRI_EMBEDDED_RE = re.compile(r'\d+users入り', re.IGNORECASE)


@dataclass(slots=True)
class RankedRecommendationResult:
    seed_user_id: int
    items: list[RecommendationItem]


class HeuristicArtistRankService:
    def __init__(
        self,
        *,
        repository: RecommendationRepository,
        blocked_tags: set[str] | frozenset[str] | None = None,
        blocked_substrings: tuple[str, ...] | list[str] | None = None,
        max_genre_fraction: float = 0.34,
        max_manga_type_fraction: float = 0.5,
        max_ai_fraction: float = 0.15,
        min_relative_bookmark_ratio: float = 0.35,
    ) -> None:
        self.repository = repository
        raw = blocked_tags if blocked_tags is not None else DEFAULT_BLOCKED_TAGS
        self.blocked_tags = {self._normalize(tag) for tag in raw if self._normalize(tag)}
        subs = blocked_substrings if blocked_substrings is not None else DEFAULT_BLOCKED_SUBSTRINGS
        self.blocked_substrings = tuple(self._normalize(s) for s in subs if self._normalize(s))
        self.max_genre_fraction = float(max_genre_fraction)
        self.max_manga_type_fraction = float(max_manga_type_fraction)
        self.max_ai_fraction = float(max_ai_fraction)
        self.min_relative_bookmark_ratio = float(min_relative_bookmark_ratio)

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
        min_local_illusts: int = 2,
        min_tag_score: float = 0.0,
        require_tag_overlap: bool = True,
        blocked_tags: set[str] | frozenset[str] | None = None,
        max_genre_fraction: float | None = None,
        max_ai_fraction: float | None = None,
        min_relative_bookmark_ratio: float | None = None,
    ) -> RankedRecommendationResult:
        seed_user = self.repository.fetch_seed_user(user_id=seed_user_id)
        resolved_allow_ai = seed_user.allow_ai if allow_ai is None and seed_user is not None else bool(allow_ai)
        resolved_allow_r18 = seed_user.allow_r18 if allow_r18 is None and seed_user is not None else bool(allow_r18)
        active_blocks = (
            {self._normalize(tag) for tag in blocked_tags if self._normalize(tag)}
            if blocked_tags is not None
            else self.blocked_tags
        )
        genre_frac_limit = self.max_genre_fraction if max_genre_fraction is None else float(max_genre_fraction)
        ai_frac_limit = self.max_ai_fraction if max_ai_fraction is None else float(max_ai_fraction)
        relative_ratio = (
            self.min_relative_bookmark_ratio
            if min_relative_bookmark_ratio is None
            else float(min_relative_bookmark_ratio)
        )

        followed_ids = set(self.repository.list_following_artist_ids(seed_user_id=seed_user_id))
        rejected_ids = set(self.repository.list_feedback_artist_ids(seed_user_id=seed_user_id, actions=('dislike', 'block')))
        followed_quality_median = self._followed_max_bookmark_median(followed_ids)
        relative_min_bookmarks = 0
        if relative_ratio > 0 and followed_quality_median > 0:
            relative_min_bookmarks = int(math.floor(followed_quality_median * relative_ratio))
        effective_min_bookmarks = max(int(min_total_bookmarks or 0), relative_min_bookmarks)

        profile = dict(self.repository.fetch_user_taste_profile(seed_user_id=seed_user_id))
        pair_weights = {
            (self._normalize(a), self._normalize(b)): float(w)
            for a, b, w in self.repository.fetch_user_tag_pairs(seed_user_id=seed_user_id)
            if self._normalize(a) and self._normalize(b)
        }
        negative_profile = dict(self.repository.fetch_user_negative_profile(seed_user_id=seed_user_id))
        evidence_map: dict[int, list[tuple[str, str, float, str]]] = defaultdict(list)
        for candidate_user_id, source_type, source_key, weight, detail in self.repository.fetch_artist_candidates(
            seed_user_id=seed_user_id
        ):
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
            # Artist-level AI fraction (before per-illust AI strip) — mixed AI portfolios drop.
            if not resolved_allow_ai and illusts and ai_frac_limit >= 0:
                ai_count = sum(1 for illust in illusts if int(getattr(illust, 'ai_type', 0) or 0) != 0)
                ai_frac = ai_count / len(illusts)
                if ai_frac > ai_frac_limit:
                    continue
            filtered_illusts = [
                illust
                for illust in illusts
                if (resolved_allow_ai or illust.ai_type == 0) and (resolved_allow_r18 or illust.x_restrict == 0)
            ]
            if illusts and not filtered_illusts:
                continue
            if min_local_illusts > 0 and len(filtered_illusts) < min_local_illusts:
                continue
            if filtered_illusts and max(illust.total_bookmarks for illust in filtered_illusts) < effective_min_bookmarks:
                continue
            if not filtered_illusts and effective_min_bookmarks > 0:
                continue

            illust_ids = [illust.illust_id for illust in filtered_illusts]
            tag_map = self.repository.fetch_illust_tag_map(illust_ids=illust_ids)
            per_illust_tags: list[set[str]] = []
            all_tags: set[str] = set()
            for illust in filtered_illusts:
                raw_tags = tag_map.get(illust.illust_id, [])
                norm = {self._normalize(tag) for tag in raw_tags if self._normalize(tag)}
                per_illust_tags.append(norm)
                all_tags.update(norm)

            # Hard exact block on any artist-level tag.
            if active_blocks and any(tag in active_blocks for tag in all_tags):
                continue
            # Substring block for composites (ケモノシスマイク).
            if self.blocked_substrings and any(
                any(sub in tag for sub in self.blocked_substrings) for tag in all_tags
            ):
                continue

            genre_fracs = self._genre_fractions(per_illust_tags)
            if genre_frac_limit >= 0 and any(frac > genre_frac_limit for frac in genre_fracs.values()):
                continue

            type_frac = self._manga_type_fraction(filtered_illusts)
            if self.max_manga_type_fraction >= 0 and type_frac > self.max_manga_type_fraction:
                continue

            # Prefer distinctive tags when picking diversity primary key.
            normalized_tags = sorted(
                all_tags,
                key=lambda t: profile.get(t, 0.0),
                reverse=True,
            )
            primary_tags_by_artist[candidate_user_id] = normalized_tags[0] if normalized_tags else ''

            taste_score, taste_meta = self._taste_score(
                profile=profile,
                pair_weights=pair_weights,
                candidate_tags=all_tags,
                per_illust_tags=per_illust_tags,
            )
            negative_tag_score = sum(negative_profile.get(tag, 0.0) for tag in all_tags)
            if negative_tag_score >= 0.5:
                continue
            if require_tag_overlap and taste_score <= 0.0:
                continue
            if taste_score < min_tag_score:
                continue

            evidence_score = self._evidence_score(evidences)
            quality_score, quality_meta = self._quality_score(filtered_illusts)
            purity_score = self._purity_score(genre_fracs, type_frac)

            # All components calibrated to ~[0, 1]. Weights sum to 1.0 before penalties.
            final_score = (
                0.50 * taste_score
                + 0.20 * evidence_score
                + 0.15 * quality_score
                + 0.15 * purity_score
                - 0.45 * min(1.0, negative_tag_score)
            )
            if final_score < min_score:
                continue

            distinct_sources = len({source_type for source_type, _, _, _ in evidences})
            distinct_keys = len({(source_type, source_key) for source_type, source_key, _, _ in evidences})
            confidence = min(
                1.0,
                0.18
                + 0.10 * min(6, distinct_keys)
                + 0.08 * min(4, distinct_sources)
                + 0.10 * min(6, len(filtered_illusts))
                + 0.15 * taste_score
                + 0.10 * purity_score
                + 0.08 * evidence_score,
            )
            ordered = sorted(filtered_illusts, key=lambda i: (-i.total_bookmarks, -i.illust_id))
            top_illust_ids = [illust.illust_id for illust in ordered[:3]]
            top_tags = normalized_tags[:3]
            source_types = sorted({source_type for source_type, _, _, _ in evidences})
            reasons = [f'evidence:{source_type}' for source_type in source_types[:4]]
            if top_tags:
                reasons.append(f"tags:{','.join(top_tags)}")
            if taste_score > 0:
                reasons.append(f'taste:score={round(taste_score, 4)}')
                if taste_meta.get('cosine') is not None:
                    reasons.append(f"taste:cosine={taste_meta['cosine']}")
                if taste_meta.get('pair') is not None:
                    reasons.append(f"taste:pair={taste_meta['pair']}")
            if negative_tag_score > 0:
                reasons.append(f'negative_penalty:{round(negative_tag_score, 3)}')
            if min_local_illusts > 0:
                reasons.append(f'quality:min_local_illusts>={min_local_illusts}')
            if effective_min_bookmarks > 0:
                reasons.append(f'quality:min_bookmarks>={effective_min_bookmarks}')
            if relative_min_bookmarks > 0:
                reasons.append(
                    f'quality:relative_min={relative_min_bookmarks}'
                    f'(followed_median_max_bm={int(followed_quality_median)},ratio={relative_ratio})'
                )
            if quality_meta.get('median_bookmarks') is not None:
                reasons.append(f"quality:median_bookmarks={quality_meta['median_bookmarks']}")
            if quality_meta.get('consistency') is not None:
                reasons.append(f"quality:consistency={quality_meta['consistency']}")
            reasons.append(f'purity:score={round(purity_score, 3)}')
            for family, frac in sorted(genre_fracs.items()):
                if frac > 0:
                    reasons.append(f'genre:{family}_frac={round(frac, 3)}')
            if type_frac > 0:
                reasons.append(f'type:manga_frac={round(type_frac, 3)}')
            results.append(
                RecommendationItem(
                    artist=artist,
                    score=round(final_score, 6),
                    confidence=round(confidence, 6),
                    reasons=reasons,
                    top_illust_ids=top_illust_ids,
                )
            )

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
        text = str(tag or '').strip().lower().replace(' ', '_')
        if not text:
            return ''
        if _USERS_IRI_RE.match(text):
            return ''
        return _USERS_IRI_EMBEDDED_RE.sub('', text).strip('_')

    def _taste_score(
        self,
        *,
        profile: dict[str, float],
        pair_weights: dict[tuple[str, str], float],
        candidate_tags: set[str],
        per_illust_tags: list[set[str]],
    ) -> tuple[float, dict[str, float]]:
        if not profile or not candidate_tags:
            return 0.0, {}

        # Cosine between profile weight vector and binary candidate tag vector.
        dot = 0.0
        for tag, weight in profile.items():
            if tag in candidate_tags:
                dot += float(weight)
        profile_norm = math.sqrt(sum(float(w) ** 2 for w in profile.values())) or 1.0
        cand_norm = math.sqrt(float(len(candidate_tags))) or 1.0
        cosine = max(0.0, min(1.0, dot / (profile_norm * cand_norm)))

        # Coverage: share of profile mass that lands on candidate tags.
        coverage = max(0.0, min(1.0, dot / (sum(abs(float(w)) for w in profile.values()) or 1.0)))

        # Pair boost: co-occurring profile pairs present on the same illust.
        pair_hit = 0.0
        pair_total = sum(pair_weights.values()) or 0.0
        if pair_weights and per_illust_tags:
            hit_mass = 0.0
            for tags in per_illust_tags:
                for (a, b), weight in pair_weights.items():
                    if a in tags and b in tags:
                        hit_mass += weight
            # Average per-illust pair mass, normalized by total pair mass.
            pair_hit = max(0.0, min(1.0, (hit_mass / max(1, len(per_illust_tags))) / (pair_total or 1.0)))

        score = 0.55 * cosine + 0.30 * coverage + 0.15 * pair_hit
        return max(0.0, min(1.0, score)), {
            'cosine': round(cosine, 4),
            'coverage': round(coverage, 4),
            'pair': round(pair_hit, 4),
        }

    @staticmethod
    def _evidence_score(evidences: list[tuple[str, str, float, str]]) -> float:
        if not evidences:
            return 0.0
        # Within each source_type keep max weight per distinct source_key, then
        # saturating multi-key sum (many independent keys confirm more than one).
        keys_by_type: dict[str, dict[str, float]] = defaultdict(dict)
        for source_type, source_key, weight, _detail in evidences:
            key = str(source_key or '')
            weight_f = float(weight)
            prev = keys_by_type[source_type].get(key)
            if prev is None or weight_f > prev:
                keys_by_type[source_type][key] = weight_f
        type_values: list[float] = []
        for source_type, key_weights in keys_by_type.items():
            rel = _SOURCE_RELIABILITY.get(source_type, 0.6)
            raw = sum(key_weights.values())
            # Soft multi-key: first key full, further keys add diminishing returns.
            multi = raw / (raw + 0.75) if raw > 0 else 0.0
            n_keys = len(key_weights)
            if n_keys > 1:
                multi = min(1.0, multi * (1.0 + 0.06 * min(6, n_keys - 1)))
            type_values.append(multi * rel)
        # Cross-type saturating sum so multi-channel confirmation helps but does not explode.
        total = sum(type_values)
        return max(0.0, min(1.0, total / (total + 1.2)))

    def _genre_fractions(self, per_illust_tags: list[set[str]]) -> dict[str, float]:
        if not per_illust_tags:
            return {name: 0.0 for name in _GENRE_FAMILIES}
        counts = {name: 0 for name in _GENRE_FAMILIES}
        for tags in per_illust_tags:
            joined = ' '.join(tags)
            for family, markers in _GENRE_FAMILIES.items():
                if any(marker in joined or any(marker in tag for tag in tags) for marker in markers):
                    counts[family] += 1
        n = len(per_illust_tags)
        return {name: counts[name] / n for name in _GENRE_FAMILIES}

    @staticmethod
    def _manga_type_fraction(illusts) -> float:
        if not illusts:
            return 0.0
        manga_like = 0
        for illust in illusts:
            itype = str(getattr(illust, 'illust_type', '') or '').strip().lower()
            pages = int(getattr(illust, 'page_count', 1) or 1)
            if itype == 'manga' or pages >= 4:
                manga_like += 1
        return manga_like / len(illusts)

    @staticmethod
    def _purity_score(genre_fracs: dict[str, float], type_frac: float) -> float:
        # 1.0 = clean illustration artist; subtract genre/type pollution.
        pollution = max(genre_fracs.values(), default=0.0)
        pollution = max(pollution, type_frac * 0.8)
        return max(0.0, min(1.0, 1.0 - pollution))

    @staticmethod
    def _quality_score(illusts) -> tuple[float, dict[str, float | int]]:
        """Bounded quality in [0, 1] so popularity cannot drown taste."""
        if not illusts:
            return 0.0, {}
        sample = list(illusts[:8])
        bookmark_values = [max(0, int(illust.total_bookmarks)) for illust in sample]
        median_bookmarks = HeuristicArtistRankService._median(bookmark_values)
        max_bookmarks = max(bookmark_values) if bookmark_values else 0
        consistency = 1.0
        if max_bookmarks > 0:
            consistency = min(1.0, (median_bookmarks + 1.0) / (max_bookmarks + 1.0))
            consistency = max(0.2, consistency)

        bookmark_cap = 5000.0
        median_norm = min(1.0, math.log1p(median_bookmarks) / math.log1p(bookmark_cap))
        mean_parts: list[float] = []
        for illust in sample[:5]:
            bm = min(1.0, math.log1p(max(0, illust.total_bookmarks)) / math.log1p(bookmark_cap))
            views = min(0.25, math.log1p(max(0, illust.total_view)) / math.log1p(50000.0) * 0.25)
            comments = min(0.15, math.log1p(max(0, illust.total_comments)) / math.log1p(500.0) * 0.15)
            ratio = 0.0
            if illust.total_view > 0:
                ratio = min(0.15, illust.total_bookmarks / max(1, illust.total_view) * 1.5)
            mean_parts.append(bm + views + comments + ratio)
        mean_engagement = sum(mean_parts) / len(mean_parts) if mean_parts else 0.0
        # mean_engagement roughly [0, 1.55] → normalize into [0, 1]
        mean_norm = min(1.0, mean_engagement / 1.55)
        score = 0.50 * mean_norm + 0.35 * median_norm + 0.15 * consistency
        score = max(0.0, min(1.0, score))
        return score, {
            'median_bookmarks': int(median_bookmarks),
            'consistency': round(consistency, 3),
            'max_bookmarks': int(max_bookmarks),
        }

    @staticmethod
    def _median(values: list[int]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return float(ordered[mid])
        return (ordered[mid - 1] + ordered[mid]) / 2.0

    def _followed_max_bookmark_median(self, followed_ids: set[int]) -> float:
        """Median of per-followed-artist max bookmarks (local hydrate only).

        Used as a relative quality anchor so mid-tier candidates cannot outrank
        the user's actual followed tier via absolute min_bookmarks alone.

        Uses the *lower* half of followed maxima (25th–50th band via median of
        the bottom 60% after sort) so quality_first hydrate of only top seeds
        does not push the bar into the stratosphere and erase mid-high discoveries.
        """
        maxima: list[int] = []
        for artist_id in followed_ids:
            illusts = self.repository.fetch_illusts_for_artist(artist_user_id=artist_id)
            if not illusts:
                continue
            maxima.append(max(int(illust.total_bookmarks or 0) for illust in illusts))
        if not maxima:
            return 0.0
        ordered = sorted(maxima)
        # Drop extreme top 40% before median so mega-popular outliers do not dominate.
        if len(ordered) >= 5:
            keep = max(3, int(round(len(ordered) * 0.60)))
            ordered = ordered[:keep]
        return self._median(ordered)

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
