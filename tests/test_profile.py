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


class ProfileDecayAndFeedbackTests(unittest.TestCase):
    def test_follow_feedback_artist_tags_join_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'profile-follow.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='followed', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)
            repo.upsert_illust(Illust(illust_id=1, user_id=1001, title='a'))
            repo.replace_illust_tags(illust_id=1, tags=['夜景'])
            # Artist followed via feedback but not yet in the following edges.
            repo.upsert_artist(Artist(user_id=2001, name='new-follow'))
            repo.upsert_illust(Illust(illust_id=2, user_id=2001, title='b'))
            repo.replace_illust_tags(illust_id=2, tags=['アークナイツ'])
            repo.record_feedback_event(seed_user_id=7, artist_user_id=2001, action='follow')

            summary = UserTasteProfileService(repository=repo).build_profile(seed_user_id=7)

            tags = [tag for tag, _ in summary.top_tags]
            self.assertIn('アークナイツ', tags)
            self.assertEqual(summary.artist_count, 2)

    def test_recent_follow_outweighs_ancient_follow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'profile-decay.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            for artist_id, tag, first_seen in (
                (1001, '夜景', '2020-01-01 00:00:00'),      # ~6.5 years old
                (1002, 'アークナイツ', '2026-07-01 00:00:00'),  # weeks old
            ):
                repo.upsert_artist(Artist(user_id=artist_id, name=f'a{artist_id}', is_followed=True))
                repo.upsert_following_edge(seed_user_id=7, artist_user_id=artist_id)
                with repo.database.connect() as conn:
                    conn.execute(
                        'UPDATE seed_user_following_artists SET first_seen_at = ? WHERE artist_user_id = ?',
                        (first_seen, artist_id),
                    )
                repo.upsert_illust(Illust(illust_id=artist_id, user_id=artist_id, title='x', total_bookmarks=100))
                repo.replace_illust_tags(illust_id=artist_id, tags=[tag])

            import datetime as _dt
            now = _dt.datetime(2026, 7, 26, tzinfo=_dt.timezone.utc).timestamp()
            summary = UserTasteProfileService(repository=repo, now_fn=lambda: now).build_profile(seed_user_id=7)
            weights = dict(summary.top_tags)
            self.assertGreater(weights['アークナイツ'], weights['夜景'])

    def test_higher_bookmark_artist_speaks_louder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'profile-quality.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            for artist_id, tag, bookmarks in ((1001, '夜景', 5000), (1002, 'アークナイツ', 50)):
                repo.upsert_artist(Artist(user_id=artist_id, name=f'a{artist_id}', is_followed=True))
                repo.upsert_following_edge(seed_user_id=7, artist_user_id=artist_id)
                repo.upsert_illust(Illust(illust_id=artist_id, user_id=artist_id, title='x', total_bookmarks=bookmarks))
                repo.replace_illust_tags(illust_id=artist_id, tags=[tag])

            summary = UserTasteProfileService(repository=repo).build_profile(seed_user_id=7)
            weights = dict(summary.top_tags)
            self.assertGreater(weights['夜景'], weights['アークナイツ'])


if __name__ == '__main__':
    unittest.main()
