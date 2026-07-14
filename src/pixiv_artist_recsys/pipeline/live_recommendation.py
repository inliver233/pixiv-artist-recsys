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
    following_refresh_token_ref: str | None = None
    restrict: str = 'public'
    followed_artist_limit: int = 12
    candidate_artist_limit: int = 8
    max_related_per_artist: int = 8
    max_related_per_illust: int = 8
    max_seed_artists: int = 40
    max_candidate_artists: int = 80
    enable_user_recommended: bool = True
    max_user_recommended: int = 30
    enable_tag_search: bool = True
    max_tag_search_tags: int = 5
    max_tag_search_illusts: int = 20
    top_n_tags: int = 20
    top_n_pairs: int = 20
    max_results: int = 50
    allow_ai: bool = False
    allow_r18: bool = False
    min_total_bookmarks: int = 30
    min_score: float = 0.5
    diversity_primary_tag_limit: int = 2
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
        following_pixiv_client: PixivAppApiClient | None = None,
        stop_words: set[str] | None = None,
    ) -> None:
        self.repository = repository
        # Mother account (optional): only used for following sync to reduce risk.
        following_client = following_pixiv_client or pixiv_client
        self.following_sync_service = FollowingSyncService(repository=repository, pixiv_client=following_client)
        self.hydration_service = ArtistIllustHydrationService(repository=repository, pixiv_client=pixiv_client)
        self.profile_service = UserTasteProfileService(repository=repository, stop_words=stop_words)
        self.candidate_service = RelatedArtistCandidateService(repository=repository, pixiv_client=pixiv_client)
        self.rank_service = HeuristicArtistRankService(repository=repository)

    def run(self, request: LiveRecommendationRequest) -> LiveRecommendationResult:
        following_token_ref = request.following_refresh_token_ref or request.refresh_token_ref
        following_result = self.following_sync_service.sync_following(
            seed_user_id=request.seed_user_id,
            refresh_token_ref=following_token_ref,
            restrict=request.restrict,
            allow_ai=request.allow_ai,
            allow_r18=request.allow_r18,
        )
        followed_hydration_result = self.hydration_service.hydrate_followed_artists(
            seed_user_id=request.seed_user_id,
            per_artist_limit=request.followed_artist_limit,
            max_artists=request.max_seed_artists,
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
            max_seed_artists=request.max_seed_artists,
            enable_user_recommended=request.enable_user_recommended,
            max_user_recommended=request.max_user_recommended,
            enable_tag_search=request.enable_tag_search,
            max_tag_search_tags=request.max_tag_search_tags,
            max_tag_search_illusts=request.max_tag_search_illusts,
        )
        candidate_hydration_result = self.hydration_service.hydrate_candidate_artists(
            seed_user_id=request.seed_user_id,
            per_artist_limit=request.candidate_artist_limit,
            max_artists=request.max_candidate_artists,
        )
        ranked_result = self.rank_service.rank_from_store(
            seed_user_id=request.seed_user_id,
            max_results=request.max_results,
            allow_ai=request.allow_ai,
            allow_r18=request.allow_r18,
            min_total_bookmarks=request.min_total_bookmarks,
            min_score=request.min_score,
            diversity_primary_tag_limit=request.diversity_primary_tag_limit,
        )

        run = RecommendationRun(
            seed_user_id=request.seed_user_id,
            run_id=f"live-{uuid4().hex[:12]}",
            mode=request.mode,
            items=ranked_result.items,
        )
        if request.persist_run:
            self.repository.record_run(run)
            self.repository.upsert_run_audit(
                run_id=run.run_id,
                seed_user_id=request.seed_user_id,
                summary={
                    'mode': request.mode,
                    'filters': {
                        'allow_ai': request.allow_ai,
                        'allow_r18': request.allow_r18,
                        'min_total_bookmarks': request.min_total_bookmarks,
                        'min_score': request.min_score,
                        'diversity_primary_tag_limit': request.diversity_primary_tag_limit,
                    },
                    'following': {
                        'synced_count': following_result.synced_count,
                        'pages_fetched': following_result.pages_fetched,
                        'token_ref': following_token_ref,
                        'ops_token_ref': request.refresh_token_ref,
                        'mother_child_split': bool(
                            request.following_refresh_token_ref
                            and request.following_refresh_token_ref != request.refresh_token_ref
                        ),
                    },
                    'followed_hydration': {
                        'artists_processed': followed_hydration_result.artists_processed,
                        'illusts_upserted': followed_hydration_result.illusts_upserted,
                    },
                    'profile': {
                        'artist_count': profile_summary.artist_count,
                        'top_tags': [tag for tag, _ in profile_summary.top_tags[:10]],
                    },
                    'candidate': {
                        'candidate_count': candidate_result.candidate_count,
                        'evidence_count': candidate_result.evidence_count,
                    },
                    'candidate_hydration': {
                        'artists_processed': candidate_hydration_result.artists_processed,
                        'illusts_upserted': candidate_hydration_result.illusts_upserted,
                    },
                    'ranked': {
                        'item_count': len(ranked_result.items),
                        'artist_user_ids': [item.artist.user_id for item in ranked_result.items],
                    },
                },
            )
        return LiveRecommendationResult(
            run=run,
            following_result=following_result,
            followed_hydration_result=followed_hydration_result,
            profile_summary=profile_summary,
            candidate_result=candidate_result,
            candidate_hydration_result=candidate_hydration_result,
            ranked_result=ranked_result,
        )
