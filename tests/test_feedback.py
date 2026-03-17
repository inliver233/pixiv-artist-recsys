from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, Illust, SeedUser
from pixiv_artist_recsys.feedback import FeedbackService
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class FeedbackServiceTests(unittest.TestCase):
    def test_record_feedback_builds_negative_profile_from_dislike_and_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'feedback.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))

            repo.upsert_artist(Artist(user_id=2001, name='artist-a'))
            repo.upsert_illust(Illust(illust_id=9001, user_id=2001, title='a'))
            repo.replace_illust_tags(illust_id=9001, tags=['Blue Hair', '制服'])

            repo.upsert_artist(Artist(user_id=2002, name='artist-b'))
            repo.upsert_illust(Illust(illust_id=9002, user_id=2002, title='b'))
            repo.replace_illust_tags(illust_id=9002, tags=['blue hair', 'gore'])

            service = FeedbackService(repository=repo)
            service.record_feedback(seed_user_id=7, artist_user_id=2001, action='dislike', source_run_id='run-1', note='not my type')
            summary = service.record_feedback(seed_user_id=7, artist_user_id=2002, action='block', source_run_id='run-2', note='never show again')

            self.assertEqual(summary.event_count, 2)
            self.assertEqual(summary.disliked_artist_ids, [2001])
            self.assertEqual(summary.blocked_artist_ids, [2002])
            self.assertEqual(summary.negative_tags[0][0], 'blue_hair')
            self.assertEqual(repo.fetch_user_negative_profile(seed_user_id=7)[0][0], 'blue_hair')
            self.assertEqual(repo.list_feedback_artist_ids(seed_user_id=7, actions=('dislike', 'block')), [2001, 2002])

    def test_record_feedback_rejects_unknown_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'feedback-invalid.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            service = FeedbackService(repository=repo)

            with self.assertRaises(ValueError):
                service.record_feedback(seed_user_id=7, artist_user_id=2001, action='meh')


if __name__ == '__main__':
    unittest.main()
