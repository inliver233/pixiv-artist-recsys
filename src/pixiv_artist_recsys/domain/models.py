from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(slots=True)
class SeedUser:
    user_id: int
    refresh_token_ref: str
    allow_ai: bool = False
    allow_r18: bool = False


@dataclass(slots=True)
class Artist:
    user_id: int
    name: str
    account: str = ""
    is_followed: bool = False
    profile_image_url: str = ""


@dataclass(slots=True)
class Illust:
    illust_id: int
    user_id: int
    title: str
    create_date: str = ""
    total_bookmarks: int = 0
    total_view: int = 0
    total_comments: int = 0
    ai_type: int = 0
    x_restrict: int = 0
    # Pixiv type: "illust" | "manga" | "ugoira" (empty when unknown / legacy rows).
    illust_type: str = ""
    page_count: int = 1


@dataclass(slots=True)
class CandidateEvidence:
    source_type: str
    source_key: str
    weight: float = 0.0
    detail: str = ""


@dataclass(slots=True)
class RecommendationItem:
    artist: Artist
    score: float
    confidence: float
    reasons: list[str] = field(default_factory=list)
    top_illust_ids: list[int] = field(default_factory=list)
    evidence: list[CandidateEvidence] = field(default_factory=list)


@dataclass(slots=True)
class RecommendationRun:
    seed_user_id: int
    run_id: str
    mode: str = "dry-run"
    items: Sequence[RecommendationItem] = field(default_factory=list)
