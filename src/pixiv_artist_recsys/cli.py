from __future__ import annotations

import argparse
import json

from .api import serve_api
from .application import ApplicationFacade
from .config import load_settings
from .jobs import SeedJobRequest, SeedJobRunner
from .runtime import AppRuntime
from .storage import RecommendationRepository


def _build_runtime() -> AppRuntime:
    runtime = AppRuntime.create(settings=load_settings())
    runtime.prepare()
    return runtime


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


def _build_facade(*, runtime: AppRuntime | None = None) -> ApplicationFacade:
    return ApplicationFacade(runtime=runtime or _build_runtime(), pixiv_client_factory=_build_pixiv_client)


def _print_payload(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _build_job_runner() -> SeedJobRunner:
    return SeedJobRunner(facade=_build_facade())


def _add_pixiv_token_args(parser: argparse.ArgumentParser, *, include_seed_user: bool = True) -> None:
    if include_seed_user:
        parser.add_argument('--seed-user-id', type=int, required=True)
    parser.add_argument('--token-key')
    parser.add_argument('--refresh-token')
    parser.add_argument('--access-token')


def _add_recommendation_args(parser: argparse.ArgumentParser, *, settings, include_output: bool = False) -> None:
    _add_pixiv_token_args(parser)
    parser.add_argument('--restrict', default='public')
    parser.add_argument('--followed-artist-limit', type=int, default=5)
    parser.add_argument('--candidate-artist-limit', type=int, default=3)
    parser.add_argument('--max-related-per-artist', type=int, default=5)
    parser.add_argument('--max-related-per-illust', type=int, default=5)
    parser.add_argument('--max-seed-artists', type=int, default=40, help='Cap followed artists used for hydration/candidate seeds')
    parser.add_argument('--max-candidate-artists', type=int, default=80, help='Cap candidate artists to hydrate')
    parser.add_argument('--enable-user-recommended', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--max-user-recommended', type=int, default=30)
    parser.add_argument('--enable-tag-search', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--max-tag-search-tags', type=int, default=5)
    parser.add_argument('--max-tag-search-illusts', type=int, default=20)
    parser.add_argument('--top-n-tags', type=int, default=20)
    parser.add_argument('--top-n-pairs', type=int, default=20)
    parser.add_argument('--max-results', type=int, default=settings.recommendation.max_results)
    parser.add_argument('--allow-ai', action=argparse.BooleanOptionalAction, default=settings.recommendation.allow_ai)
    parser.add_argument('--allow-r18', action=argparse.BooleanOptionalAction, default=settings.recommendation.allow_r18)
    parser.add_argument('--min-bookmarks', type=int, default=settings.recommendation.min_bookmarks)
    parser.add_argument('--min-score', type=float, default=settings.recommendation.min_score)
    parser.add_argument('--diversity-per-tag', type=int, default=settings.recommendation.diversity_per_tag)
    parser.add_argument('--stop-word', action='append', default=[])
    if include_output:
        parser.add_argument('--output')


def build_parser() -> argparse.ArgumentParser:
    settings = load_settings()
    parser = argparse.ArgumentParser(prog='pixiv_artist_recsys')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('init-db', help='Initialize local sqlite database')
    sub.add_parser('show-config', help='Print resolved local settings')
    sub.add_parser('show-proxy-state', help='Print proxy pool configuration and health snapshot')
    serve = sub.add_parser('serve-api', help='Run local JSON API server')
    serve.add_argument('--host', default=settings.api.host)
    serve.add_argument('--port', type=int, default=settings.api.port)

    feedback = sub.add_parser('record-feedback', help='Record follow/dislike/block feedback for an artist')
    feedback.add_argument('--seed-user-id', type=int, required=True)
    feedback.add_argument('--artist-user-id', type=int, required=True)
    feedback.add_argument('--action', choices=['follow', 'dislike', 'block'], required=True)
    feedback.add_argument('--source-run-id', default='')
    feedback.add_argument('--note', default='')
    feedback.add_argument('--top-n-tags', type=int, default=20)

    feedback_profile = sub.add_parser('show-feedback-profile', help='Show derived negative profile from recorded feedback')
    feedback_profile.add_argument('--seed-user-id', type=int, required=True)
    feedback_profile.add_argument('--top-n-tags', type=int, default=20)

    run_audit = sub.add_parser('show-run-audit', help='Show stored audit payload for a recommendation run')
    run_audit.add_argument('--run-id', required=True)

    list_runs = sub.add_parser('list-runs', help='List recent recommendation runs')
    list_runs.add_argument('--limit', type=int, default=20)

    export_run = sub.add_parser('export-run', help='Export a recommendation run with items and audit payload')
    export_run.add_argument('--run-id', required=True)
    export_run.add_argument('--output')

    dry = sub.add_parser('dry-run-recommend', help='Run placeholder recommendation pipeline')
    dry.add_argument('--seed-user-id', type=int, default=1)
    dry.add_argument('--refresh-token-ref', default='masked:token')
    dry.add_argument('--max-results', type=int, default=settings.recommendation.max_results)

    hydrate = sub.add_parser('hydrate-followed-illusts', help="Hydrate followed artists' representative illusts into local sqlite")
    hydrate.add_argument('--seed-user-id', type=int, required=True)
    hydrate.add_argument('--token-key')
    hydrate.add_argument('--refresh-token')
    hydrate.add_argument('--access-token')
    hydrate.add_argument('--per-artist-limit', type=int, default=5)

    profile = sub.add_parser('build-profile', help='Build local taste profile from hydrated followed artists')
    profile.add_argument('--seed-user-id', type=int, required=True)
    profile.add_argument('--top-n-tags', type=int, default=20)
    profile.add_argument('--top-n-pairs', type=int, default=20)
    profile.add_argument('--stop-word', action='append', default=[])

    recommend = sub.add_parser('recommend-from-store', help='Rank locally stored candidate artists')
    recommend.add_argument('--seed-user-id', type=int, required=True)
    recommend.add_argument('--max-results', type=int, default=settings.recommendation.max_results)
    recommend.add_argument('--diversity-per-tag', type=int, default=settings.recommendation.diversity_per_tag)

    full = sub.add_parser('full-recommend', help='Run the full live Pixiv recommendation pipeline')
    _add_recommendation_args(full, settings=settings)

    run_seed_job = sub.add_parser('run-seed-job', help='Execute one live recommendation job and write a snapshot file')
    _add_recommendation_args(run_seed_job, settings=settings, include_output=True)

    run_manifest = sub.add_parser('run-manifest', help='Execute multiple recommendation jobs from a local JSON manifest')
    run_manifest.add_argument('--manifest', required=True)
    run_manifest.add_argument('--output-dir')
    run_manifest.add_argument('--fail-fast', action='store_true')

    pixiv_following = sub.add_parser('pixiv-following', help='Fetch current following list via refresh token/access token')
    _add_pixiv_token_args(pixiv_following)
    pixiv_following.add_argument('--restrict', default='public')
    pixiv_following.add_argument('--offset', type=int)

    pixiv_user_detail = sub.add_parser('pixiv-user-detail', help='Fetch Pixiv user detail via refresh token/access token')
    _add_pixiv_token_args(pixiv_user_detail)
    pixiv_user_detail.add_argument('--target-user-id', type=int, required=True)

    pixiv_user_illusts = sub.add_parser('pixiv-user-illusts', help='Fetch Pixiv user illust list via refresh token/access token')
    _add_pixiv_token_args(pixiv_user_illusts)
    pixiv_user_illusts.add_argument('--target-user-id', type=int, required=True)
    pixiv_user_illusts.add_argument('--type', default='illust')
    pixiv_user_illusts.add_argument('--offset', type=int)

    pixiv_illust_detail = sub.add_parser('pixiv-illust-detail', help='Fetch Pixiv illust detail via refresh token/access token')
    _add_pixiv_token_args(pixiv_illust_detail)
    pixiv_illust_detail.add_argument('--illust-id', type=int, required=True)

    pixiv_user_related = sub.add_parser('pixiv-user-related', help='Fetch Pixiv related users via refresh token/access token')
    _add_pixiv_token_args(pixiv_user_related)
    pixiv_user_related.add_argument('--target-user-id', type=int, required=True)
    pixiv_user_related.add_argument('--offset', type=int)

    pixiv_illust_related = sub.add_parser('pixiv-illust-related', help='Fetch Pixiv related illusts via refresh token/access token')
    _add_pixiv_token_args(pixiv_illust_related)
    pixiv_illust_related.add_argument('--illust-id', type=int, required=True)

    return parser


def cmd_init_db() -> int:
    _build_runtime()
    print('initialized')
    return 0


def cmd_show_config() -> int:
    _print_payload(_build_facade().show_config_payload())
    return 0


def cmd_show_proxy_state() -> int:
    _print_payload(_build_facade().show_proxy_state_payload())
    return 0


def cmd_serve_api(*, host: str, port: int) -> int:
    runtime = _build_runtime()
    _print_payload(
        {
            'starting': True,
            'host': host,
            'port': port,
            'db_path': str(runtime.db_path),
        }
    )
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
    _print_payload(
        _build_facade().record_feedback_payload(
            seed_user_id=seed_user_id,
            artist_user_id=artist_user_id,
            action=action,
            source_run_id=source_run_id,
            note=note,
            top_n_tags=top_n_tags,
        )
    )
    return 0


def cmd_show_feedback_profile(*, seed_user_id: int, top_n_tags: int) -> int:
    _print_payload(_build_facade().feedback_profile_payload(seed_user_id=seed_user_id, top_n_tags=top_n_tags))
    return 0


def cmd_show_run_audit(*, run_id: str) -> int:
    _print_payload(_build_facade().run_audit_payload(run_id=run_id))
    return 0


def cmd_list_runs(*, limit: int) -> int:
    _print_payload(_build_facade().list_runs_payload(limit=limit))
    return 0


def cmd_export_run(*, run_id: str, output: str | None = None) -> int:
    _print_payload(_build_facade().export_run_payload(run_id=run_id, output=output))
    return 0


def cmd_dry_run_recommend(seed_user_id: int, refresh_token_ref: str, max_results: int) -> int:
    _print_payload(
        _build_facade().dry_run_recommend_payload(
            seed_user_id=seed_user_id,
            refresh_token_ref=refresh_token_ref,
            max_results=max_results,
        )
    )
    return 0


def cmd_hydrate_followed_illusts(
    *,
    seed_user_id: int,
    token_key: str | None,
    refresh_token: str | None,
    access_token: str | None,
    per_artist_limit: int,
) -> int:
    _print_payload(
        _build_facade().hydrate_followed_illusts_payload(
            seed_user_id=seed_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
            per_artist_limit=per_artist_limit,
        )
    )
    return 0


def cmd_build_profile(*, seed_user_id: int, top_n_tags: int, top_n_pairs: int, stop_words: list[str]) -> int:
    _print_payload(
        _build_facade().build_profile_payload(
            seed_user_id=seed_user_id,
            top_n_tags=top_n_tags,
            top_n_pairs=top_n_pairs,
            stop_words=stop_words,
        )
    )
    return 0


def cmd_recommend_from_store(*, seed_user_id: int, max_results: int, diversity_per_tag: int) -> int:
    _print_payload(
        _build_facade().recommend_from_store_payload(
            seed_user_id=seed_user_id,
            max_results=max_results,
            diversity_per_tag=diversity_per_tag,
        )
    )
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
    max_seed_artists: int,
    max_candidate_artists: int,
    enable_user_recommended: bool,
    max_user_recommended: int,
    enable_tag_search: bool,
    max_tag_search_tags: int,
    max_tag_search_illusts: int,
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
    _print_payload(
        _build_facade().full_recommend_payload(
            seed_user_id=seed_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
            restrict=restrict,
            followed_artist_limit=followed_artist_limit,
            candidate_artist_limit=candidate_artist_limit,
            max_related_per_artist=max_related_per_artist,
            max_related_per_illust=max_related_per_illust,
            max_seed_artists=max_seed_artists,
            max_candidate_artists=max_candidate_artists,
            enable_user_recommended=enable_user_recommended,
            max_user_recommended=max_user_recommended,
            enable_tag_search=enable_tag_search,
            max_tag_search_tags=max_tag_search_tags,
            max_tag_search_illusts=max_tag_search_illusts,
            top_n_tags=top_n_tags,
            top_n_pairs=top_n_pairs,
            max_results=max_results,
            allow_ai=allow_ai,
            allow_r18=allow_r18,
            min_bookmarks=min_bookmarks,
            min_score=min_score,
            diversity_per_tag=diversity_per_tag,
            stop_words=stop_words,
        )
    )
    return 0


def cmd_run_seed_job(
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
    max_seed_artists: int,
    max_candidate_artists: int,
    enable_user_recommended: bool,
    max_user_recommended: int,
    enable_tag_search: bool,
    max_tag_search_tags: int,
    max_tag_search_illusts: int,
    top_n_tags: int,
    top_n_pairs: int,
    max_results: int,
    allow_ai: bool,
    allow_r18: bool,
    min_bookmarks: int,
    min_score: float,
    diversity_per_tag: int,
    stop_words: list[str],
    output: str | None,
) -> int:
    result = _build_job_runner().run(
        SeedJobRequest(
            seed_user_id=seed_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
            restrict=restrict,
            followed_artist_limit=followed_artist_limit,
            candidate_artist_limit=candidate_artist_limit,
            max_related_per_artist=max_related_per_artist,
            max_related_per_illust=max_related_per_illust,
            max_seed_artists=max_seed_artists,
            max_candidate_artists=max_candidate_artists,
            enable_user_recommended=enable_user_recommended,
            max_user_recommended=max_user_recommended,
            enable_tag_search=enable_tag_search,
            max_tag_search_tags=max_tag_search_tags,
            max_tag_search_illusts=max_tag_search_illusts,
            top_n_tags=top_n_tags,
            top_n_pairs=top_n_pairs,
            max_results=max_results,
            allow_ai=allow_ai,
            allow_r18=allow_r18,
            min_bookmarks=min_bookmarks,
            min_score=min_score,
            diversity_per_tag=diversity_per_tag,
            stop_words=tuple(stop_words),
        ),
        output_path=output,
    )
    payload = dict(result.payload)
    payload['output_path'] = result.output_path
    _print_payload(payload)
    return 0


def cmd_run_manifest(*, manifest: str, output_dir: str | None, fail_fast: bool) -> int:
    summary = _build_job_runner().run_manifest(
        manifest_path=manifest,
        output_dir=output_dir,
        fail_fast=fail_fast,
    )
    _print_payload(
        {
            'manifest_path': summary.manifest_path,
            'output_dir': summary.output_dir,
            'jobs_requested': summary.jobs_requested,
            'jobs_succeeded': summary.jobs_succeeded,
            'jobs_failed': summary.jobs_failed,
            'results': [
                {
                    'seed_user_id': item.seed_user_id,
                    'run_id': item.run_id,
                    'output_path': item.output_path,
                }
                for item in summary.results
            ],
            'errors': summary.errors,
        }
    )
    return 0


def cmd_pixiv_following(
    *,
    seed_user_id: int,
    token_key: str | None,
    refresh_token: str | None,
    access_token: str | None,
    restrict: str,
    offset: int | None,
) -> int:
    _print_payload(
        _build_facade().pixiv_following_payload(
            seed_user_id=seed_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
            restrict=restrict,
            offset=offset,
        )
    )
    return 0


def cmd_pixiv_user_detail(
    *,
    seed_user_id: int,
    target_user_id: int,
    token_key: str | None,
    refresh_token: str | None,
    access_token: str | None,
) -> int:
    _print_payload(
        _build_facade().pixiv_user_detail_payload(
            seed_user_id=seed_user_id,
            target_user_id=target_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
        )
    )
    return 0


def cmd_pixiv_user_illusts(
    *,
    seed_user_id: int,
    target_user_id: int,
    token_key: str | None,
    refresh_token: str | None,
    access_token: str | None,
    type_: str,
    offset: int | None,
) -> int:
    _print_payload(
        _build_facade().pixiv_user_illusts_payload(
            seed_user_id=seed_user_id,
            target_user_id=target_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
            type_=type_,
            offset=offset,
        )
    )
    return 0


def cmd_pixiv_illust_detail(
    *,
    seed_user_id: int,
    illust_id: int,
    token_key: str | None,
    refresh_token: str | None,
    access_token: str | None,
) -> int:
    _print_payload(
        _build_facade().pixiv_illust_detail_payload(
            seed_user_id=seed_user_id,
            illust_id=illust_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
        )
    )
    return 0


def cmd_pixiv_user_related(
    *,
    seed_user_id: int,
    target_user_id: int,
    token_key: str | None,
    refresh_token: str | None,
    access_token: str | None,
    offset: int | None,
) -> int:
    _print_payload(
        _build_facade().pixiv_user_related_payload(
            seed_user_id=seed_user_id,
            target_user_id=target_user_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
            offset=offset,
        )
    )
    return 0


def cmd_pixiv_illust_related(
    *,
    seed_user_id: int,
    illust_id: int,
    token_key: str | None,
    refresh_token: str | None,
    access_token: str | None,
) -> int:
    _print_payload(
        _build_facade().pixiv_illust_related_payload(
            seed_user_id=seed_user_id,
            illust_id=illust_id,
            token_key=token_key,
            refresh_token=refresh_token,
            access_token=access_token,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == 'init-db':
            return cmd_init_db()
        if args.command == 'show-config':
            return cmd_show_config()
        if args.command == 'show-proxy-state':
            return cmd_show_proxy_state()
        if args.command == 'serve-api':
            return cmd_serve_api(host=args.host, port=args.port)
        if args.command == 'record-feedback':
            return cmd_record_feedback(
                seed_user_id=args.seed_user_id,
                artist_user_id=args.artist_user_id,
                action=args.action,
                source_run_id=args.source_run_id,
                note=args.note,
                top_n_tags=args.top_n_tags,
            )
        if args.command == 'show-feedback-profile':
            return cmd_show_feedback_profile(seed_user_id=args.seed_user_id, top_n_tags=args.top_n_tags)
        if args.command == 'show-run-audit':
            return cmd_show_run_audit(run_id=args.run_id)
        if args.command == 'list-runs':
            return cmd_list_runs(limit=args.limit)
        if args.command == 'export-run':
            return cmd_export_run(run_id=args.run_id, output=args.output)
        if args.command == 'dry-run-recommend':
            return cmd_dry_run_recommend(args.seed_user_id, args.refresh_token_ref, args.max_results)
        if args.command == 'hydrate-followed-illusts':
            return cmd_hydrate_followed_illusts(
                seed_user_id=args.seed_user_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
                per_artist_limit=args.per_artist_limit,
            )
        if args.command == 'build-profile':
            return cmd_build_profile(
                seed_user_id=args.seed_user_id,
                top_n_tags=args.top_n_tags,
                top_n_pairs=args.top_n_pairs,
                stop_words=args.stop_word,
            )
        if args.command == 'recommend-from-store':
            return cmd_recommend_from_store(seed_user_id=args.seed_user_id, max_results=args.max_results, diversity_per_tag=args.diversity_per_tag)
        if args.command == 'full-recommend':
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
                max_seed_artists=args.max_seed_artists,
                max_candidate_artists=args.max_candidate_artists,
                enable_user_recommended=args.enable_user_recommended,
                max_user_recommended=args.max_user_recommended,
                enable_tag_search=args.enable_tag_search,
                max_tag_search_tags=args.max_tag_search_tags,
                max_tag_search_illusts=args.max_tag_search_illusts,
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
        if args.command == 'run-seed-job':
            return cmd_run_seed_job(
                seed_user_id=args.seed_user_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
                restrict=args.restrict,
                followed_artist_limit=args.followed_artist_limit,
                candidate_artist_limit=args.candidate_artist_limit,
                max_related_per_artist=args.max_related_per_artist,
                max_related_per_illust=args.max_related_per_illust,
                max_seed_artists=args.max_seed_artists,
                max_candidate_artists=args.max_candidate_artists,
                enable_user_recommended=args.enable_user_recommended,
                max_user_recommended=args.max_user_recommended,
                enable_tag_search=args.enable_tag_search,
                max_tag_search_tags=args.max_tag_search_tags,
                max_tag_search_illusts=args.max_tag_search_illusts,
                top_n_tags=args.top_n_tags,
                top_n_pairs=args.top_n_pairs,
                max_results=args.max_results,
                allow_ai=args.allow_ai,
                allow_r18=args.allow_r18,
                min_bookmarks=args.min_bookmarks,
                min_score=args.min_score,
                diversity_per_tag=args.diversity_per_tag,
                stop_words=args.stop_word,
                output=args.output,
            )
        if args.command == 'run-manifest':
            return cmd_run_manifest(manifest=args.manifest, output_dir=args.output_dir, fail_fast=args.fail_fast)
        if args.command == 'pixiv-following':
            return cmd_pixiv_following(
                seed_user_id=args.seed_user_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
                restrict=args.restrict,
                offset=args.offset,
            )
        if args.command == 'pixiv-user-detail':
            return cmd_pixiv_user_detail(
                seed_user_id=args.seed_user_id,
                target_user_id=args.target_user_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
            )
        if args.command == 'pixiv-user-illusts':
            return cmd_pixiv_user_illusts(
                seed_user_id=args.seed_user_id,
                target_user_id=args.target_user_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
                type_=args.type,
                offset=args.offset,
            )
        if args.command == 'pixiv-illust-detail':
            return cmd_pixiv_illust_detail(
                seed_user_id=args.seed_user_id,
                illust_id=args.illust_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
            )
        if args.command == 'pixiv-user-related':
            return cmd_pixiv_user_related(
                seed_user_id=args.seed_user_id,
                target_user_id=args.target_user_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
                offset=args.offset,
            )
        if args.command == 'pixiv-illust-related':
            return cmd_pixiv_illust_related(
                seed_user_id=args.seed_user_id,
                illust_id=args.illust_id,
                token_key=args.token_key,
                refresh_token=args.refresh_token,
                access_token=args.access_token,
            )
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    parser.error(f'unsupported command: {args.command}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
