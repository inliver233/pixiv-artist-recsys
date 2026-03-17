from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, SeedUser
from pixiv_artist_recsys.profile import UserTasteProfileService
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class ProfileTests(unittest.TestCase):
    def test_build_profile_from_followed_artist_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'profile.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            for artist_id in [1001, 1002]:
                repo.upsert_artist(Artist(user_id=artist_id, name=f'artist-{artist_id}', is_followed=True))
                repo.upsert_following_edge(seed_user_id=7, artist_user_id=artist_id)
            # illusts + tags
            from pixiv_artist_recsys.domain.models import Illust
            repo.upsert_illust(Illust(illust_id=1, user_id=1001, title='a'))
            repo.replace_illust_tags(illust_id=1, tags=['Blue Hair', '制服'])
            repo.upsert_illust(Illust(illust_id=2, user_id=1002, title='b'))
            repo.replace_illust_tags(illust_id=2, tags=['blue hair', '夜景'])

            summary = UserTasteProfileService(repository=repo).build_profile(seed_user_id=7)

            self.assertEqual(summary.artist_count, 2)
            self.assertEqual(summary.top_tags[0][0], 'blue_hair')
            self.assertGreater(len(summary.top_pairs), 0)
            self.assertEqual(repo.fetch_user_taste_profile(seed_user_id=7)[0][0], 'blue_hair')


if __name__ == '__main__':
    unittest.main()
