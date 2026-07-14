from __future__ import annotations

import json
import unittest

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.auth import HttpResponse
from pixiv_artist_recsys.pixiv import PixivAppApiClient, StaticAccessTokenProvider


class FakePixivTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        url = str(kwargs['url'])
        if url.endswith('/v1/user/following'):
            return HttpResponse(200, {}, json.dumps({
                'user_previews': [
                    {'user': {'id': 101, 'name': 'artist-a', 'account': 'a', 'profile_image_urls': {'medium': 'https://img/a.jpg'}}},
                    {'user': {'id': 102, 'name': 'artist-b', 'account': 'b', 'profile_image_urls': {'medium': 'https://img/b.jpg'}}},
                ],
                'next_url': None,
            }))
        if url.endswith('/v1/user/detail'):
            return HttpResponse(200, {}, json.dumps({
                'user': {'id': 101, 'name': 'artist-a', 'account': 'a', 'profile_image_urls': {'medium': 'https://img/a.jpg'}},
                'profile': {'total_illusts': 12, 'total_manga': 3, 'total_illust_bookmarks_public': 99},
            }))
        if url.endswith('/v1/user/illusts'):
            return HttpResponse(200, {}, json.dumps({
                'illusts': [
                    {'id': 201, 'title': 'illust-1', 'create_date': '2026-03-01T00:00:00+00:00', 'total_bookmarks': 10, 'total_view': 100, 'total_comments': 1, 'user': {'id': 101}},
                ],
                'next_url': None,
            }))
        if url.endswith('/v1/illust/detail'):
            return HttpResponse(200, {}, json.dumps({
                'illust': {
                    'id': 201,
                    'title': 'illust-1',
                    'create_date': '2026-03-01T00:00:00+00:00',
                    'total_bookmarks': 10,
                    'total_view': 100,
                    'total_comments': 1,
                    'user': {'id': 101},
                    'tags': [{'name': 'tag-a'}, {'name': 'tag-b'}],
                    'meta_single_page': {'original_image_url': 'https://i.pximg.net/img-original/201.jpg'},
                    'page_count': 1,
                    'illust_ai_type': 0,
                    'x_restrict': 0,
                }
            }))
        if url.endswith('/v1/user/recommended'):
            return HttpResponse(200, {}, json.dumps({
                'user_previews': [
                    {'user': {'id': 301, 'name': 'rec-a', 'account': 'rec_a', 'profile_image_urls': {'medium': 'https://img/r.jpg'}}},
                ],
                'next_url': None,
            }))
        if url.endswith('/v1/search/illust'):
            return HttpResponse(200, {}, json.dumps({
                'illusts': [
                    {
                        'id': 401,
                        'title': 'search-hit',
                        'create_date': '2026-03-01T00:00:00+00:00',
                        'total_bookmarks': 50,
                        'total_view': 500,
                        'total_comments': 2,
                        'user': {'id': 501},
                    }
                ],
                'next_url': None,
            }))
        return HttpResponse(404, {}, '{}')


class PixivClientTests(unittest.TestCase):
    def test_client_calls_endpoints_and_parses_payloads(self) -> None:
        transport = FakePixivTransport()
        client = PixivAppApiClient(access_token_provider=StaticAccessTokenProvider('token-abc'), transport=transport)

        following = client.fetch_following_users(user_id=1)
        self.assertEqual(len(following.items), 2)
        self.assertEqual(following.items[0].name, 'artist-a')

        detail = client.fetch_user_detail(user_id=101)
        self.assertEqual(detail.total_illusts, 12)

        illusts = client.fetch_user_illusts(user_id=101)
        self.assertEqual(illusts.items[0].illust_id, 201)

        illust_detail = client.fetch_illust_detail(illust_id=201)
        self.assertEqual(illust_detail.tags, ['tag-a', 'tag-b'])
        self.assertTrue(illust_detail.original_image_url.endswith('201.jpg'))

        recommended = client.fetch_user_recommended()
        self.assertEqual(recommended.items[0].user_id, 301)

        searched = client.fetch_search_illust(word='blue hair')
        self.assertEqual(searched.items[0].user_id, 501)
        self.assertEqual(searched.items[0].illust_id, 401)

        auth_headers = [call['headers']['Authorization'] for call in transport.calls]
        self.assertTrue(all(header == 'Bearer token-abc' for header in auth_headers))
        search_call = next(call for call in transport.calls if str(call['url']).endswith('/v1/search/illust'))
        self.assertEqual(search_call['params']['word'], 'blue hair')
        self.assertEqual(search_call['params']['sort'], 'popular_desc')


if __name__ == '__main__':
    unittest.main()
