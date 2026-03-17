from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Artist, SeedUser
from ..pixiv import PixivAppApiClient
from ..storage.repositories import RecommendationRepository


@dataclass(slots=True)
class FollowingSyncResult:
    seed_user_id: int
    synced_count: int
    pages_fetched: int


class FollowingSyncService:
    def __init__(self, *, repository: RecommendationRepository, pixiv_client: PixivAppApiClient) -> None:
        self.repository = repository
        self.pixiv_client = pixiv_client

    def sync_following(self, *, seed_user_id: int, refresh_token_ref: str, restrict: str = 'public') -> FollowingSyncResult:
        self.repository.upsert_seed_user(SeedUser(user_id=seed_user_id, refresh_token_ref=refresh_token_ref))

        offset = 0
        pages = 0
        synced_count = 0
        while True:
            page = self.pixiv_client.fetch_following_users(user_id=seed_user_id, restrict=restrict, offset=offset)
            pages += 1
            if not page.items:
                break
            for item in page.items:
                self.repository.upsert_artist(
                    Artist(
                        user_id=item.user_id,
                        name=item.name,
                        account=item.account,
                        is_followed=True,
                        profile_image_url=item.profile_image_url,
                    )
                )
                self.repository.upsert_following_edge(seed_user_id=seed_user_id, artist_user_id=item.user_id)
                synced_count += 1
            if not page.next_url:
                break
            offset += len(page.items)
        return FollowingSyncResult(seed_user_id=seed_user_id, synced_count=synced_count, pages_fetched=pages)
