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
from ..utils.progress import ProgressCallback, emit


@dataclass(slots=True)
class LiveRecommendationRequest:
    seed_user_id: int
    refresh_token_ref: str
    following_refresh_token_ref: str | None = None
    restrict: str = 'public'
    followed_artist_limit: int = 16
    candidate_artist_limit: int = 10
    max_related_per_artist: int = 16
    max_related_per_illust: int = 16
    max_seed_artists: int = 600
    max_candidate_artists: int = 2000
    seed_sample: str = 'quality_first'
    enable_user_recommended: bool = True
    max_user_recommended: int = 100
    enable_tag_search: bool = True
    max_tag_search_tags: int = 16
    max_tag_search_illusts: int = 50
    enable_seed_following: bool = True
    max_seed_following_artists: int = 80
    max_following_per_seed_artist: int = 50
    seed_following_sample: str = 'quality_first'
    merge_candidates: bool = True
    top_n_tags: int = 40
    top_n_pairs: int = 30
    profile_min_bookmarks: int = 200
    max_results: int = 500
    allow_ai: bool = False
    allow_r18: bool = False
    min_total_bookmarks: int = 80
    min_score: float = 0.24
    diversity_primary_tag_limit: int = 6
    min_local_illusts: int = 2
    require_tag_overlap: bool = True
    max_genre_fraction: float = 0.34
    max_ai_fraction: float = 0.12
    min_relative_bookmark_ratio: float = 0.35
    sample_salt: int | str | None = None
    explore_ratio: float = 0.25
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
        self.rank_service = HeuristicArtistRankService(
            repository=repository,
            max_genre_fraction=0.34,
            max_ai_fraction=0.12,
            min_relative_bookmark_ratio=0.35,
        )

    def run(
        self,
        request: LiveRecommendationRequest,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> LiveRecommendationResult:
        emit(
            on_progress,
            stage='pipeline',
            event='start',
            message=f'live-recommend seed={request.seed_user_id} mode={request.mode}',
            seed_user_id=request.seed_user_id,
            mode=request.mode,
            max_seed_artists=request.max_seed_artists,
            max_candidate_artists=request.max_candidate_artists,
        )

        following_token_ref = request.following_refresh_token_ref or request.refresh_token_ref
        emit(on_progress, stage='pipeline', event='info', message='stage 1/6 following_sync (mother preferred)')
        following_result = self.following_sync_service.sync_following(
            seed_user_id=request.seed_user_id,
            refresh_token_ref=following_token_ref,
            restrict=request.restrict,
            allow_ai=request.allow_ai,
            allow_r18=request.allow_r18,
            on_progress=on_progress,
        )

        emit(on_progress, stage='pipeline', event='info', message='stage 2/6 hydrate_followed')
        followed_hydration_result = self.hydration_service.hydrate_followed_artists(
            seed_user_id=request.seed_user_id,
            per_artist_limit=request.followed_artist_limit,
            max_artists=request.max_seed_artists,
            seed_sample=request.seed_sample,
            sample_salt=request.sample_salt,
            explore_ratio=request.explore_ratio,
            on_progress=on_progress,
        )

        emit(on_progress, stage='pipeline', event='info', message='stage 3/6 build_profile')
        emit(
            on_progress,
            stage='profile',
            event='start',
            message=(
                f'building taste profile from followed illusts '
                f'(min_artist_bookmarks={request.profile_min_bookmarks})'
            ),
        )
        profile_summary = self.profile_service.build_profile(
            seed_user_id=request.seed_user_id,
            top_n_tags=request.top_n_tags,
            top_n_pairs=request.top_n_pairs,
            min_artist_bookmarks=request.profile_min_bookmarks,
        )
        emit(
            on_progress,
            stage='profile',
            event='done',
            message=f'profile artists={profile_summary.artist_count} top_tags={len(profile_summary.top_tags)}',
            artist_count=profile_summary.artist_count,
            top_tag_count=len(profile_summary.top_tags),
        )

        emit(on_progress, stage='pipeline', event='info', message='stage 4/6 build_candidates')
        candidate_result = self.candidate_service.build_candidates(
            seed_user_id=request.seed_user_id,
            max_related_per_artist=request.max_related_per_artist,
            max_related_per_illust=request.max_related_per_illust,
            max_seed_artists=request.max_seed_artists,
            seed_sample=request.seed_sample,
            enable_user_recommended=request.enable_user_recommended,
            max_user_recommended=request.max_user_recommended,
            enable_tag_search=request.enable_tag_search,
            max_tag_search_tags=request.max_tag_search_tags,
            max_tag_search_illusts=request.max_tag_search_illusts,
            enable_seed_following=request.enable_seed_following,
            max_seed_following_artists=request.max_seed_following_artists,
            max_following_per_seed_artist=request.max_following_per_seed_artist,
            seed_following_sample=request.seed_following_sample,
            merge_candidates=request.merge_candidates,
            sample_salt=request.sample_salt,
            explore_ratio=request.explore_ratio,
            on_progress=on_progress,
        )

        emit(on_progress, stage='pipeline', event='info', message='stage 5/6 hydrate_candidates')
        candidate_hydration_result = self.hydration_service.hydrate_candidate_artists(
            seed_user_id=request.seed_user_id,
            per_artist_limit=request.candidate_artist_limit,
            max_artists=request.max_candidate_artists,
            seed_sample=request.seed_sample,
            sample_salt=request.sample_salt,
            explore_ratio=request.explore_ratio,
            on_progress=on_progress,
        )

        emit(on_progress, stage='pipeline', event='info', message='stage 6/6 rank_from_store')
        emit(on_progress, stage='rank', event='start', message='ranking candidates')
        ranked_result = self.rank_service.rank_from_store(
            seed_user_id=request.seed_user_id,
            max_results=request.max_results,
            allow_ai=request.allow_ai,
            allow_r18=request.allow_r18,
            min_total_bookmarks=request.min_total_bookmarks,
            min_score=request.min_score,
            diversity_primary_tag_limit=request.diversity_primary_tag_limit,
            min_local_illusts=request.min_local_illusts,
            require_tag_overlap=request.require_tag_overlap,
            max_genre_fraction=request.max_genre_fraction,
            max_ai_fraction=request.max_ai_fraction,
            min_relative_bookmark_ratio=request.min_relative_bookmark_ratio,
        )
        emit(
            on_progress,
            stage='rank',
            event='done',
            current=len(ranked_result.items),
            total=request.max_results,
            message=f'ranked items={len(ranked_result.items)}',
            item_count=len(ranked_result.items),
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
                        'min_local_illusts': request.min_local_illusts,
                        'require_tag_overlap': request.require_tag_overlap,
                        'max_genre_fraction': request.max_genre_fraction,
                        'max_ai_fraction': request.max_ai_fraction,
                        'min_relative_bookmark_ratio': request.min_relative_bookmark_ratio,
                        'profile_min_bookmarks': request.profile_min_bookmarks,
                        'merge_candidates': request.merge_candidates,
                        'seed_sample': request.seed_sample,
                        'sample_salt': request.sample_salt,
                        'explore_ratio': request.explore_ratio,
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
        emit(
            on_progress,
            stage='pipeline',
            event='done',
            message=f'pipeline complete run_id={run.run_id} items={len(ranked_result.items)}',
            run_id=run.run_id,
            item_count=len(ranked_result.items),
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
