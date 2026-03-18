from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import PixivAppApiClient
from .models import PagedResult, PixivIllustDetail, PixivIllustSummary, PixivUserDetail, PixivUserSummary


@dataclass(slots=True)
class PixivInspectorService:
    pixiv_client: PixivAppApiClient

    def following_payload(self, *, user_id: int, restrict: str = 'public', offset: int | None = None) -> dict[str, Any]:
        result = self.pixiv_client.fetch_following_users(user_id=user_id, restrict=restrict, offset=offset)
        return {
            'user_id': user_id,
            'restrict': restrict,
            'offset': offset,
            'count': len(result.items),
            'next_url': result.next_url,
            'items': [self._user_summary_payload(item) for item in result.items],
        }

    def user_detail_payload(self, *, user_id: int) -> dict[str, Any]:
        detail = self.pixiv_client.fetch_user_detail(user_id=user_id)
        return {
            'user': self._user_summary_payload(detail.user),
            'profile': {
                'total_illusts': detail.total_illusts,
                'total_manga': detail.total_manga,
                'total_illust_bookmarks_public': detail.total_illust_bookmarks_public,
            },
        }

    def user_illusts_payload(self, *, user_id: int, type_: str = 'illust', offset: int | None = None) -> dict[str, Any]:
        result = self.pixiv_client.fetch_user_illusts(user_id=user_id, type_=type_, offset=offset)
        return {
            'user_id': user_id,
            'type': type_,
            'offset': offset,
            'count': len(result.items),
            'next_url': result.next_url,
            'items': [self._illust_summary_payload(item) for item in result.items],
        }

    def illust_detail_payload(self, *, illust_id: int) -> dict[str, Any]:
        detail = self.pixiv_client.fetch_illust_detail(illust_id=illust_id)
        return self._illust_detail_payload(detail)

    def user_related_payload(self, *, seed_user_id: int, offset: int | None = None) -> dict[str, Any]:
        result = self.pixiv_client.fetch_user_related(seed_user_id=seed_user_id, offset=offset)
        return {
            'seed_user_id': seed_user_id,
            'offset': offset,
            'count': len(result.items),
            'next_url': result.next_url,
            'items': [self._user_summary_payload(item) for item in result.items],
        }

    def illust_related_payload(self, *, illust_id: int) -> dict[str, Any]:
        result = self.pixiv_client.fetch_illust_related(illust_id=illust_id)
        return {
            'illust_id': illust_id,
            'count': len(result.items),
            'next_url': result.next_url,
            'items': [self._illust_summary_payload(item) for item in result.items],
        }

    @staticmethod
    def _user_summary_payload(item: PixivUserSummary) -> dict[str, Any]:
        return {
            'user_id': item.user_id,
            'name': item.name,
            'account': item.account,
            'profile_image_url': item.profile_image_url,
        }

    @staticmethod
    def _illust_summary_payload(item: PixivIllustSummary) -> dict[str, Any]:
        return {
            'illust_id': item.illust_id,
            'user_id': item.user_id,
            'title': item.title,
            'create_date': item.create_date,
            'total_bookmarks': item.total_bookmarks,
            'total_view': item.total_view,
            'total_comments': item.total_comments,
        }

    @classmethod
    def _illust_detail_payload(cls, detail: PixivIllustDetail) -> dict[str, Any]:
        return {
            'illust': cls._illust_summary_payload(detail.illust),
            'tags': list(detail.tags),
            'original_image_url': detail.original_image_url,
            'page_count': detail.page_count,
            'ai_type': detail.ai_type,
            'x_restrict': detail.x_restrict,
        }
