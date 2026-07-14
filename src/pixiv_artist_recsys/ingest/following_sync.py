from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Artist, SeedUser
from ..pixiv import PixivAppApiClient
from ..storage.repositories import RecommendationRepository
from ..utils.progress import ProgressCallback, emit


@dataclass(slots=True)
class FollowingSyncResult:
    seed_user_id: int
    synced_count: int
    pages_fetched: int


class FollowingSyncService:
    def __init__(self, *, repository: RecommendationRepository, pixiv_client: PixivAppApiClient) -> None:
        self.repository = repository
        self.pixiv_client = pixiv_client

    def sync_following(
        self,
        *,
        seed_user_id: int,
        refresh_token_ref: str,
        restrict: str = 'public',
        allow_ai: bool | None = None,
        allow_r18: bool | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> FollowingSyncResult:
        existing = self.repository.fetch_seed_user(user_id=seed_user_id)
        resolved_allow_ai = existing.allow_ai if allow_ai is None and existing is not None else bool(allow_ai)
        resolved_allow_r18 = existing.allow_r18 if allow_r18 is None and existing is not None else bool(allow_r18)
        self.repository.upsert_seed_user(
            SeedUser(
                user_id=seed_user_id,
                refresh_token_ref=refresh_token_ref,
                allow_ai=resolved_allow_ai,
                allow_r18=resolved_allow_r18,
            )
        )

        # all = public + private (private only works for the token owner's own account).
        restrict_modes = self._restrict_modes(restrict)
        emit(
            on_progress,
            stage='following_sync',
            event='start',
            message=f'sync following for seed={seed_user_id} restrict={"+".join(restrict_modes)}',
            seed_user_id=seed_user_id,
            restrict=restrict,
        )

        pages = 0
        synced_count = 0
        for mode in restrict_modes:
            offset = 0
            while True:
                page = self.pixiv_client.fetch_following_users(user_id=seed_user_id, restrict=mode, offset=offset)
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
                emit(
                    on_progress,
                    stage='following_sync',
                    event='progress',
                    current=synced_count,
                    total=0,
                    message=f'{mode} page {pages}: +{len(page.items)} -> synced={synced_count}',
                    pages_fetched=pages,
                    page_size=len(page.items),
                    offset=offset,
                    has_next=bool(page.next_url),
                    restrict_mode=mode,
                )
                if not page.next_url:
                    break
                offset += len(page.items)

        emit(
            on_progress,
            stage='following_sync',
            event='done',
            current=synced_count,
            message=f'done: synced={synced_count} pages={pages} modes={"+".join(restrict_modes)}',
            pages_fetched=pages,
            synced_count=synced_count,
        )
        return FollowingSyncResult(seed_user_id=seed_user_id, synced_count=synced_count, pages_fetched=pages)

    @staticmethod
    def _restrict_modes(restrict: str) -> list[str]:
        normalized = str(restrict or 'public').strip().lower()
        if normalized in {'all', 'both', 'public+private', 'public,private'}:
            return ['public', 'private']
        if normalized in {'public', 'private'}:
            return [normalized]
        return ['public']
