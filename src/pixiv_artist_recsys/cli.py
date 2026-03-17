from __future__ import annotations

import argparse
import json
import os

from .auth import AccessTokenCache, PixivOAuthService, PixivTokenCoordinator
from .auth.models import PixivTokenRecord
from .config import load_settings
from .ingest import ArtistIllustHydrationService
from .pipeline import LiveRecommendationPipeline, LiveRecommendationRequest, RecommendationPipeline, RecommendationRequest
from .pixiv import CoordinatorBackedAccessTokenProvider, PixivAppApiClient, StaticAccessTokenProvider
from .profile import UserTasteProfileService
from .rank import HeuristicArtistRankService
from .services import DryRunCandidateRetriever, DryRunIngestService, DryRunProfileService, DryRunRankService
from .storage import RecommendationRepository, SQLiteDatabase


def _build_repository() -> RecommendationRepository:
    settings = load_settings()
    settings.ensure_directories()
    repository = RecommendationRepository(SQLiteDatabase(settings.storage.sqlite_path))
    repository.initialize()
    return repository


def _resolve_access_token(access_token: str | None = None) -> str:
    return (access_token or os.getenv("PIXIV_ARTIST_RECSYS_ACCESS_TOKEN", "")).strip()


def _resolve_refresh_token(refresh_token: str | None = None) -> str:
    return (refresh_token or os.getenv("PIXIV_ARTIST_RECSYS_REFRESH_TOKEN", "")).strip()


def _resolve_refresh_token_ref(refresh_token: str | None = None, access_token: str | None = None) -> str:
    resolved_refresh_token = _resolve_refresh_token(refresh_token)
    if resolved_refresh_token:
        return PixivTokenRecord.mask_refresh_token(resolved_refresh_token)
    if _resolve_access_token(access_token):
        return 'access-token-only'
    return 'masked:'


def _build_pixiv_client(
    *,
    repository: RecommendationRepository,
    seed_user_id: int,
    token_key: str | None = None,
    refresh_token: str | None = None,
    access_token: str | None = None,
) -> PixivAppApiClient:
    resolved_access_token = _resolve_access_token(access_token)
    if resolved_access_token:
        provider = StaticAccessTokenProvider(access_token=resolved_access_token)
        return PixivAppApiClient(access_token_provider=provider)

    resolved_refresh_token = _resolve_refresh_token(refresh_token)
    if not resolved_refresh_token:
        raise ValueError("this command requires --refresh-token or PIXIV_ARTIST_RECSYS_REFRESH_TOKEN (or access token equivalent)")

    provider = CoordinatorBackedAccessTokenProvider(
        coordinator=PixivTokenCoordinator(
            cache=AccessTokenCache(),
            oauth_service=PixivOAuthService(),
            repository=repository,
        ),
        token_key=(token_key or f"seed-user:{seed_user_id}"),
        refresh_token=resolved_refresh_token,
    )
    return PixivAppApiClient(access_token_provider=provider)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pixiv_artist_recsys")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Initialize local sqlite database")
    sub.add_parser("show-config", help="Print resolved local settings")

    dry = sub.add_parser("dry-run-recommend", help="Run placeholder recommendation pipeline")
    dry.add_argument("--seed-user-id", type=int, default=1)
    dry.add_argument("--refresh-token-ref", default="masked:token")
    dry.add_argument("--max-results", type=int, default=5)

    hydrate = sub.add_parser("hydrate-followed-illusts", help="Hydrate followed artists' representative illusts into local sqlite")
    hydrate.add_argument("--seed-user-id", type=int, required=True)
    hydrate.add_argument("--token-key")
    hydrate.add_argument("--refresh-token")
    hydrate.add_argument("--access-token")
    hydrate.add_argument("--per-artist-limit", type=int, default=5)

    profile = sub.add_parser("build-profile", help="Build local taste profile from hydrated followed artists")
    profile.add_argument("--seed-user-id", type=int, required=True)
    profile.add_argument("--top-n-tags", type=int, default=20)
    profile.add_argument("--top-n-pairs", type=int, default=20)
    profile.add_argument("--stop-word", action="append", default=[])

    recommend = sub.add_parser("recommend-from-store", help="Rank locally stored candidate artists")
    recommend.add_argument("--seed-user-id", type=int, required=True)
    recommend.add_argument("--max-results", type=int, default=20)

    full = sub.add_parser("full-recommend", help="Run the full live Pixiv recommendation pipeline")
    full.add_argument("--seed-user-id", type=int, required=True)
    full.add_argument("--token-key")
    full.add_argument("--refresh-token")
    full.add_argument("--access-token")
    full.add_argument("--restrict", default="public")
    full.add_argument("--followed-artist-limit", type=int, default=5)
    full.add_argument("--candidate-artist-limit", type=int, default=3)
    full.add_argument("--max-related-per-artist", type=int, default=5)
    full.add_argument("--max-related-per-illust", type=int, default=5)
    full.add_argument("--top-n-tags", type=int, default=20)
    full.add_argument("--top-n-pairs", type=int, default=20)
    full.add_argument("--max-results", type=int, default=20)
    full.add_argument("--allow-ai", action="store_true")
    full.add_argument("--allow-r18", action="store_true")
    full.add_argument("--min-bookmarks", type=int, default=30)
    full.add_argument("--min-score", type=float, default=0.5)
    full.add_argument("--stop-word", action="append", default=[])

    return parser


def cmd_init_db() -> int:
    _build_repository()
    print("initialized")
    return 0


def cmd_show_config() -> int:
    settings = load_settings()
    settings.ensure_directories()
    payload = {
        "mode": settings.mode.value,
        "repo_root": str(settings.paths.repo_root),
        "data_dir": str(settings.paths.data_dir),
        "runtime_dir": str(settings.paths.runtime_dir),
        "db_path": str(settings.storage.sqlite_path),
        "max_results": settings.recommendation.max_results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_dry_run_recommend(seed_user_id: int, refresh_token_ref: str, max_results: int) -> int:
    repository = _build_repository()
    pipeline = RecommendationPipeline(
        repository=repository,
        ingest_service=DryRunIngestService(),
        profile_service=DryRunProfileService(),
        candidate_retriever=DryRunCandidateRetriever(),
        rank_service=DryRunRankService(),
    )
    run = pipeline.run(
        RecommendationRequest(
            seed_user_id=seed_user_id,
            refresh_token_ref=refresh_token_ref,
            max_results=max_results,
        )
    )
    payload = {
        "run_id": run.run_id,
        "seed_user_id": run.seed_user_id,
        "items": [
            {
                "artist_user_id": item.artist.user_id,
                "artist_name": item.artist.name,
                "score": item.score,
                "confidence": item.confidence,
                "reasons": item.reasons,
            }
            for item in run.items
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_hydrate_followed_illusts(
    *,
    seed_user_id: int,
    token_key: str | None,
    refresh_token: str | None,
    access_token: str | None,
    per_artist_limit: int,
) -> int:
    repository = _build_repository()
    pixiv_client = _build_pixiv_client(
        repository=repository,
        seed_user_id=seed_user_id,
        token_key=token_key,
        refresh_token=refresh_token,
        access_token=access_token,
    )
    result = ArtistIllustHydrationService(repository=repository, pixiv_client=pixiv_client).hydrate_followed_artists(
        seed_user_id=seed_user_id,
        per_artist_limit=per_artist_limit,
    )
    payload = {
        "seed_user_id": result.seed_user_id,
        "artists_processed": result.artists_processed,
        "illusts_upserted": result.illusts_upserted,
        "per_artist_limit": per_artist_limit,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_build_profile(*, seed_user_id: int, top_n_tags: int, top_n_pairs: int, stop_words: list[str]) -> int:
    repository = _build_repository()
    summary = UserTasteProfileService(repository=repository, stop_words=set(stop_words)).build_profile(
        seed_user_id=seed_user_id,
        top_n_tags=top_n_tags,
        top_n_pairs=top_n_pairs,
    )
    payload = {
        "seed_user_id": summary.seed_user_id,
        "artist_count": summary.artist_count,
        "top_tags": [
            {"tag": tag, "weight": weight}
            for tag, weight in summary.top_tags
        ],
        "top_pairs": [
            {"tag_a": pair.tag_a, "tag_b": pair.tag_b, "weight": pair.weight}
            for pair in summary.top_pairs
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_recommend_from_store(*, seed_user_id: int, max_results: int) -> int:
    repository = _build_repository()
    result = HeuristicArtistRankService(repository=repository).rank_from_store(seed_user_id=seed_user_id, max_results=max_results)
    payload = {
        "seed_user_id": result.seed_user_id,
        "item_count": len(result.items),
        "items": [
            {
                "artist_user_id": item.artist.user_id,
                "artist_name": item.artist.name,
                "artist_account": item.artist.account,
                "score": item.score,
                "confidence": item.confidence,
                "reasons": item.reasons,
                "top_illust_ids": item.top_illust_ids,
            }
            for item in result.items
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_full_recommend(
    *,
    seed_user_id: int,
    token_key: str | None,
    refresh_token: str | None,
    access_token: str | None,
    restrict: str,
    followed_artist_limit: int,
    candidate_artist_limit: int,
    max_related_per_artist: int,
    max_related_per_illust: int,
    top_n_tags: int,
    top_n_pairs: int,
    max_results: int,
    allow_ai: bool,
    allow_r18: bool,
    min_bookmarks: int,
    min_score: float,
    stop_words: list[str],
) -> int:
    repository = _build_repository()
    pixiv_client = _build_pixiv_client(
        repository=repository,
        seed_user_id=seed_user_id,
        token_key=token_key,
        refresh_token=refresh_token,
        access_token=access_token,
    )
    result = LiveRecommendationPipeline(repository=repository, pixiv_client=pixiv_client, stop_words=set(stop_words)).run(
        LiveRecommendationRequest(
            seed_user_id=seed_user_id,
            refresh_token_ref=_resolve_refresh_token_ref(refresh_token=refresh_token, access_token=access_token),
            restrict=restrict,
            followed_artist_limit=followed_artist_limit,
            candidate_artist_limit=candidate_artist_limit,
            max_related_per_artist=max_related_per_artist,
            max_related_per_illust=max_related_per_illust,
            top_n_tags=top_n_tags,
            top_n_pairs=top_n_pairs,
            max_results=max_results,
            allow_ai=allow_ai,
            allow_r18=allow_r18,
            min_total_bookmarks=min_bookmarks,
            min_score=min_score,
        )
    )
    payload = {
        "run_id": result.run.run_id,
        "mode": result.run.mode,
        "seed_user_id": result.run.seed_user_id,
        "recommended_artist_ids": [item.artist.user_id for item in result.run.items],
        "filters": {
            "allow_ai": allow_ai,
            "allow_r18": allow_r18,
            "min_bookmarks": min_bookmarks,
            "min_score": min_score,
        },
        "stats": {
            "following_synced": result.following_result.synced_count,
            "followed_illusts_upserted": result.followed_hydration_result.illusts_upserted,
            "profile_artist_count": result.profile_summary.artist_count,
            "candidate_count": result.candidate_result.candidate_count,
            "candidate_evidence_count": result.candidate_result.evidence_count,
            "candidate_hydrated_artists": result.candidate_hydration_result.artists_processed,
            "candidate_hydrated_illusts": result.candidate_hydration_result.illusts_upserted,
            "top_tags": [tag for tag, _ in result.profile_summary.top_tags[:5]],
        },
        "items": [
            {
                "artist_user_id": item.artist.user_id,
                "artist_name": item.artist.name,
                "artist_account": item.artist.account,
                "score": item.score,
                "confidence": item.confidence,
                "reasons": item.reasons,
                "top_illust_ids": item.top_illust_ids,
            }
            for item in result.run.items
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init-db":
            return cmd_init_db()
        if args.command == "show-config":
            return cmd_show_config()
        if args.command == "dry-run-recommend":
            return cmd_dry_run_recommend(args.seed_user_id, args.refresh_token_ref, args.max_results)
        if args.command == "hydrate-followed-illusts":
            return cmd_hydrate_followed_illusts(
                seed_user_id=args.seed_user_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
                per_artist_limit=args.per_artist_limit,
            )
        if args.command == "build-profile":
            return cmd_build_profile(
                seed_user_id=args.seed_user_id,
                top_n_tags=args.top_n_tags,
                top_n_pairs=args.top_n_pairs,
                stop_words=args.stop_word,
            )
        if args.command == "recommend-from-store":
            return cmd_recommend_from_store(seed_user_id=args.seed_user_id, max_results=args.max_results)
        if args.command == "full-recommend":
            return cmd_full_recommend(
                seed_user_id=args.seed_user_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
                restrict=args.restrict,
                followed_artist_limit=args.followed_artist_limit,
                candidate_artist_limit=args.candidate_artist_limit,
                max_related_per_artist=args.max_related_per_artist,
                max_related_per_illust=args.max_related_per_illust,
                top_n_tags=args.top_n_tags,
                top_n_pairs=args.top_n_pairs,
                max_results=args.max_results,
                allow_ai=args.allow_ai,
                allow_r18=args.allow_r18,
                min_bookmarks=args.min_bookmarks,
                min_score=args.min_score,
                stop_words=args.stop_word,
            )
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
