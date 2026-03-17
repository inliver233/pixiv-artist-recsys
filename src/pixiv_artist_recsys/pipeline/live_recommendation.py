from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..candidate import CandidateArtistResult, RelatedArtistCandidateService
from ..domain.models import RecommendationRun
from ..ingest import ArtistIllustHydrationResult, ArtistIllustHydrationService, FollowingSyncResult, FollowingSyncService
from ..pixiv import PixivAppApiClient
from ..profile import TasteProfileSummary, UserTasteProfileService
from ..rank import HeuristicArtistRankService, RankedRecommendationResult
from ..storage.repositories import RecommendationRepository


@dataclass(slots=True)
class LiveRecommendationRequest:
    seed_user_id: int
    refresh_token_ref: str
    restrict: str = 'public'
    followed_artist_limit: int = 5
    candidate_artist_limit: int = 3
    max_related_per_artist: int = 5
    max_related_per_illust: int = 5
    top_n_tags: int = 20
    top_n_pairs: int = 20
    max_results: int = 20
    allow_ai: bool = False
    allow_r18: bool = False
    min_total_bookmarks: int = 30
    min_score: float = 0.5
    persist_run: bool = True
    mode: str = 'live-heuristic'


@dataclass(slots=True)
class LiveRecommendationResult:
    run: RecommendationRun
    following_result: FollowingSyncResult
    followed_hydration_result: ArtistIllustHydrationResult
    profile_summary: TasteProfileSummary
    candidate_result: CandidateArtistResult
    candidate_hydration_result: ArtistIllustHydrationResult
    ranked_result: RankedRecommendationResult


class LiveRecommendationPipeline:
    def __init__(
        self,
        *,
        repository: RecommendationRepository,
        pixiv_client: PixivAppApiClient,
        stop_words: set[str] | None = None,
    ) -> None:
        self.repository = repository
        self.following_sync_service = FollowingSyncService(repository=repository, pixiv_client=pixiv_client)
        self.hydration_service = ArtistIllustHydrationService(repository=repository, pixiv_client=pixiv_client)
        self.profile_service = UserTasteProfileService(repository=repository, stop_words=stop_words)
        self.candidate_service = RelatedArtistCandidateService(repository=repository, pixiv_client=pixiv_client)
        self.rank_service = HeuristicArtistRankService(repository=repository)

    def run(self, request: LiveRecommendationRequest) -> LiveRecommendationResult:
        following_result = self.following_sync_service.sync_following(
            seed_user_id=request.seed_user_id,
            refresh_token_ref=request.refresh_token_ref,
            restrict=request.restrict,
            allow_ai=request.allow_ai,
            allow_r18=request.allow_r18,
        )
        followed_hydration_result = self.hydration_service.hydrate_followed_artists(
            seed_user_id=request.seed_user_id,
            per_artist_limit=request.followed_artist_limit,
        )
        profile_summary = self.profile_service.build_profile(
            seed_user_id=request.seed_user_id,
            top_n_tags=request.top_n_tags,
            top_n_pairs=request.top_n_pairs,
        )
        candidate_result = self.candidate_service.build_candidates(
            seed_user_id=request.seed_user_id,
            max_related_per_artist=request.max_related_per_artist,
            max_related_per_illust=request.max_related_per_illust,
        )
        candidate_hydration_result = self.hydration_service.hydrate_candidate_artists(
            seed_user_id=request.seed_user_id,
            per_artist_limit=request.candidate_artist_limit,
        )
        ranked_result = self.rank_service.rank_from_store(
            seed_user_id=request.seed_user_id,
            max_results=request.max_results,
            allow_ai=request.allow_ai,
            allow_r18=request.allow_r18,
            min_total_bookmarks=request.min_total_bookmarks,
            min_score=request.min_score,
        )

        run = RecommendationRun(
            seed_user_id=request.seed_user_id,
            run_id=f"live-{uuid4().hex[:12]}",
            mode=request.mode,
            items=ranked_result.items,
        )
        if request.persist_run:
            self.repository.record_run(run)
        return LiveRecommendationResult(
            run=run,
            following_result=following_result,
            followed_hydration_result=followed_hydration_result,
            profile_summary=profile_summary,
            candidate_result=candidate_result,
            candidate_hydration_result=candidate_hydration_result,
            ranked_result=ranked_result,
        )
