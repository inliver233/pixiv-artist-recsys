from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api import serve_api
from .config import load_settings
from .feedback import FeedbackService
from .ingest import ArtistIllustHydrationService
from .pipeline import LiveRecommendationPipeline, LiveRecommendationRequest, RecommendationPipeline, RecommendationRequest
from .profile import UserTasteProfileService
from .rank import HeuristicArtistRankService
from .runtime import AppRuntime
from .services import DryRunCandidateRetriever, DryRunIngestService, DryRunProfileService, DryRunRankService
from .storage import RecommendationRepository


def _build_runtime() -> AppRuntime:
    runtime = AppRuntime.create(settings=load_settings())
    runtime.prepare()
    return runtime


def _build_repository() -> RecommendationRepository:
    return _build_runtime().repository


def _build_pixiv_client(
    *,
    repository: RecommendationRepository,
    seed_user_id: int,
    token_key: str | None = None,
    refresh_token: str | None = None,
    access_token: str | None = None,
):
    runtime = AppRuntime.create(settings=load_settings())
    runtime.repository = repository
    runtime.settings.ensure_directories()
    return runtime.build_pixiv_client(
        seed_user_id=seed_user_id,
        token_key=token_key,
        refresh_token=refresh_token,
        access_token=access_token,
    )


def build_parser() -> argparse.ArgumentParser:
    settings = load_settings()
    parser = argparse.ArgumentParser(prog="pixiv_artist_recsys")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Initialize local sqlite database")
    sub.add_parser("show-config", help="Print resolved local settings")
    sub.add_parser("show-proxy-state", help="Print proxy pool configuration and health snapshot")
    serve = sub.add_parser("serve-api", help="Run local JSON API server")
    serve.add_argument("--host", default=settings.api.host)
    serve.add_argument("--port", type=int, default=settings.api.port)

    feedback = sub.add_parser("record-feedback", help="Record follow/dislike/block feedback for an artist")
    feedback.add_argument("--seed-user-id", type=int, required=True)
    feedback.add_argument("--artist-user-id", type=int, required=True)
    feedback.add_argument("--action", choices=["follow", "dislike", "block"], required=True)
    feedback.add_argument("--source-run-id", default="")
    feedback.add_argument("--note", default="")
    feedback.add_argument("--top-n-tags", type=int, default=20)

    feedback_profile = sub.add_parser("show-feedback-profile", help="Show derived negative profile from recorded feedback")
    feedback_profile.add_argument("--seed-user-id", type=int, required=True)
    feedback_profile.add_argument("--top-n-tags", type=int, default=20)

    run_audit = sub.add_parser("show-run-audit", help="Show stored audit payload for a recommendation run")
    run_audit.add_argument("--run-id", required=True)

    list_runs = sub.add_parser("list-runs", help="List recent recommendation runs")
    list_runs.add_argument("--limit", type=int, default=20)

    export_run = sub.add_parser("export-run", help="Export a recommendation run with items and audit payload")
    export_run.add_argument("--run-id", required=True)
    export_run.add_argument("--output")

    dry = sub.add_parser("dry-run-recommend", help="Run placeholder recommendation pipeline")
    dry.add_argument("--seed-user-id", type=int, default=1)
    dry.add_argument("--refresh-token-ref", default="masked:token")
    dry.add_argument("--max-results", type=int, default=settings.recommendation.max_results)

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
    recommend.add_argument("--max-results", type=int, default=settings.recommendation.max_results)
    recommend.add_argument("--diversity-per-tag", type=int, default=settings.recommendation.diversity_per_tag)

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
    full.add_argument("--max-results", type=int, default=settings.recommendation.max_results)
    full.add_argument("--allow-ai", action=argparse.BooleanOptionalAction, default=settings.recommendation.allow_ai)
    full.add_argument("--allow-r18", action=argparse.BooleanOptionalAction, default=settings.recommendation.allow_r18)
    full.add_argument("--min-bookmarks", type=int, default=settings.recommendation.min_bookmarks)
    full.add_argument("--min-score", type=float, default=settings.recommendation.min_score)
    full.add_argument("--diversity-per-tag", type=int, default=settings.recommendation.diversity_per_tag)
    full.add_argument("--stop-word", action="append", default=[])

    return parser


def cmd_init_db() -> int:
    _build_repository()
    print("initialized")
    return 0


def cmd_show_config() -> int:
    runtime = _build_runtime()
    payload = runtime.settings_payload()
    payload["repo_root"] = payload["paths"]["repo_root"]
    payload["data_dir"] = payload["paths"]["data_dir"]
    payload["runtime_dir"] = payload["paths"]["runtime_dir"]
    payload["db_path"] = payload["storage"]["sqlite_path"]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_show_proxy_state() -> int:
    payload = _build_runtime().proxy_state_payload()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_serve_api(*, host: str, port: int) -> int:
    runtime = _build_runtime()
    payload = {
        "starting": True,
        "host": host,
        "port": port,
        "db_path": str(runtime.db_path),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    serve_api(runtime=runtime, host=host, port=port)
    return 0


def cmd_record_feedback(
    *,
    seed_user_id: int,
    artist_user_id: int,
    action: str,
    source_run_id: str,
    note: str,
    top_n_tags: int,
) -> int:
    repository = _build_repository()
    summary = FeedbackService(repository=repository).record_feedback(
        seed_user_id=seed_user_id,
        artist_user_id=artist_user_id,
        action=action,
        source_run_id=source_run_id,
        note=note,
        top_n_tags=top_n_tags,
    )
    payload = {
        "seed_user_id": summary.seed_user_id,
        "artist_user_id": artist_user_id,
        "action": action,
        "event_count": summary.event_count,
        "negative_tags": [{"tag": tag, "weight": weight} for tag, weight in summary.negative_tags],
        "disliked_artist_ids": summary.disliked_artist_ids,
        "blocked_artist_ids": summary.blocked_artist_ids,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_show_feedback_profile(*, seed_user_id: int, top_n_tags: int) -> int:
    repository = _build_repository()
    summary = FeedbackService(repository=repository).build_negative_profile(seed_user_id=seed_user_id, top_n_tags=top_n_tags)
    payload = {
        "seed_user_id": summary.seed_user_id,
        "event_count": summary.event_count,
        "negative_tags": [{"tag": tag, "weight": weight} for tag, weight in summary.negative_tags],
        "disliked_artist_ids": summary.disliked_artist_ids,
        "blocked_artist_ids": summary.blocked_artist_ids,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_show_run_audit(*, run_id: str) -> int:
    repository = _build_repository()
    payload = {
        "run_id": run_id,
        "audit": repository.fetch_run_audit(run_id=run_id),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_list_runs(*, limit: int) -> int:
    repository = _build_repository()
    runs = repository.list_recommendation_runs(limit=limit)
    payload = {
        "count": len(runs),
        "runs": [
            {
                "run_id": run_id,
                "seed_user_id": seed_user_id,
                "mode": mode,
                "created_at": created_at,
            }
            for run_id, seed_user_id, mode, created_at in runs
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_export_run(*, run_id: str, output: str | None = None) -> int:
    repository = _build_repository()
    run = repository.fetch_recommendation_run(run_id=run_id)
    items = repository.fetch_recommendation_items(run_id=run_id)
    payload = {
        "found": run is not None,
        "run": None,
        "audit": repository.fetch_run_audit(run_id=run_id),
        "items": [
            {
                "artist_user_id": artist_user_id,
                "score": score,
                "confidence": confidence,
                "reasons": reasons,
                "top_illust_ids": top_illust_ids,
            }
            for artist_user_id, score, confidence, reasons, top_illust_ids in items
        ],
    }
    if run is not None:
        payload["run"] = {
            "run_id": run[0],
            "seed_user_id": run[1],
            "mode": run[2],
            "created_at": run[3],
        }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        payload["output_path"] = str(output_path)
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
    runtime = _build_runtime()
    pixiv_client = _build_pixiv_client(
        repository=runtime.repository,
        seed_user_id=seed_user_id,
        token_key=token_key,
        refresh_token=refresh_token,
        access_token=access_token,
    )
    result = ArtistIllustHydrationService(repository=runtime.repository, pixiv_client=pixiv_client).hydrate_followed_artists(
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
        "top_tags": [{"tag": tag, "weight": weight} for tag, weight in summary.top_tags],
        "top_pairs": [{"tag_a": pair.tag_a, "tag_b": pair.tag_b, "weight": pair.weight} for pair in summary.top_pairs],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_recommend_from_store(*, seed_user_id: int, max_results: int, diversity_per_tag: int) -> int:
    repository = _build_repository()
    result = HeuristicArtistRankService(repository=repository).rank_from_store(
        seed_user_id=seed_user_id,
        max_results=max_results,
        diversity_primary_tag_limit=diversity_per_tag,
    )
    payload = {
        "seed_user_id": result.seed_user_id,
        "item_count": len(result.items),
        "diversity_per_tag": diversity_per_tag,
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
    diversity_per_tag: int,
    stop_words: list[str],
) -> int:
    runtime = _build_runtime()
    pixiv_client = _build_pixiv_client(
        repository=runtime.repository,
        seed_user_id=seed_user_id,
        token_key=token_key,
        refresh_token=refresh_token,
        access_token=access_token,
    )
    result = LiveRecommendationPipeline(repository=runtime.repository, pixiv_client=pixiv_client, stop_words=set(stop_words)).run(
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
            max_results=max_results,
            allow_ai=allow_ai,
            allow_r18=allow_r18,
            min_total_bookmarks=min_bookmarks,
            min_score=min_score,
            diversity_primary_tag_limit=diversity_per_tag,
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
            "diversity_per_tag": diversity_per_tag,
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
        if args.command == "show-proxy-state":
            return cmd_show_proxy_state()
        if args.command == "serve-api":
            return cmd_serve_api(host=args.host, port=args.port)
        if args.command == "record-feedback":
            return cmd_record_feedback(
                seed_user_id=args.seed_user_id,
                artist_user_id=args.artist_user_id,
                action=args.action,
                source_run_id=args.source_run_id,
                note=args.note,
                top_n_tags=args.top_n_tags,
            )
        if args.command == "show-feedback-profile":
            return cmd_show_feedback_profile(seed_user_id=args.seed_user_id, top_n_tags=args.top_n_tags)
        if args.command == "show-run-audit":
            return cmd_show_run_audit(run_id=args.run_id)
        if args.command == "list-runs":
            return cmd_list_runs(limit=args.limit)
        if args.command == "export-run":
            return cmd_export_run(run_id=args.run_id, output=args.output)
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
            return cmd_recommend_from_store(seed_user_id=args.seed_user_id, max_results=args.max_results, diversity_per_tag=args.diversity_per_tag)
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
                diversity_per_tag=args.diversity_per_tag,
                stop_words=args.stop_word,
            )
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
