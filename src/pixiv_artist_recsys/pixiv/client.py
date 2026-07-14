from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..auth.coordinator import PixivTokenCoordinator
from ..auth.transport import HttpTransport, UrllibHttpTransport
from .models import PagedResult, PixivIllustDetail, PixivIllustSummary, PixivUserDetail, PixivUserSummary

APP_API_BASE_URL = "https://app-api.pixiv.net"
USER_FOLLOWING_PATH = "/v1/user/following"
USER_DETAIL_PATH = "/v1/user/detail"
USER_ILLUSTS_PATH = "/v1/user/illusts"
ILLUST_DETAIL_PATH = "/v1/illust/detail"
USER_RELATED_PATH = "/v1/user/related"
ILLUST_RELATED_PATH = "/v2/illust/related"
USER_RECOMMENDED_PATH = "/v1/user/recommended"
SEARCH_ILLUST_PATH = "/v1/search/illust"


class PixivAppApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AccessTokenProvider(Protocol):
    def get_access_token(self) -> str: ...


@dataclass(slots=True)
class StaticAccessTokenProvider:
    access_token: str

    def get_access_token(self) -> str:
        return self.access_token


@dataclass(slots=True)
class CoordinatorBackedAccessTokenProvider:
    coordinator: PixivTokenCoordinator
    token_key: str
    refresh_token: str

    def get_access_token(self) -> str:
        return self.coordinator.get_access_token_record(token_key=self.token_key, refresh_token=self.refresh_token).access_token


class PixivAppApiClient:
    def __init__(
        self,
        *,
        access_token_provider: AccessTokenProvider,
        transport: HttpTransport | None = None,
        base_url: str = APP_API_BASE_URL,
        accept_language: str = 'en_US',
    ) -> None:
        self.access_token_provider = access_token_provider
        self.transport = transport or UrllibHttpTransport()
        self.base_url = base_url.rstrip('/')
        self.accept_language = accept_language


    def fetch_user_related(self, *, seed_user_id: int, offset: int | None = None) -> PagedResult[PixivUserSummary]:
        payload = self._get_json(USER_RELATED_PATH, params={'seed_user_id': seed_user_id, 'offset': offset})
        previews = payload.get('user_previews') if isinstance(payload, dict) else None
        items = [self._parse_user_preview(item) for item in previews or []]
        return PagedResult(items=items, next_url=payload.get('next_url') if isinstance(payload, dict) else None)

    def fetch_illust_related(self, *, illust_id: int) -> PagedResult[PixivIllustSummary]:
        payload = self._get_json(ILLUST_RELATED_PATH, params={'illust_id': illust_id})
        illusts = payload.get('illusts') if isinstance(payload, dict) else None
        items = [self._parse_illust_summary(item) for item in illusts or []]
        return PagedResult(items=items, next_url=payload.get('next_url') if isinstance(payload, dict) else None)

    def fetch_user_recommended(self, *, offset: int | None = None) -> PagedResult[PixivUserSummary]:
        payload = self._get_json(USER_RECOMMENDED_PATH, params={'offset': offset})
        previews = payload.get('user_previews') if isinstance(payload, dict) else None
        items = [self._parse_user_preview(item) for item in previews or []]
        return PagedResult(items=items, next_url=payload.get('next_url') if isinstance(payload, dict) else None)

    def fetch_search_illust(
        self,
        *,
        word: str,
        search_target: str = 'partial_match_for_tags',
        sort: str = 'popular_desc',
        offset: int | None = None,
    ) -> PagedResult[PixivIllustSummary]:
        word = (word or '').strip()
        if not word:
            raise ValueError('search word is required')
        payload = self._get_json(
            SEARCH_ILLUST_PATH,
            params={
                'word': word,
                'search_target': search_target,
                'sort': sort,
                'offset': offset,
            },
        )
        illusts = payload.get('illusts') if isinstance(payload, dict) else None
        items = [self._parse_illust_summary(item) for item in illusts or []]
        return PagedResult(items=items, next_url=payload.get('next_url') if isinstance(payload, dict) else None)

    def fetch_following_users(self, *, user_id: int, restrict: str = 'public', offset: int | None = None) -> PagedResult[PixivUserSummary]:
        payload = self._get_json(USER_FOLLOWING_PATH, params={'user_id': user_id, 'restrict': restrict, 'offset': offset})
        previews = payload.get('user_previews') if isinstance(payload, dict) else None
        items = [self._parse_user_preview(item) for item in previews or []]
        return PagedResult(items=items, next_url=payload.get('next_url') if isinstance(payload, dict) else None)

    def fetch_user_detail(self, *, user_id: int) -> PixivUserDetail:
        payload = self._get_json(USER_DETAIL_PATH, params={'user_id': user_id})
        user = self._parse_user(payload.get('user') if isinstance(payload, dict) else None)
        profile = payload.get('profile') if isinstance(payload, dict) and isinstance(payload.get('profile'), dict) else {}
        return PixivUserDetail(
            user=user,
            total_illusts=self._as_int(profile.get('total_illusts')),
            total_manga=self._as_int(profile.get('total_manga')),
            total_illust_bookmarks_public=self._as_int(profile.get('total_illust_bookmarks_public')),
        )

    def fetch_user_illusts(self, *, user_id: int, type_: str = 'illust', offset: int | None = None) -> PagedResult[PixivIllustSummary]:
        payload = self._get_json(USER_ILLUSTS_PATH, params={'user_id': user_id, 'type': type_, 'offset': offset})
        illusts = payload.get('illusts') if isinstance(payload, dict) else None
        items = [self._parse_illust_summary(item) for item in illusts or []]
        return PagedResult(items=items, next_url=payload.get('next_url') if isinstance(payload, dict) else None)

    def fetch_illust_detail(self, *, illust_id: int) -> PixivIllustDetail:
        payload = self._get_json(ILLUST_DETAIL_PATH, params={'illust_id': illust_id})
        illust_raw = payload.get('illust') if isinstance(payload, dict) else None
        if not isinstance(illust_raw, dict):
            raise PixivAppApiError('Missing illust payload')
        summary = self._parse_illust_summary(illust_raw)
        tags = []
        for tag in illust_raw.get('tags') or []:
            if isinstance(tag, dict) and isinstance(tag.get('name'), str):
                tags.append(tag['name'])
        original_image_url = ''
        meta_single_page = illust_raw.get('meta_single_page')
        if isinstance(meta_single_page, dict) and isinstance(meta_single_page.get('original_image_url'), str):
            original_image_url = meta_single_page['original_image_url']
        return PixivIllustDetail(
            illust=summary,
            tags=tags,
            original_image_url=original_image_url,
            page_count=self._as_int(illust_raw.get('page_count'), fallback=1),
            ai_type=self._as_int(illust_raw.get('illust_ai_type')),
            x_restrict=self._as_int(illust_raw.get('x_restrict')),
        )

    def _get_json(self, path: str, *, params: Mapping[str, object] | None = None) -> Mapping[str, Any]:
        headers = {
            'Authorization': f"Bearer {self.access_token_provider.get_access_token()}",
            'Accept-Language': self.accept_language,
        }
        response = self.transport.send(method='GET', url=self.base_url + path, headers=headers, params=params)
        if response.status_code != 200:
            body_preview = (response.text or '')[:240].replace('\n', ' ')
            raise PixivAppApiError(
                f'Pixiv App API request failed path={path} status={response.status_code}: {body_preview}',
                status_code=response.status_code,
            )
        try:
            data = response.json()
        except Exception as exc:
            raise PixivAppApiError('Pixiv response is not JSON', status_code=response.status_code) from exc
        if not isinstance(data, dict):
            raise PixivAppApiError('Unexpected Pixiv response shape', status_code=response.status_code)
        return data

    @staticmethod
    def _parse_user_preview(raw: Any) -> PixivUserSummary:
        if isinstance(raw, dict) and isinstance(raw.get('user'), dict):
            return PixivAppApiClient._parse_user(raw['user'])
        return PixivUserSummary(user_id=0, name='unknown')

    @staticmethod
    def _parse_user(raw: Any) -> PixivUserSummary:
        if not isinstance(raw, dict):
            return PixivUserSummary(user_id=0, name='unknown')
        image_urls = raw.get('profile_image_urls') if isinstance(raw.get('profile_image_urls'), dict) else {}
        return PixivUserSummary(
            user_id=PixivAppApiClient._as_int(raw.get('id')),
            name=str(raw.get('name') or ''),
            account=str(raw.get('account') or ''),
            profile_image_url=str(image_urls.get('medium') or image_urls.get('px_50x50') or ''),
        )

    @staticmethod
    def _parse_illust_summary(raw: Any) -> PixivIllustSummary:
        if not isinstance(raw, dict):
            return PixivIllustSummary(illust_id=0, user_id=0, title='')
        user = raw.get('user') if isinstance(raw.get('user'), dict) else {}
        return PixivIllustSummary(
            illust_id=PixivAppApiClient._as_int(raw.get('id')),
            user_id=PixivAppApiClient._as_int(user.get('id')),
            title=str(raw.get('title') or ''),
            create_date=str(raw.get('create_date') or ''),
            total_bookmarks=PixivAppApiClient._as_int(raw.get('total_bookmarks')),
            total_view=PixivAppApiClient._as_int(raw.get('total_view')),
            total_comments=PixivAppApiClient._as_int(raw.get('total_comments')),
        )

    @staticmethod
    def _as_int(value: Any, fallback: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return fallback
