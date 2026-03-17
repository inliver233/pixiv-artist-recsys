from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import os


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
    max_candidates: int = 300
    max_results: int = 50
    freshness_days: int = 180
    allow_ai: bool = False
    allow_r18: bool = False


@dataclass(slots=True)
class AppSettings:
    mode: AppMode
    paths: RuntimePaths
    storage: StorageConfig
    recommendation: RecommendationConfig = field(default_factory=RecommendationConfig)

    def ensure_directories(self) -> None:
        self.paths.ensure()
        self.storage.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_settings() -> AppSettings:
    repo_root = _repo_root()
    data_dir = Path(os.getenv("PIXIV_ARTIST_RECSYS_DATA_DIR", repo_root / "data"))
    runtime_dir = Path(os.getenv("PIXIV_ARTIST_RECSYS_RUNTIME_DIR", data_dir / "runtime"))
    logs_dir = Path(os.getenv("PIXIV_ARTIST_RECSYS_LOGS_DIR", runtime_dir / "logs"))
    cache_dir = Path(os.getenv("PIXIV_ARTIST_RECSYS_CACHE_DIR", runtime_dir / "cache"))
    sqlite_path = Path(os.getenv("PIXIV_ARTIST_RECSYS_DB_PATH", runtime_dir / "pixiv_artist_recsys.sqlite3"))
    raw_mode = os.getenv("PIXIV_ARTIST_RECSYS_MODE", AppMode.DEVELOPMENT.value)
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
    )
