from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..domain.models import Artist
from ..pixiv import PixivAppApiClient
from ..profile import UserTasteProfileService
from ..storage.repositories import RecommendationRepository


@dataclass(slots=True)
class CandidateArtistResult:
    seed_user_id: int
    candidate_count: int
    evidence_count: int


class RelatedArtistCandidateService:
    def __init__(self, *, repository: RecommendationRepository, pixiv_client: PixivAppApiClient) -> None:
        self.repository = repository
        self.pixiv_client = pixiv_client

    def build_candidates(
        self,
        *,
        seed_user_id: int,
        max_related_per_artist: int = 8,
        max_related_per_illust: int = 8,
        max_seed_artists: int = 40,
    ) -> CandidateArtistResult:
        followed_artist_ids = set(self.repository.list_following_artist_ids(seed_user_id=seed_user_id))
        evidence_rows: list[tuple[int, str, str, float, str]] = []
        hydrated_artist_cache: dict[int, Artist] = {}
        seed_artist_ids = sorted(followed_artist_ids)[: max(0, int(max_seed_artists))]

        for artist_id in seed_artist_ids:
            related_users = self.pixiv_client.fetch_user_related(seed_user_id=artist_id)
            for user in related_users.items[:max_related_per_artist]:
                if user.user_id in followed_artist_ids or user.user_id <= 0:
                    continue
                hydrated_artist_cache[user.user_id] = Artist(user_id=user.user_id, name=user.name, account=user.account, profile_image_url=user.profile_image_url, is_followed=False)
                evidence_rows.append((user.user_id, 'user_related', f'user:{artist_id}', 1.0, f'related-to-user:{artist_id}'))

            for illust_id in self.repository.list_illust_ids_for_artist(artist_user_id=artist_id)[:max_related_per_artist]:
                related_illusts = self.pixiv_client.fetch_illust_related(illust_id=illust_id)
                for illust in related_illusts.items[:max_related_per_illust]:
                    if illust.user_id in followed_artist_ids or illust.user_id <= 0:
                        continue
                    if illust.user_id not in hydrated_artist_cache:
                        existing = self.repository.fetch_artist(artist_user_id=illust.user_id)
                        hydrated_artist_cache[illust.user_id] = existing or Artist(user_id=illust.user_id, name=f'artist-{illust.user_id}', is_followed=False)
                    evidence_rows.append((illust.user_id, 'illust_related', f'illust:{illust_id}', 0.8, f'related-to-illust:{illust_id}'))

        for artist in hydrated_artist_cache.values():
            self.repository.upsert_artist(artist)
        self.repository.replace_artist_candidates(seed_user_id=seed_user_id, candidates=evidence_rows)
        return CandidateArtistResult(seed_user_id=seed_user_id, candidate_count=len({row[0] for row in evidence_rows}), evidence_count=len(evidence_rows))
