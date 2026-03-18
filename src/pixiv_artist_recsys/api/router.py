from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from ..application import ApplicationFacade
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
    def __init__(self, *, runtime: AppRuntime, application: ApplicationFacade | None = None) -> None:
        self.runtime = runtime
        self.application = application or ApplicationFacade(runtime=runtime)

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
            return ApiResponse(status_code=200, payload=self.application.show_config_payload())
        if path == '/proxy-state':
            return ApiResponse(status_code=200, payload=self.application.show_proxy_state_payload())
        if path == '/runs':
            limit = self._query_int(request, 'limit', default=20)
            return ApiResponse(status_code=200, payload=self.application.list_runs_payload(limit=limit))
        if len(segments) == 2 and segments[0] == 'runs':
            return ApiResponse(status_code=200, payload=self.application.export_run_payload(run_id=segments[1]))
        if len(segments) == 3 and segments[0] == 'runs' and segments[2] == 'audit':
            return ApiResponse(status_code=200, payload=self.application.run_audit_payload(run_id=segments[1]))
        if path == '/feedback/profile':
            seed_user_id = self._query_int(request, 'seed_user_id')
            top_n_tags = self._query_int(request, 'top_n_tags', default=20)
            return ApiResponse(
                status_code=200,
                payload=self.application.feedback_profile_payload(
                    seed_user_id=seed_user_id,
                    top_n_tags=top_n_tags,
                ),
            )
        if path == '/recommend/from-store':
            seed_user_id = self._query_int(request, 'seed_user_id')
            max_results = self._query_int(request, 'max_results', default=self.runtime.settings.recommendation.max_results)
            diversity_per_tag = self._query_int(
                request,
                'diversity_per_tag',
                default=self.runtime.settings.recommendation.diversity_per_tag,
            )
            return ApiResponse(
                status_code=200,
                payload=self.application.recommend_from_store_payload(
                    seed_user_id=seed_user_id,
                    max_results=max_results,
                    diversity_per_tag=diversity_per_tag,
                    allow_ai=self._query_bool(request, 'allow_ai', default=None),
                    allow_r18=self._query_bool(request, 'allow_r18', default=None),
                    min_bookmarks=self._query_int(
                        request,
                        'min_bookmarks',
                        default=self.runtime.settings.recommendation.min_bookmarks,
                    ),
                    min_score=self._query_float(request, 'min_score', default=self.runtime.settings.recommendation.min_score),
                ),
            )
        return ApiResponse(status_code=404, payload={'error': 'not_found', 'path': path})

    def _handle_post(self, path: str, request: ApiRequest) -> ApiResponse:
        body = self._json_body(request)
        if path == '/feedback':
            return ApiResponse(
                status_code=200,
                payload=self.application.record_feedback_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    artist_user_id=self._required_body_int(body, 'artist_user_id'),
                    action=self._required_body_text(body, 'action'),
                    source_run_id=self._optional_body_text(body, 'source_run_id', default='') or '',
                    note=self._optional_body_text(body, 'note', default='') or '',
                    top_n_tags=self._optional_body_int(body, 'top_n_tags', default=20) or 20,
                ),
            )
        if path == '/hydrate/followed-illusts':
            return ApiResponse(
                status_code=200,
                payload=self.application.hydrate_followed_illusts_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    token_key=self._optional_body_text(body, 'token_key', default=None),
                    refresh_token=self._optional_body_text(body, 'refresh_token', default=None),
                    access_token=self._optional_body_text(body, 'access_token', default=None),
                    per_artist_limit=self._optional_body_int(body, 'per_artist_limit', default=5) or 5,
                ),
            )
        if path == '/profile/build':
            return ApiResponse(
                status_code=200,
                payload=self.application.build_profile_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    top_n_tags=self._optional_body_int(body, 'top_n_tags', default=20) or 20,
                    top_n_pairs=self._optional_body_int(body, 'top_n_pairs', default=20) or 20,
                    stop_words=self._optional_body_list(body, 'stop_words'),
                ),
            )
        if path == '/recommend/full':
            recommendation = self.runtime.settings.recommendation
            return ApiResponse(
                status_code=200,
                payload=self.application.full_recommend_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    token_key=self._optional_body_text(body, 'token_key', default=None),
                    refresh_token=self._optional_body_text(body, 'refresh_token', default=None),
                    access_token=self._optional_body_text(body, 'access_token', default=None),
                    restrict=self._optional_body_text(body, 'restrict', default='public') or 'public',
                    followed_artist_limit=self._optional_body_int(body, 'followed_artist_limit', default=5) or 5,
                    candidate_artist_limit=self._optional_body_int(body, 'candidate_artist_limit', default=3) or 3,
                    max_related_per_artist=self._optional_body_int(body, 'max_related_per_artist', default=5) or 5,
                    max_related_per_illust=self._optional_body_int(body, 'max_related_per_illust', default=5) or 5,
                    top_n_tags=self._optional_body_int(body, 'top_n_tags', default=20) or 20,
                    top_n_pairs=self._optional_body_int(body, 'top_n_pairs', default=20) or 20,
                    max_results=self._optional_body_int(body, 'max_results', default=recommendation.max_results),
                    allow_ai=self._optional_body_bool(body, 'allow_ai', default=recommendation.allow_ai),
                    allow_r18=self._optional_body_bool(body, 'allow_r18', default=recommendation.allow_r18),
                    min_bookmarks=self._optional_body_int(body, 'min_bookmarks', default=recommendation.min_bookmarks),
                    min_score=self._optional_body_float(body, 'min_score', default=recommendation.min_score),
                    diversity_per_tag=self._optional_body_int(body, 'diversity_per_tag', default=recommendation.diversity_per_tag),
                    stop_words=self._optional_body_list(body, 'stop_words'),
                ),
            )
        if path == '/pixiv/following':
            return ApiResponse(
                status_code=200,
                payload=self.application.pixiv_following_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    token_key=self._optional_body_text(body, 'token_key', default=None),
                    refresh_token=self._optional_body_text(body, 'refresh_token', default=None),
                    access_token=self._optional_body_text(body, 'access_token', default=None),
                    restrict=self._optional_body_text(body, 'restrict', default='public') or 'public',
                    offset=self._optional_body_int(body, 'offset', default=None),
                ),
            )
        if path == '/pixiv/user-detail':
            return ApiResponse(
                status_code=200,
                payload=self.application.pixiv_user_detail_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    target_user_id=self._required_body_int(body, 'target_user_id'),
                    token_key=self._optional_body_text(body, 'token_key', default=None),
                    refresh_token=self._optional_body_text(body, 'refresh_token', default=None),
                    access_token=self._optional_body_text(body, 'access_token', default=None),
                ),
            )
        if path == '/pixiv/user-illusts':
            return ApiResponse(
                status_code=200,
                payload=self.application.pixiv_user_illusts_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    target_user_id=self._required_body_int(body, 'target_user_id'),
                    token_key=self._optional_body_text(body, 'token_key', default=None),
                    refresh_token=self._optional_body_text(body, 'refresh_token', default=None),
                    access_token=self._optional_body_text(body, 'access_token', default=None),
                    type_=self._optional_body_text(body, 'type', default='illust') or 'illust',
                    offset=self._optional_body_int(body, 'offset', default=None),
                ),
            )
        if path == '/pixiv/illust-detail':
            return ApiResponse(
                status_code=200,
                payload=self.application.pixiv_illust_detail_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    illust_id=self._required_body_int(body, 'illust_id'),
                    token_key=self._optional_body_text(body, 'token_key', default=None),
                    refresh_token=self._optional_body_text(body, 'refresh_token', default=None),
                    access_token=self._optional_body_text(body, 'access_token', default=None),
                ),
            )
        if path == '/pixiv/user-related':
            return ApiResponse(
                status_code=200,
                payload=self.application.pixiv_user_related_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    target_user_id=self._required_body_int(body, 'target_user_id'),
                    token_key=self._optional_body_text(body, 'token_key', default=None),
                    refresh_token=self._optional_body_text(body, 'refresh_token', default=None),
                    access_token=self._optional_body_text(body, 'access_token', default=None),
                    offset=self._optional_body_int(body, 'offset', default=None),
                ),
            )
        if path == '/pixiv/illust-related':
            return ApiResponse(
                status_code=200,
                payload=self.application.pixiv_illust_related_payload(
                    seed_user_id=self._required_body_int(body, 'seed_user_id'),
                    illust_id=self._required_body_int(body, 'illust_id'),
                    token_key=self._optional_body_text(body, 'token_key', default=None),
                    refresh_token=self._optional_body_text(body, 'refresh_token', default=None),
                    access_token=self._optional_body_text(body, 'access_token', default=None),
                ),
            )
        return ApiResponse(status_code=404, payload={'error': 'not_found', 'path': path})

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

    @staticmethod
    def _required_body_int(body: dict[str, Any], key: str) -> int:
        if key not in body:
            raise ValueError(f'missing required body field: {key}')
        value = ApiRouter._optional_body_int(body, key, default=None)
        if value is None:
            raise ValueError(f'missing required body field: {key}')
        return value

    @staticmethod
    def _optional_body_int(body: dict[str, Any], key: str, default: int | None) -> int | None:
        value = body.get(key)
        if value is None or value == '':
            return default
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'invalid integer body field for {key}: {value}') from exc

    @staticmethod
    def _optional_body_float(body: dict[str, Any], key: str, default: float) -> float:
        value = body.get(key)
        if value is None or value == '':
            return default
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'invalid float body field for {key}: {value}') from exc

    @staticmethod
    def _required_body_text(body: dict[str, Any], key: str) -> str:
        value = ApiRouter._optional_body_text(body, key, default=None)
        if value is None:
            raise ValueError(f'missing required body field: {key}')
        return value

    @staticmethod
    def _optional_body_text(body: dict[str, Any], key: str, default: str | None) -> str | None:
        value = body.get(key)
        if value is None:
            return default
        text = str(value).strip()
        return text or default

    @staticmethod
    def _optional_body_bool(body: dict[str, Any], key: str, default: bool) -> bool:
        value = body.get(key)
        if value is None or value == '':
            return default
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
        raise ValueError(f'invalid boolean body field for {key}: {value}')

    @staticmethod
    def _optional_body_list(body: dict[str, Any], key: str) -> list[str]:
        value = body.get(key)
        if value is None or value == '':
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)]
