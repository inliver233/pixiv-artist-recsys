from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..feedback import FeedbackService
from ..ingest import ArtistIllustHydrationService, FollowingSyncService
from ..pipeline import LiveRecommendationPipeline, LiveRecommendationRequest, RecommendationPipeline, RecommendationRequest
from ..pixiv import PixivInspectorService
from ..profile import UserTasteProfileService
from ..rank import HeuristicArtistRankService
from ..runtime import AppRuntime
from ..services import DryRunCandidateRetriever, DryRunIngestService, DryRunProfileService, DryRunRankService


PixivClientFactory = Callable[..., object]


@dataclass(slots=True)
class ApplicationFacade:
    runtime: AppRuntime
    pixiv_client_factory: PixivClientFactory | None = None

    def init_db(self) -> dict[str, Any]:
        self.runtime.prepare()
        return {'initialized': True, 'db_path': str(self.runtime.db_path)}

    def show_config_payload(self) -> dict[str, Any]:
        payload = self.runtime.settings_payload()
        payload['repo_root'] = payload['paths']['repo_root']
        payload['data_dir'] = payload['paths']['data_dir']
        payload['runtime_dir'] = payload['paths']['runtime_dir']
        payload['db_path'] = payload['storage']['sqlite_path']
        return payload

    def show_proxy_state_payload(self) -> dict[str, Any]:
        return self.runtime.proxy_state_payload()

    def dry_run_recommend_payload(self, *, seed_user_id: int, refresh_token_ref: str, max_results: int) -> dict[str, Any]:
        run = RecommendationPipeline(
            repository=self.runtime.repository,
            ingest_service=DryRunIngestService(),
            profile_service=DryRunProfileService(),
            candidate_retriever=DryRunCandidateRetriever(),
            rank_service=DryRunRankService(),
        ).run(
            RecommendationRequest(
                seed_user_id=seed_user_id,
                refresh_token_ref=refresh_token_ref,
                max_results=max_results,
            )
        )
        return {
            'run_id': run.run_id,
            'seed_user_id': run.seed_user_id,
            'items': self._ranked_items_payload(run.items),
        }

    def record_feedback_payload(
        self,
        *,
        seed_user_id: int,
        artist_user_id: int,
        action: str,
        source_run_id: str = '',
        note: str = '',
        top_n_tags: int = 20,
    ) -> dict[str, Any]:
        summary = FeedbackService(repository=self.runtime.repository).record_feedback(
            seed_user_id=seed_user_id,
            artist_user_id=artist_user_id,
            action=action,
            source_run_id=source_run_id,
            note=note,
            top_n_tags=top_n_tags,
        )
        payload = self.feedback_profile_payload(seed_user_id=seed_user_id, top_n_tags=top_n_tags)
        payload['artist_user_id'] = artist_user_id
        payload['action'] = action
        payload['event_count'] = summary.event_count
        return payload

    def feedback_profile_payload(self, *, seed_user_id: int, top_n_tags: int = 20) -> dict[str, Any]:
        summary = FeedbackService(repository=self.runtime.repository).build_negative_profile(
            seed_user_id=seed_user_id,
            top_n_tags=top_n_tags,
        )
        return {
            'seed_user_id': summary.seed_user_id,
            'event_count': summary.event_count,
            'negative_tags': [{'tag': tag, 'weight': weight} for tag, weight in summary.negative_tags],
            'disliked_artist_ids': summary.disliked_artist_ids,
            'blocked_artist_ids': summary.blocked_artist_ids,
        }

    def run_audit_payload(self, *, run_id: str) -> dict[str, Any]:
        return {
            'run_id': run_id,
            'audit': self.runtime.repository.fetch_run_audit(run_id=run_id),
        }

    def list_runs_payload(self, *, limit: int = 20) -> dict[str, Any]:
        runs = self.runtime.repository.list_recommendation_runs(limit=limit)
        return {
            'count': len(runs),
            'runs': [
                {
                    'run_id': run_id,
                    'seed_user_id': seed_user_id,
                    'mode': mode,
                    'created_at': created_at,
                }
                for run_id, seed_user_id, mode, created_at in runs
            ],
        }

    def export_run_payload(self, *, run_id: str, output: str | None = None) -> dict[str, Any]:
        run = self.runtime.repository.fetch_recommendation_run(run_id=run_id)
        items = self.runtime.repository.fetch_recommendation_items(run_id=run_id)
        payload: dict[str, Any] = {
            'found': run is not None,
            'run': None,
            'audit': self.runtime.repository.fetch_run_audit(run_id=run_id),
            'items': [
                {
                    'artist_user_id': artist_user_id,
                    'score': score,
                    'confidence': confidence,
                    'reasons': reasons,
                    'top_illust_ids': top_illust_ids,
                }
                for artist_user_id, score, confidence, reasons, top_illust_ids in items
            ],
        }
        if run is not None:
            payload['run'] = {
                'run_id': run[0],
                'seed_user_id': run[1],
                'mode': run[2],
                'created_at': run[3],
            }
        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            payload['output_path'] = str(output_path)
        return payload

    def hydrate_followed_illusts_payload(
        self,
        *,
        seed_user_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
        per_artist_limit: int = 5,
    ) -> dict[str, Any]:
        pixiv_client = self._build_pixiv_client(
            seed_user_id=seed_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
        )
        following_result = FollowingSyncService(
            repository=self.runtime.repository,
            pixiv_client=pixiv_client,
        ).sync_following(
            seed_user_id=seed_user_id,
            refresh_token_ref=AppRuntime.resolve_refresh_token_ref(refresh_token=refresh_token, access_token=access_token),
        )
        result = ArtistIllustHydrationService(
            repository=self.runtime.repository,
            pixiv_client=pixiv_client,
        ).hydrate_followed_artists(
            seed_user_id=seed_user_id,
            per_artist_limit=per_artist_limit,
        )
        return {
            'seed_user_id': result.seed_user_id,
            'following_synced': following_result.synced_count,
            'artists_processed': result.artists_processed,
            'illusts_upserted': result.illusts_upserted,
            'per_artist_limit': per_artist_limit,
        }

    def build_profile_payload(
        self,
        *,
        seed_user_id: int,
        top_n_tags: int = 20,
        top_n_pairs: int = 20,
        stop_words: list[str] | set[str] | None = None,
    ) -> dict[str, Any]:
        summary = UserTasteProfileService(
            repository=self.runtime.repository,
            stop_words=set(stop_words or []),
        ).build_profile(
            seed_user_id=seed_user_id,
            top_n_tags=top_n_tags,
            top_n_pairs=top_n_pairs,
        )
        return {
            'seed_user_id': summary.seed_user_id,
            'artist_count': summary.artist_count,
            'top_tags': [{'tag': tag, 'weight': weight} for tag, weight in summary.top_tags],
            'top_pairs': [{'tag_a': pair.tag_a, 'tag_b': pair.tag_b, 'weight': pair.weight} for pair in summary.top_pairs],
        }

    def recommend_from_store_payload(
        self,
        *,
        seed_user_id: int,
        max_results: int,
        diversity_per_tag: int,
        allow_ai: bool | None = None,
        allow_r18: bool | None = None,
        min_bookmarks: int | None = None,
        min_score: float | None = None,
    ) -> dict[str, Any]:
        settings = self.runtime.settings.recommendation
        result = HeuristicArtistRankService(repository=self.runtime.repository).rank_from_store(
            seed_user_id=seed_user_id,
            max_results=max_results,
            allow_ai=allow_ai,
            allow_r18=allow_r18,
            min_total_bookmarks=settings.min_bookmarks if min_bookmarks is None else min_bookmarks,
            min_score=settings.min_score if min_score is None else min_score,
            diversity_primary_tag_limit=diversity_per_tag,
        )
        return {
            'seed_user_id': result.seed_user_id,
            'item_count': len(result.items),
            'diversity_per_tag': diversity_per_tag,
            'items': self._ranked_items_payload(result.items),
        }

    def full_recommend_payload(
        self,
        *,
        seed_user_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
        restrict: str = 'public',
        followed_artist_limit: int = 5,
        candidate_artist_limit: int = 3,
        max_related_per_artist: int = 5,
        max_related_per_illust: int = 5,
        top_n_tags: int = 20,
        top_n_pairs: int = 20,
        max_results: int | None = None,
        allow_ai: bool | None = None,
        allow_r18: bool | None = None,
        min_bookmarks: int | None = None,
        min_score: float | None = None,
        diversity_per_tag: int | None = None,
        stop_words: list[str] | set[str] | None = None,
    ) -> dict[str, Any]:
        pixiv_client = self._build_pixiv_client(
            seed_user_id=seed_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
        )
        settings = self.runtime.settings.recommendation
        result = LiveRecommendationPipeline(
            repository=self.runtime.repository,
            pixiv_client=pixiv_client,
            stop_words=set(stop_words or []),
        ).run(
            LiveRecommendationRequest(
                seed_user_id=seed_user_id,
                refresh_token_ref=AppRuntime.resolve_refresh_token_ref(refresh_token=refresh_token, access_token=access_token),
                restrict=restrict,
                followed_artist_limit=followed_artist_limit,
                candidate_artist_limit=candidate_artist_limit,
                max_related_per_artist=max_related_per_artist,
                max_related_per_illust=max_related_per_illust,
                top_n_tags=top_n_tags,
                top_n_pairs=top_n_pairs,
                max_results=settings.max_results if max_results is None else max_results,
                allow_ai=settings.allow_ai if allow_ai is None else allow_ai,
                allow_r18=settings.allow_r18 if allow_r18 is None else allow_r18,
                min_total_bookmarks=settings.min_bookmarks if min_bookmarks is None else min_bookmarks,
                min_score=settings.min_score if min_score is None else min_score,
                diversity_primary_tag_limit=settings.diversity_per_tag if diversity_per_tag is None else diversity_per_tag,
            )
        )
        resolved_allow_ai = settings.allow_ai if allow_ai is None else allow_ai
        resolved_allow_r18 = settings.allow_r18 if allow_r18 is None else allow_r18
        resolved_min_bookmarks = settings.min_bookmarks if min_bookmarks is None else min_bookmarks
        resolved_min_score = settings.min_score if min_score is None else min_score
        resolved_diversity = settings.diversity_per_tag if diversity_per_tag is None else diversity_per_tag
        return {
            'run_id': result.run.run_id,
            'mode': result.run.mode,
            'seed_user_id': result.run.seed_user_id,
            'recommended_artist_ids': [item.artist.user_id for item in result.run.items],
            'filters': {
                'allow_ai': resolved_allow_ai,
                'allow_r18': resolved_allow_r18,
                'min_bookmarks': resolved_min_bookmarks,
                'min_score': resolved_min_score,
                'diversity_per_tag': resolved_diversity,
            },
            'stats': {
                'following_synced': result.following_result.synced_count,
                'followed_illusts_upserted': result.followed_hydration_result.illusts_upserted,
                'profile_artist_count': result.profile_summary.artist_count,
                'candidate_count': result.candidate_result.candidate_count,
                'candidate_evidence_count': result.candidate_result.evidence_count,
                'candidate_hydrated_artists': result.candidate_hydration_result.artists_processed,
                'candidate_hydrated_illusts': result.candidate_hydration_result.illusts_upserted,
                'top_tags': [tag for tag, _ in result.profile_summary.top_tags[:5]],
            },
            'items': self._ranked_items_payload(result.run.items),
        }

    def pixiv_following_payload(
        self,
        *,
        seed_user_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
        restrict: str = 'public',
        offset: int | None = None,
    ) -> dict[str, Any]:
        return PixivInspectorService(
            pixiv_client=self._build_pixiv_client(
                seed_user_id=seed_user_id,
                token_key=token_key,
                refresh_token=refresh_token,
                access_token=access_token,
            )
        ).following_payload(user_id=seed_user_id, restrict=restrict, offset=offset)

    def pixiv_user_detail_payload(
        self,
        *,
        seed_user_id: int,
        target_user_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        return PixivInspectorService(
            pixiv_client=self._build_pixiv_client(
                seed_user_id=seed_user_id,
                token_key=token_key,
                refresh_token=refresh_token,
                access_token=access_token,
            )
        ).user_detail_payload(user_id=target_user_id)

    def pixiv_user_illusts_payload(
        self,
        *,
        seed_user_id: int,
        target_user_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
        type_: str = 'illust',
        offset: int | None = None,
    ) -> dict[str, Any]:
        return PixivInspectorService(
            pixiv_client=self._build_pixiv_client(
                seed_user_id=seed_user_id,
                token_key=token_key,
                refresh_token=refresh_token,
                access_token=access_token,
            )
        ).user_illusts_payload(user_id=target_user_id, type_=type_, offset=offset)

    def pixiv_illust_detail_payload(
        self,
        *,
        seed_user_id: int,
        illust_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        return PixivInspectorService(
            pixiv_client=self._build_pixiv_client(
                seed_user_id=seed_user_id,
                token_key=token_key,
                refresh_token=refresh_token,
                access_token=access_token,
            )
        ).illust_detail_payload(illust_id=illust_id)

    def pixiv_user_related_payload(
        self,
        *,
        seed_user_id: int,
        target_user_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        return PixivInspectorService(
            pixiv_client=self._build_pixiv_client(
                seed_user_id=seed_user_id,
                token_key=token_key,
                refresh_token=refresh_token,
                access_token=access_token,
            )
        ).user_related_payload(seed_user_id=target_user_id, offset=offset)

    def pixiv_illust_related_payload(
        self,
        *,
        seed_user_id: int,
        illust_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        return PixivInspectorService(
            pixiv_client=self._build_pixiv_client(
                seed_user_id=seed_user_id,
                token_key=token_key,
                refresh_token=refresh_token,
                access_token=access_token,
            )
        ).illust_related_payload(illust_id=illust_id)

    def _build_pixiv_client(
        self,
        *,
        seed_user_id: int,
        token_key: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
    ):
        if self.pixiv_client_factory is not None:
            return self.pixiv_client_factory(
                repository=self.runtime.repository,
                seed_user_id=seed_user_id,
                token_key=token_key,
                refresh_token=refresh_token,
                access_token=access_token,
            )
        return self.runtime.build_pixiv_client(
            seed_user_id=seed_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
        )

    @staticmethod
    def _ranked_items_payload(items) -> list[dict[str, Any]]:
        return [
            {
                'artist_user_id': item.artist.user_id,
                'artist_name': item.artist.name,
                'artist_account': item.artist.account,
                'score': item.score,
                'confidence': item.confidence,
                'reasons': item.reasons,
                'top_illust_ids': item.top_illust_ids,
            }
            for item in items
        ]
