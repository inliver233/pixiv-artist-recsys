from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Illust
from ..pixiv import PixivAppApiClient
from ..storage.repositories import RecommendationRepository


@dataclass(slots=True)
class ArtistIllustHydrationResult:
    seed_user_id: int
    artists_processed: int
    illusts_upserted: int


class ArtistIllustHydrationService:
    def __init__(self, *, repository: RecommendationRepository, pixiv_client: PixivAppApiClient) -> None:
        self.repository = repository
        self.pixiv_client = pixiv_client

    def hydrate_followed_artists(self, *, seed_user_id: int, per_artist_limit: int = 5) -> ArtistIllustHydrationResult:
        artists = self.repository.list_followed_artists(seed_user_id=seed_user_id)
        illusts_upserted = 0
        for artist in artists:
            page = self.pixiv_client.fetch_user_illusts(user_id=artist.user_id)
            for summary in page.items[:per_artist_limit]:
                detail = self.pixiv_client.fetch_illust_detail(illust_id=summary.illust_id)
                self.repository.upsert_illust(Illust(
                    illust_id=detail.illust.illust_id,
                    user_id=detail.illust.user_id,
                    title=detail.illust.title,
                    create_date=detail.illust.create_date,
                    total_bookmarks=detail.illust.total_bookmarks,
                    total_view=detail.illust.total_view,
                    total_comments=detail.illust.total_comments,
                    ai_type=detail.ai_type,
                    x_restrict=detail.x_restrict,
                ))
                self.repository.replace_illust_tags(illust_id=detail.illust.illust_id, tags=detail.tags)
                illusts_upserted += 1
        return ArtistIllustHydrationResult(seed_user_id=seed_user_id, artists_processed=len(artists), illusts_upserted=illusts_upserted)
