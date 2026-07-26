from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Mapping

from ..config import RecommendationConfig

_SAMPLE_MODES = {'quality_first', 'quality', 'random', 'hydrated_first', 'hash', 'first'}


def _optional_int(value: Any) -> int | None:
    if value is None or value == '':
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == '':
        return None
    return float(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False
    raise ValueError(f'invalid boolean value: {value}')


def _sample_mode(value: Any, default: str) -> str:
    text = str(value or '').strip()
    return text if text in _SAMPLE_MODES else default


@dataclass(slots=True)
class FullRecommendParams:
    """Single definition of every full-recommend tunable.

    CLI, facade, jobs and the API router previously each hand-copied this
    parameter list; the API layer had silently drifted (missing ~10 knobs).
    from_mapping() is the one parsing point — jobs manifests and API bodies
    both go through it, so a new knob added here is available everywhere.

    None means "resolve from RecommendationConfig at execution time" for
    fields the facade treats as optional; concrete defaults mirror the
    facade's own signature defaults for the rest.
    """

    restrict: str = 'public'
    followed_artist_limit: int = 16
    candidate_artist_limit: int = 10
    max_related_per_artist: int = 16
    max_related_per_illust: int = 16
    max_illusts_for_related: int | None = None
    max_seed_artists: int = 600
    max_candidate_artists: int = 2000
    seed_sample: str = 'quality_first'
    enable_user_recommended: bool = True
    max_user_recommended: int = 100
    enable_tag_search: bool = True
    max_tag_search_tags: int = 16
    max_tag_search_illusts: int = 50
    enable_seed_following: bool = True
    max_seed_following_artists: int = 80
    max_following_per_seed_artist: int = 50
    seed_following_sample: str = 'quality_first'
    merge_candidates: bool | None = None
    top_n_tags: int = 40
    top_n_pairs: int = 30
    profile_min_bookmarks: int | None = None
    max_results: int | None = None
    allow_ai: bool | None = None
    allow_r18: bool | None = None
    min_bookmarks: int | None = None
    min_score: float | None = None
    diversity_per_tag: int | None = None
    min_local_illusts: int | None = None
    require_tag_overlap: bool | None = None
    max_genre_fraction: float | None = None
    max_ai_fraction: float | None = None
    min_relative_bookmark_ratio: float | None = None
    sample_salt: int | str | None = None
    explore_ratio: float | None = None
    skip_sync_if_fresh: bool = False
    light_round: bool = False
    stop_words: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        defaults: RecommendationConfig | None = None,
    ) -> 'FullRecommendParams':
        """Parse a manifest/API body. Absent keys fall back to `defaults`
        (RecommendationConfig) where a concrete value exists, else to the
        dataclass default (None = resolve later)."""
        base = cls()
        if defaults is not None:
            # Config carries concrete values for the sampling/limit knobs.
            for name in (
                'followed_artist_limit', 'candidate_artist_limit', 'max_related_per_artist',
                'max_related_per_illust', 'max_seed_artists', 'max_candidate_artists',
                'max_user_recommended', 'max_tag_search_tags', 'max_tag_search_illusts',
                'enable_seed_following', 'max_seed_following_artists',
                'max_following_per_seed_artist', 'seed_sample', 'seed_following_sample',
            ):
                setattr(base, name, getattr(defaults, name))
            base.max_illusts_for_related = defaults.max_illusts_for_related

        stop_words = payload.get('stop_words') or []
        if isinstance(stop_words, str):
            stop_words = [stop_words]

        def has(key: str) -> bool:
            return payload.get(key, None) is not None and payload.get(key) != ''

        base.restrict = str(payload.get('restrict') or base.restrict)
        if has('followed_artist_limit'):
            base.followed_artist_limit = int(payload['followed_artist_limit'])
        if has('candidate_artist_limit'):
            base.candidate_artist_limit = int(payload['candidate_artist_limit'])
        if has('max_related_per_artist'):
            base.max_related_per_artist = int(payload['max_related_per_artist'])
        if has('max_related_per_illust'):
            base.max_related_per_illust = int(payload['max_related_per_illust'])
        if has('max_illusts_for_related'):
            base.max_illusts_for_related = _optional_int(payload['max_illusts_for_related'])
        if has('max_seed_artists'):
            base.max_seed_artists = int(payload['max_seed_artists'])
        if has('max_candidate_artists'):
            base.max_candidate_artists = int(payload['max_candidate_artists'])
        base.seed_sample = _sample_mode(payload.get('seed_sample'), base.seed_sample)
        if has('enable_user_recommended'):
            base.enable_user_recommended = bool(_optional_bool(payload['enable_user_recommended']))
        if has('max_user_recommended'):
            base.max_user_recommended = int(payload['max_user_recommended'])
        if has('enable_tag_search'):
            base.enable_tag_search = bool(_optional_bool(payload['enable_tag_search']))
        if has('max_tag_search_tags'):
            base.max_tag_search_tags = int(payload['max_tag_search_tags'])
        if has('max_tag_search_illusts'):
            base.max_tag_search_illusts = int(payload['max_tag_search_illusts'])
        if has('enable_seed_following'):
            base.enable_seed_following = bool(_optional_bool(payload['enable_seed_following']))
        if has('max_seed_following_artists'):
            base.max_seed_following_artists = int(payload['max_seed_following_artists'])
        if has('max_following_per_seed_artist'):
            base.max_following_per_seed_artist = int(payload['max_following_per_seed_artist'])
        base.seed_following_sample = _sample_mode(payload.get('seed_following_sample'), base.seed_following_sample)
        base.merge_candidates = _optional_bool(payload.get('merge_candidates'))
        if has('top_n_tags'):
            base.top_n_tags = int(payload['top_n_tags'])
        if has('top_n_pairs'):
            base.top_n_pairs = int(payload['top_n_pairs'])
        base.profile_min_bookmarks = _optional_int(payload.get('profile_min_bookmarks'))
        base.max_results = _optional_int(payload.get('max_results'))
        base.allow_ai = _optional_bool(payload.get('allow_ai'))
        base.allow_r18 = _optional_bool(payload.get('allow_r18'))
        base.min_bookmarks = _optional_int(payload.get('min_bookmarks'))
        base.min_score = _optional_float(payload.get('min_score'))
        base.diversity_per_tag = _optional_int(payload.get('diversity_per_tag'))
        base.min_local_illusts = _optional_int(payload.get('min_local_illusts'))
        base.require_tag_overlap = _optional_bool(payload.get('require_tag_overlap'))
        base.max_genre_fraction = _optional_float(payload.get('max_genre_fraction'))
        base.max_ai_fraction = _optional_float(payload.get('max_ai_fraction'))
        base.min_relative_bookmark_ratio = _optional_float(payload.get('min_relative_bookmark_ratio'))
        base.sample_salt = payload.get('sample_salt')
        base.explore_ratio = _optional_float(payload.get('explore_ratio'))
        if has('skip_sync_if_fresh'):
            base.skip_sync_if_fresh = bool(_optional_bool(payload['skip_sync_if_fresh']))
        if has('light_round'):
            base.light_round = bool(_optional_bool(payload['light_round']))
        base.stop_words = tuple(str(item) for item in stop_words if str(item).strip())
        return base

    def to_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ApplicationFacade.full_recommend_payload."""
        out = {f.name: getattr(self, f.name) for f in fields(self)}
        out['stop_words'] = list(self.stop_words)
        return out
