from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, Illust, SeedUser
from pixiv_artist_recsys.profile import DEFAULT_STOP_WORDS, UserTasteProfileService
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
            repo.upsert_illust(Illust(illust_id=1, user_id=1001, title='a'))
            repo.replace_illust_tags(illust_id=1, tags=['Blue Hair', '制服'])
            repo.upsert_illust(Illust(illust_id=2, user_id=1002, title='b'))
            repo.replace_illust_tags(illust_id=2, tags=['blue hair', '夜景'])

            summary = UserTasteProfileService(repository=repo).build_profile(seed_user_id=7)

            self.assertEqual(summary.artist_count, 2)
            tags = [tag for tag, _ in summary.top_tags]
            # blue_hair appears on every followed artist → IDF dampens it vs rarer tags.
            self.assertIn('blue_hair', tags)
            self.assertTrue(any(tag in tags for tag in ('制服', '夜景')))
            self.assertGreater(len(summary.top_pairs), 0)
            stored = [tag for tag, _ in repo.fetch_user_taste_profile(seed_user_id=7)]
            self.assertIn('blue_hair', stored)

    def test_profile_strips_usersiri_and_stopwords_prefers_rare_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'profile-denoise.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            # Three artists all share generic 女の子; only one has distinctive tag.
            for artist_id in (1001, 1002, 1003):
                repo.upsert_artist(Artist(user_id=artist_id, name=f'a{artist_id}', is_followed=True))
                repo.upsert_following_edge(seed_user_id=7, artist_user_id=artist_id)
            repo.upsert_illust(Illust(illust_id=1, user_id=1001, title='a'))
            repo.replace_illust_tags(illust_id=1, tags=['女の子', 'オリジナル', '1000users入り', 'アークナイツ'])
            repo.upsert_illust(Illust(illust_id=2, user_id=1002, title='b'))
            repo.replace_illust_tags(illust_id=2, tags=['女の子', 'オリジナル', '500users入り'])
            repo.upsert_illust(Illust(illust_id=3, user_id=1003, title='c'))
            repo.replace_illust_tags(illust_id=3, tags=['女の子', '夜景'])

            summary = UserTasteProfileService(repository=repo).build_profile(seed_user_id=7)
            tags = [tag for tag, _ in summary.top_tags]

            self.assertIn('女の子', DEFAULT_STOP_WORDS)
            self.assertNotIn('女の子', tags)
            self.assertNotIn('オリジナル', tags)
            self.assertTrue(all('users入り' not in tag for tag in tags))
            # Rare distinctive tags should dominate after IDF.
            self.assertIn(tags[0], {'アークナイツ', '夜景'})


if __name__ == '__main__':
    unittest.main()
