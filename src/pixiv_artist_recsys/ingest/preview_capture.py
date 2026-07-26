from __future__ import annotations

from typing import Iterable

from ..domain.models import Illust
from ..pixiv.models import PixivUserSummary
from ..storage.repositories import RecommendationRepository


def persist_preview_illusts(
    repository: RecommendationRepository,
    users: Iterable[PixivUserSummary],
    *,
    max_per_user: int = 3,
) -> int:
    """Store the free illusts bundled in user_previews responses.

    Every list API (user_related / user_recommended / following) ships each
    user's ~3 latest full illust objects — tags, bookmarks, ai flags — at zero
    extra request cost. Persisting them is a free hydration stage 1: candidate
    priority scoring gets real bookmark numbers and the ranker can score these
    artists (min_local_illusts=2) before any paid hydration.

    Deliberately does NOT touch artists.hydrated_at_epoch: three latest works
    are not a full portfolio, so skip-if-fresh must not treat them as hydrated.
    """
    saved = 0
    with repository.transaction():
        for user in users:
            for summary in list(getattr(user, 'preview_illusts', None) or [])[: max(0, int(max_per_user))]:
                if summary.illust_id <= 0 or summary.user_id <= 0:
                    continue
                repository.upsert_illust(
                    Illust(
                        illust_id=summary.illust_id,
                        user_id=summary.user_id,
                        title=summary.title,
                        create_date=summary.create_date,
                        total_bookmarks=summary.total_bookmarks,
                        total_view=summary.total_view,
                        total_comments=summary.total_comments,
                        ai_type=summary.ai_type,
                        x_restrict=summary.x_restrict,
                        illust_type=summary.illust_type or '',
                        page_count=max(1, int(summary.page_count or 1)),
                        image_url=str(summary.image_url or ''),
                    )
                )
                if summary.tags:
                    repository.replace_illust_tags(illust_id=summary.illust_id, tags=list(summary.tags))
                saved += 1
    return saved
