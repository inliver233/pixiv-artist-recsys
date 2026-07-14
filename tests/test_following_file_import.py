from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, SeedUser
from pixiv_artist_recsys.ingest import FollowingFileImportService
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class FollowingFileImportTests(unittest.TestCase):
    def test_import_merges_uid_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'import.sqlite3'))
            repo.initialize()
            repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
            repo.upsert_artist(Artist(user_id=1001, name='existing', is_followed=True))
            repo.upsert_following_edge(seed_user_id=7, artist_user_id=1001)

            path = Path(tmpdir) / 'following.txt'
            path.write_text('1001\n2002\n# comment\n3003\n2002\n', encoding='utf-8')

            result = FollowingFileImportService(repository=repo).import_file(seed_user_id=7, path=path)
            self.assertEqual(result.unique_ids, 3)
            self.assertEqual(result.edges_before, 1)
            self.assertEqual(result.edges_after, 3)
            self.assertEqual(result.edges_added, 2)
            self.assertEqual(sorted(repo.list_following_artist_ids(seed_user_id=7)), [1001, 2002, 3003])
            self.assertEqual(repo.fetch_artist(artist_user_id=1001).name, 'existing')


if __name__ == '__main__':
    unittest.main()
