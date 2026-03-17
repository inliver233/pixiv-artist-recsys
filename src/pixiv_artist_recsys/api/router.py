from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from ..feedback import FeedbackService
from ..rank import HeuristicArtistRankService
from ..runtime import AppRuntime


@dataclass(slots=True)
class ApiRequest:
    method: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    body: bytes = b''
    headers: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_target(
        cls,
        *,
        method: str,
        target: str,
        body: bytes = b'',
        headers: Mapping[str, str] | None = None,
    ) -> 'ApiRequest':
        parsed = urlsplit(target)
        return cls(
            method=str(method or 'GET').upper(),
            path=parsed.path or '/',
            query={key: list(values) for key, values in parse_qs(parsed.query, keep_blank_values=True).items()},
            body=body,
            headers=headers or {},
        )


@dataclass(slots=True)
class ApiResponse:
    status_code: int
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class ApiRouter:
    def __init__(self, *, runtime: AppRuntime) -> None:
        self.runtime = runtime

    def handle(self, request: ApiRequest) -> ApiResponse:
        normalized_path = self._normalize_path(request.path)
        try:
            if request.method == 'GET':
                return self._handle_get(normalized_path, request)
            if request.method == 'POST':
                return self._handle_post(normalized_path, request)
            return ApiResponse(status_code=405, payload={'error': 'method_not_allowed', 'method': request.method})
        except ValueError as exc:
            return ApiResponse(status_code=400, payload={'error': 'bad_request', 'message': str(exc)})

    def _handle_get(self, path: str, request: ApiRequest) -> ApiResponse:
        segments = self._segments(path)
        if path == '/health':
            return ApiResponse(
                status_code=200,
                payload={
                    'status': 'ok',
                    'mode': self.runtime.settings.mode.value,
                    'db_path': str(self.runtime.db_path),
                },
            )
        if path == '/config':
            return ApiResponse(status_code=200, payload=self.runtime.settings_payload())
        if path == '/proxy-state':
            return ApiResponse(status_code=200, payload=self.runtime.proxy_state_payload())
        if path == '/runs':
            limit = self._query_int(request, 'limit', default=20)
            runs = self.runtime.repository.list_recommendation_runs(limit=limit)
            return ApiResponse(
                status_code=200,
                payload={
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
                },
            )
        if len(segments) == 2 and segments[0] == 'runs':
            return ApiResponse(status_code=200, payload=self._run_payload(run_id=segments[1]))
        if len(segments) == 3 and segments[0] == 'runs' and segments[2] == 'audit':
            return ApiResponse(
                status_code=200,
                payload={
                    'run_id': segments[1],
                    'audit': self.runtime.repository.fetch_run_audit(run_id=segments[1]),
                },
            )
        if path == '/feedback/profile':
            seed_user_id = self._query_int(request, 'seed_user_id')
            top_n_tags = self._query_int(request, 'top_n_tags', default=20)
            summary = FeedbackService(repository=self.runtime.repository).build_negative_profile(
                seed_user_id=seed_user_id,
                top_n_tags=top_n_tags,
            )
            return ApiResponse(status_code=200, payload=self._negative_profile_payload(summary))
        if path == '/recommend/from-store':
            seed_user_id = self._query_int(request, 'seed_user_id')
            max_results = self._query_int(request, 'max_results', default=self.runtime.settings.recommendation.max_results)
            diversity_per_tag = self._query_int(
                request,
                'diversity_per_tag',
                default=self.runtime.settings.recommendation.diversity_per_tag,
            )
            result = HeuristicArtistRankService(repository=self.runtime.repository).rank_from_store(
                seed_user_id=seed_user_id,
                max_results=max_results,
                allow_ai=self._query_bool(request, 'allow_ai', default=None),
                allow_r18=self._query_bool(request, 'allow_r18', default=None),
                min_total_bookmarks=self._query_int(
                    request,
                    'min_bookmarks',
                    default=self.runtime.settings.recommendation.min_bookmarks,
                ),
                min_score=self._query_float(request, 'min_score', default=self.runtime.settings.recommendation.min_score),
                diversity_primary_tag_limit=diversity_per_tag,
            )
            return ApiResponse(
                status_code=200,
                payload={
                    'seed_user_id': result.seed_user_id,
                    'item_count': len(result.items),
                    'diversity_per_tag': diversity_per_tag,
                    'items': [
                        {
                            'artist_user_id': item.artist.user_id,
                            'artist_name': item.artist.name,
                            'artist_account': item.artist.account,
                            'score': item.score,
                            'confidence': item.confidence,
                            'reasons': item.reasons,
                            'top_illust_ids': item.top_illust_ids,
                        }
                        for item in result.items
                    ],
                },
            )
        return ApiResponse(status_code=404, payload={'error': 'not_found', 'path': path})

    def _handle_post(self, path: str, request: ApiRequest) -> ApiResponse:
        if path != '/feedback':
            return ApiResponse(status_code=404, payload={'error': 'not_found', 'path': path})
        body = self._json_body(request)
        summary = FeedbackService(repository=self.runtime.repository).record_feedback(
            seed_user_id=int(body['seed_user_id']),
            artist_user_id=int(body['artist_user_id']),
            action=str(body['action']),
            source_run_id=str(body.get('source_run_id', '')),
            note=str(body.get('note', '')),
            top_n_tags=int(body.get('top_n_tags', 20)),
        )
        payload = self._negative_profile_payload(summary)
        payload['artist_user_id'] = int(body['artist_user_id'])
        payload['action'] = str(body['action']).strip().lower()
        return ApiResponse(status_code=200, payload=payload)

    @staticmethod
    def _normalize_path(path: str) -> str:
        stripped = str(path or '/').strip() or '/'
        if stripped != '/' and stripped.endswith('/'):
            return stripped.rstrip('/')
        return stripped

    @staticmethod
    def _segments(path: str) -> list[str]:
        return [segment for segment in path.split('/') if segment]

    @staticmethod
    def _query_first(request: ApiRequest, key: str) -> str | None:
        values = request.query.get(key)
        if not values:
            return None
        candidate = str(values[0]).strip()
        return candidate or None

    def _query_int(self, request: ApiRequest, key: str, default: int | None = None) -> int:
        raw_value = self._query_first(request, key)
        if raw_value is None:
            if default is None:
                raise ValueError(f'missing required query parameter: {key}')
            return default
        try:
            return int(raw_value)
        except ValueError as exc:
            raise ValueError(f'invalid integer query parameter for {key}: {raw_value}') from exc

    def _query_float(self, request: ApiRequest, key: str, default: float) -> float:
        raw_value = self._query_first(request, key)
        if raw_value is None:
            return default
        try:
            return float(raw_value)
        except ValueError as exc:
            raise ValueError(f'invalid float query parameter for {key}: {raw_value}') from exc

    def _query_bool(self, request: ApiRequest, key: str, default: bool | None) -> bool | None:
        raw_value = self._query_first(request, key)
        if raw_value is None:
            return default
        normalized = raw_value.lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
        raise ValueError(f'invalid boolean query parameter for {key}: {raw_value}')

    @staticmethod
    def _json_body(request: ApiRequest) -> dict[str, Any]:
        raw = request.body.decode('utf-8').strip()
        if not raw:
            raise ValueError('request body is required')
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f'invalid json body: {exc.msg}') from exc
        if not isinstance(payload, dict):
            raise ValueError('json body must be an object')
        return payload

    def _run_payload(self, *, run_id: str) -> dict[str, Any]:
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
        return payload

    @staticmethod
    def _negative_profile_payload(summary) -> dict[str, Any]:
        return {
            'seed_user_id': summary.seed_user_id,
            'event_count': summary.event_count,
            'negative_tags': [{'tag': tag, 'weight': weight} for tag, weight in summary.negative_tags],
            'disliked_artist_ids': summary.disliked_artist_ids,
            'blocked_artist_ids': summary.blocked_artist_ids,
        }
