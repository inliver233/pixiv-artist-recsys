from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import os
from typing import Mapping


class AppMode(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


@dataclass(slots=True)
class StorageConfig:
    sqlite_path: Path


@dataclass(slots=True)
class RuntimePaths:
    repo_root: Path
    data_dir: Path
    runtime_dir: Path
    logs_dir: Path
    cache_dir: Path

    def ensure(self) -> None:
        for path in (self.data_dir, self.runtime_dir, self.logs_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class RecommendationConfig:
    # Tuned for ~2000–3000 following with a single child token (depth over concurrency).
    max_candidates: int = 400
    max_results: int = 60
    freshness_days: int = 180
    allow_ai: bool = False
    allow_r18: bool = False
    min_bookmarks: int = 30
    # Calibrated scores land roughly in 0.15–0.85; 0.28 filters weak taste/purity matches.
    min_score: float = 0.28
    diversity_per_tag: int = 3
    # Sparse hydrate (1 illust) was ranking popular off-taste artists; require a bit more evidence.
    min_local_illusts: int = 2
    # Drop candidates with zero overlap against the taste profile (popularity-only noise).
    require_tag_overlap: bool = True
    # Drop artists when manga/furry/BL fraction of local works exceeds this.
    max_genre_fraction: float = 0.34
    # Sampling defaults used by CLI / full-recommend when not overridden.
    followed_artist_limit: int = 10
    candidate_artist_limit: int = 6
    max_related_per_artist: int = 6
    max_related_per_illust: int = 6
    max_seed_artists: int = 90
    max_candidate_artists: int = 130
    max_user_recommended: int = 30
    max_tag_search_tags: int = 5
    max_tag_search_illusts: int = 20
    enable_seed_following: bool = True
    # Following expand is high-recall/low-precision — keep caps modest.
    max_seed_following_artists: int = 12
    max_following_per_seed_artist: int = 18
    # Seed pick modes: random (default, different each run) | hash | first | hydrated_first
    seed_sample: str = 'random'
    seed_following_sample: str = 'random'


@dataclass(slots=True)
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 8787


@dataclass(slots=True)
class AppSettings:
    mode: AppMode
    paths: RuntimePaths
    storage: StorageConfig
    api: ApiConfig = field(default_factory=ApiConfig)
    recommendation: RecommendationConfig = field(default_factory=RecommendationConfig)

    def ensure_directories(self) -> None:
        self.paths.ensure()
        self.storage.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_text(env: Mapping[str, str], key: str, default: str) -> str:
    raw_value = env.get(key)
    if raw_value is None:
        return default
    stripped = str(raw_value).strip()
    return stripped or default


def _env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw_value = env.get(key)
    if raw_value is None or not str(raw_value).strip():
        return default
    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean env value for {key}: {raw_value}")


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw_value = env.get(key)
    if raw_value is None or not str(raw_value).strip():
        return default
    try:
        return int(str(raw_value).strip())
    except ValueError as exc:
        raise ValueError(f"invalid integer env value for {key}: {raw_value}") from exc


def _env_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw_value = env.get(key)
    if raw_value is None or not str(raw_value).strip():
        return default
    try:
        return float(str(raw_value).strip())
    except ValueError as exc:
        raise ValueError(f"invalid float env value for {key}: {raw_value}") from exc


def load_settings(*, env: Mapping[str, str] | None = None) -> AppSettings:
    env = env or os.environ
    api_defaults = ApiConfig()
    recommendation_defaults = RecommendationConfig()
    repo_root = _repo_root()
    data_dir = Path(_env_text(env, "PIXIV_ARTIST_RECSYS_DATA_DIR", str(repo_root / "data")))
    runtime_dir = Path(_env_text(env, "PIXIV_ARTIST_RECSYS_RUNTIME_DIR", str(data_dir / "runtime")))
    logs_dir = Path(_env_text(env, "PIXIV_ARTIST_RECSYS_LOGS_DIR", str(runtime_dir / "logs")))
    cache_dir = Path(_env_text(env, "PIXIV_ARTIST_RECSYS_CACHE_DIR", str(runtime_dir / "cache")))
    sqlite_path = Path(_env_text(env, "PIXIV_ARTIST_RECSYS_DB_PATH", str(runtime_dir / "pixiv_artist_recsys.sqlite3")))
    raw_mode = _env_text(env, "PIXIV_ARTIST_RECSYS_MODE", AppMode.DEVELOPMENT.value)
    mode = AppMode(raw_mode)
    return AppSettings(
        mode=mode,
        paths=RuntimePaths(
            repo_root=repo_root,
            data_dir=data_dir,
            runtime_dir=runtime_dir,
            logs_dir=logs_dir,
            cache_dir=cache_dir,
        ),
        storage=StorageConfig(sqlite_path=sqlite_path),
        api=ApiConfig(
            host=_env_text(env, "PIXIV_ARTIST_RECSYS_API_HOST", api_defaults.host),
            port=_env_int(env, "PIXIV_ARTIST_RECSYS_API_PORT", api_defaults.port),
        ),
        recommendation=RecommendationConfig(
            max_candidates=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_CANDIDATES", recommendation_defaults.max_candidates),
            max_results=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_RESULTS", recommendation_defaults.max_results),
            freshness_days=_env_int(env, "PIXIV_ARTIST_RECSYS_FRESHNESS_DAYS", recommendation_defaults.freshness_days),
            allow_ai=_env_bool(env, "PIXIV_ARTIST_RECSYS_ALLOW_AI", recommendation_defaults.allow_ai),
            allow_r18=_env_bool(env, "PIXIV_ARTIST_RECSYS_ALLOW_R18", recommendation_defaults.allow_r18),
            min_bookmarks=_env_int(env, "PIXIV_ARTIST_RECSYS_MIN_BOOKMARKS", recommendation_defaults.min_bookmarks),
            min_score=_env_float(env, "PIXIV_ARTIST_RECSYS_MIN_SCORE", recommendation_defaults.min_score),
            diversity_per_tag=_env_int(env, "PIXIV_ARTIST_RECSYS_DIVERSITY_PER_TAG", recommendation_defaults.diversity_per_tag),
            min_local_illusts=_env_int(env, "PIXIV_ARTIST_RECSYS_MIN_LOCAL_ILLUSTS", recommendation_defaults.min_local_illusts),
            require_tag_overlap=_env_bool(env, "PIXIV_ARTIST_RECSYS_REQUIRE_TAG_OVERLAP", recommendation_defaults.require_tag_overlap),
            max_genre_fraction=_env_float(env, "PIXIV_ARTIST_RECSYS_MAX_GENRE_FRACTION", recommendation_defaults.max_genre_fraction),
            followed_artist_limit=_env_int(env, "PIXIV_ARTIST_RECSYS_FOLLOWED_ARTIST_LIMIT", recommendation_defaults.followed_artist_limit),
            candidate_artist_limit=_env_int(env, "PIXIV_ARTIST_RECSYS_CANDIDATE_ARTIST_LIMIT", recommendation_defaults.candidate_artist_limit),
            max_related_per_artist=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_RELATED_PER_ARTIST", recommendation_defaults.max_related_per_artist),
            max_related_per_illust=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_RELATED_PER_ILLUST", recommendation_defaults.max_related_per_illust),
            max_seed_artists=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_SEED_ARTISTS", recommendation_defaults.max_seed_artists),
            max_candidate_artists=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_CANDIDATE_ARTISTS", recommendation_defaults.max_candidate_artists),
            max_user_recommended=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_USER_RECOMMENDED", recommendation_defaults.max_user_recommended),
            max_tag_search_tags=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_TAG_SEARCH_TAGS", recommendation_defaults.max_tag_search_tags),
            max_tag_search_illusts=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_TAG_SEARCH_ILLUSTS", recommendation_defaults.max_tag_search_illusts),
            enable_seed_following=_env_bool(env, "PIXIV_ARTIST_RECSYS_ENABLE_SEED_FOLLOWING", recommendation_defaults.enable_seed_following),
            max_seed_following_artists=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_SEED_FOLLOWING_ARTISTS", recommendation_defaults.max_seed_following_artists),
            max_following_per_seed_artist=_env_int(env, "PIXIV_ARTIST_RECSYS_MAX_FOLLOWING_PER_SEED_ARTIST", recommendation_defaults.max_following_per_seed_artist),
            seed_sample=_env_text(env, "PIXIV_ARTIST_RECSYS_SEED_SAMPLE", recommendation_defaults.seed_sample),
            seed_following_sample=_env_text(env, "PIXIV_ARTIST_RECSYS_SEED_FOLLOWING_SAMPLE", recommendation_defaults.seed_following_sample),
        ),
    )
