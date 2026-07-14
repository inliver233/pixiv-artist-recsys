from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Artist, Illust
from ..pixiv import PixivAppApiClient
from ..storage.repositories import RecommendationRepository


@dataclass(slots=True)
class ArtistIllustHydrationResult:
    seed_user_id: int
    artists_processed: int
    illusts_upserted: int
    scope: str = 'followed'


class ArtistIllustHydrationService:
    def __init__(self, *, repository: RecommendationRepository, pixiv_client: PixivAppApiClient) -> None:
        self.repository = repository
        self.pixiv_client = pixiv_client

    def hydrate_followed_artists(
        self,
        *,
        seed_user_id: int,
        per_artist_limit: int = 12,
        max_artists: int | None = 40,
    ) -> ArtistIllustHydrationResult:
        artists = self.repository.list_followed_artists(seed_user_id=seed_user_id)
        artist_ids = [artist.user_id for artist in artists]
        if max_artists is not None:
            artist_ids = artist_ids[: max(0, int(max_artists))]
        return self._hydrate_artist_ids(
            seed_user_id=seed_user_id,
            artist_user_ids=artist_ids,
            per_artist_limit=per_artist_limit,
            scope='followed',
        )

    def hydrate_candidate_artists(
        self,
        *,
        seed_user_id: int,
        per_artist_limit: int = 8,
        max_artists: int | None = 80,
    ) -> ArtistIllustHydrationResult:
        followed_ids = set(self.repository.list_following_artist_ids(seed_user_id=seed_user_id))
        candidate_ids = []
        for artist_user_id in self.repository.list_candidate_artist_ids(seed_user_id=seed_user_id):
            if artist_user_id in followed_ids:
                continue
            if self.repository.fetch_artist(artist_user_id=artist_user_id) is None:
                self.repository.upsert_artist(Artist(user_id=artist_user_id, name=f'artist-{artist_user_id}', is_followed=False))
            candidate_ids.append(artist_user_id)
            if max_artists is not None and len(candidate_ids) >= max(0, int(max_artists)):
                break
        return self._hydrate_artist_ids(
            seed_user_id=seed_user_id,
            artist_user_ids=candidate_ids,
            per_artist_limit=per_artist_limit,
            scope='candidate',
        )

    def _hydrate_artist_ids(
        self,
        *,
        seed_user_id: int,
        artist_user_ids: list[int],
        per_artist_limit: int,
        scope: str,
    ) -> ArtistIllustHydrationResult:
        illusts_upserted = 0
        for artist_user_id in artist_user_ids:
            page = self.pixiv_client.fetch_user_illusts(user_id=artist_user_id)
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
        return ArtistIllustHydrationResult(
            seed_user_id=seed_user_id,
            artists_processed=len(artist_user_ids),
            illusts_upserted=illusts_upserted,
            scope=scope,
        )
