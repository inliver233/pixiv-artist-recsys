from __future__ import annotations

import json
from dataclasses import dataclass, field, fields as dataclass_fields
from pathlib import Path
from typing import Any

from ..application import ApplicationFacade
from ..application.params import FullRecommendParams


@dataclass(slots=True)
class SeedJobRequest:
    seed_user_id: int
    token_key: str | None = None
    refresh_token: str | None = None
    access_token: str | None = None
    following_refresh_token: str | None = None
    following_token_key: str | None = None
    restrict: str = 'public'
    followed_artist_limit: int = 16
    candidate_artist_limit: int = 10
    max_related_per_artist: int = 16
    max_related_per_illust: int = 16
    max_illusts_for_related: int | None = None
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
    merge_candidates: bool | None = None
    top_n_tags: int = 40
    top_n_pairs: int = 30
    profile_min_bookmarks: int | None = None
    max_results: int | None = None
    allow_ai: bool | None = None
    allow_r18: bool | None = None
    min_bookmarks: int | None = None
    min_score: float | None = None
    diversity_per_tag: int | None = None
    min_local_illusts: int | None = None
    require_tag_overlap: bool | None = None
    max_genre_fraction: float | None = None
    max_ai_fraction: float | None = None
    min_relative_bookmark_ratio: float | None = None
    sample_salt: int | str | None = None
    explore_ratio: float | None = None
    skip_sync_if_fresh: bool = False
    light_round: bool = False
    stop_words: tuple[str, ...] = field(default_factory=tuple)
    output_name: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> 'SeedJobRequest':
        if 'seed_user_id' not in payload:
            raise ValueError('manifest job missing seed_user_id')
        # All recommendation knobs are parsed by the single shared definition;
        # only job identity/token fields are handled here.
        params = FullRecommendParams.from_mapping(payload)
        shared = {f.name: getattr(params, f.name) for f in dataclass_fields(FullRecommendParams)}
        return cls(
            seed_user_id=int(payload['seed_user_id']),
            token_key=_optional_text(payload.get('token_key')),
            refresh_token=_optional_text(payload.get('refresh_token')),
            access_token=_optional_text(payload.get('access_token')),
            following_refresh_token=_optional_text(payload.get('following_refresh_token')),
            following_token_key=_optional_text(payload.get('following_token_key')),
            output_name=_optional_text(payload.get('output_name')),
            **shared,
        )


@dataclass(slots=True)
class JobRunResult:
    seed_user_id: int
    run_id: str
    output_path: str
    payload: dict[str, Any]


@dataclass(slots=True)
class ManifestRunResult:
    manifest_path: str
    output_dir: str
    jobs_requested: int
    jobs_succeeded: int
    jobs_failed: int
    results: list[JobRunResult]
    errors: list[dict[str, Any]]


class SeedJobRunner:
    def __init__(self, *, facade: ApplicationFacade) -> None:
        self.facade = facade

    def run(self, request: SeedJobRequest, *, output_path: str | Path | None = None) -> JobRunResult:
        payload = self.facade.full_recommend_payload(
            seed_user_id=request.seed_user_id,
            token_key=request.token_key,
            refresh_token=request.refresh_token,
            access_token=request.access_token,
            following_refresh_token=request.following_refresh_token,
            following_token_key=request.following_token_key,
            restrict=request.restrict,
            followed_artist_limit=request.followed_artist_limit,
            candidate_artist_limit=request.candidate_artist_limit,
            max_related_per_artist=request.max_related_per_artist,
            max_related_per_illust=request.max_related_per_illust,
            max_illusts_for_related=request.max_illusts_for_related,
            max_seed_artists=request.max_seed_artists,
            max_candidate_artists=request.max_candidate_artists,
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
            top_n_tags=request.top_n_tags,
            top_n_pairs=request.top_n_pairs,
            profile_min_bookmarks=request.profile_min_bookmarks,
            max_results=request.max_results,
            allow_ai=request.allow_ai,
            allow_r18=request.allow_r18,
            min_bookmarks=request.min_bookmarks,
            min_score=request.min_score,
            diversity_per_tag=request.diversity_per_tag,
            min_local_illusts=request.min_local_illusts,
            require_tag_overlap=request.require_tag_overlap,
            max_genre_fraction=request.max_genre_fraction,
            max_ai_fraction=request.max_ai_fraction,
            min_relative_bookmark_ratio=request.min_relative_bookmark_ratio,
            sample_salt=request.sample_salt,
            explore_ratio=request.explore_ratio,
            skip_sync_if_fresh=request.skip_sync_if_fresh,
            light_round=request.light_round,
            stop_words=list(request.stop_words),
        )
        resolved_output = Path(output_path) if output_path is not None else self._default_output_path(request)
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        resolved_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return JobRunResult(
            seed_user_id=request.seed_user_id,
            run_id=str(payload.get('run_id', '')),
            output_path=str(resolved_output),
            payload=payload,
        )

    def run_manifest(
        self,
        *,
        manifest_path: str | Path,
        output_dir: str | Path | None = None,
        fail_fast: bool = False,
    ) -> ManifestRunResult:
        manifest_file = Path(manifest_path)
        jobs = load_job_manifest(manifest_file)
        resolved_output_dir = Path(output_dir) if output_dir is not None else self.facade.runtime.settings.paths.runtime_dir / 'job_exports'
        results: list[JobRunResult] = []
        errors: list[dict[str, Any]] = []
        for job in jobs:
            output_path = resolved_output_dir / (job.output_name or f'seed-{job.seed_user_id}.json')
            try:
                results.append(self.run(job, output_path=output_path))
            except Exception as exc:  # noqa: BLE001
                errors.append({'seed_user_id': job.seed_user_id, 'message': str(exc)})
                if fail_fast:
                    break
        return ManifestRunResult(
            manifest_path=str(manifest_file),
            output_dir=str(resolved_output_dir),
            jobs_requested=len(jobs),
            jobs_succeeded=len(results),
            jobs_failed=len(errors),
            results=results,
            errors=errors,
        )

    def _default_output_path(self, request: SeedJobRequest) -> Path:
        output_dir = self.facade.runtime.settings.paths.runtime_dir / 'job_exports'
        filename = request.output_name or f'seed-{request.seed_user_id}.json'
        return output_dir / filename


def load_job_manifest(path: str | Path) -> list[SeedJobRequest]:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding='utf-8'))
    if isinstance(payload, dict):
        jobs_payload = payload.get('jobs', [])
    elif isinstance(payload, list):
        jobs_payload = payload
    else:
        raise ValueError('manifest root must be an object or list')
    if not isinstance(jobs_payload, list):
        raise ValueError('manifest jobs must be a list')
    return [SeedJobRequest.from_mapping(dict(job)) for job in jobs_payload]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == '':
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == '':
        return None
    return float(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False
    raise ValueError(f'invalid boolean manifest value: {value}')
