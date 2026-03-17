from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .config import load_settings
from .pipeline import RecommendationPipeline, RecommendationRequest
from .services import DryRunCandidateRetriever, DryRunIngestService, DryRunProfileService, DryRunRankService
from .storage import RecommendationRepository, SQLiteDatabase


def _build_repository() -> RecommendationRepository:
    settings = load_settings()
    settings.ensure_directories()
    repository = RecommendationRepository(SQLiteDatabase(settings.storage.sqlite_path))
    repository.initialize()
    return repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pixiv_artist_recsys")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Initialize local sqlite database")
    sub.add_parser("show-config", help="Print resolved local settings")

    dry = sub.add_parser("dry-run-recommend", help="Run placeholder recommendation pipeline")
    dry.add_argument("--seed-user-id", type=int, default=1)
    dry.add_argument("--refresh-token-ref", default="masked:token")
    dry.add_argument("--max-results", type=int, default=5)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init-db":
        return cmd_init_db()
    if args.command == "show-config":
        return cmd_show_config()
    if args.command == "dry-run-recommend":
        return cmd_dry_run_recommend(args.seed_user_id, args.refresh_token_ref, args.max_results)
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
