from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class PagedResult(Generic[T]):
    items: list[T]
    next_url: str | None = None


@dataclass(slots=True)
class PixivUserSummary:
    user_id: int
    name: str
    account: str = ""
    profile_image_url: str = ""


@dataclass(slots=True)
class PixivUserDetail:
    user: PixivUserSummary
    total_illusts: int = 0
    total_manga: int = 0
    total_illust_bookmarks_public: int = 0


@dataclass(slots=True)
class PixivIllustSummary:
    illust_id: int
    user_id: int
    title: str
    create_date: str = ""
    total_bookmarks: int = 0
    total_view: int = 0
    total_comments: int = 0


@dataclass(slots=True)
class PixivIllustDetail:
    illust: PixivIllustSummary
    tags: list[str] = field(default_factory=list)
    original_image_url: str = ""
    page_count: int = 1
    ai_type: int = 0
    x_restrict: int = 0
