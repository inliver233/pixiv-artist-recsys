from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.domain.models import Artist, Illust, RecommendationItem, RecommendationRun, SeedUser
from pixiv_artist_recsys.report import HtmlReportBuilder
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class HtmlReportTests(unittest.TestCase):
    def _build_run(self, repo: RecommendationRepository) -> str:
        repo.upsert_seed_user(SeedUser(user_id=7, refresh_token_ref='masked:token'))
        artist = Artist(user_id=2001, name='画師A', profile_image_url='https://i.pximg.net/user-profile/a.jpg')
        repo.upsert_artist(artist)
        for i in (1, 2, 3):
            repo.upsert_illust(
                Illust(
                    illust_id=9000 + i,
                    user_id=2001,
                    title=f'作品<{i}>',
                    total_bookmarks=100 * i,
                    image_url=f'https://i.pximg.net/img-master/900{i}_square1200.jpg',
                )
            )
        run = RecommendationRun(
            seed_user_id=7,
            run_id='run-html-1',
            mode='live-heuristic',
            items=[
                RecommendationItem(
                    artist=artist,
                    score=0.678,
                    confidence=0.9,
                    reasons=['taste:score=0.5', 'cofollow:count=2,score=0.8'],
                    top_illust_ids=[9003, 9002, 9001],
                )
            ],
        )
        repo.record_run(run)
        return run.run_id

    def test_report_contains_cards_links_and_feedback_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'report.sqlite3'))
            repo.initialize()
            run_id = self._build_run(repo)

            builder = HtmlReportBuilder(repository=repo, api_base='http://127.0.0.1:8787')
            content = builder.build_for_run(run_id=run_id)

            self.assertIn('https://www.pixiv.net/users/2001', content)
            self.assertIn('https://www.pixiv.net/artworks/9003', content)
            # Thumbnails rewritten to the referer-free mirror; original kept in data-src.
            self.assertIn('i.pixiv.re/img-master/9003_square1200.jpg', content)
            self.assertIn('data-src="https://i.pximg.net/img-master/9003_square1200.jpg"', content)
            self.assertIn("feedback(this, 2001, 'dislike')", content)
            self.assertIn("feedback(this, 2001, 'block')", content)
            self.assertIn('http://127.0.0.1:8787', content)
            # HTML-escaped title (作品<1> must not inject raw <).
            self.assertIn('作品&lt;3&gt;', content)
            self.assertIn('0.678', content)

    def test_write_for_run_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'report-io.sqlite3'))
            repo.initialize()
            run_id = self._build_run(repo)
            out = Path(tmpdir) / 'out' / 'report.html'
            result = HtmlReportBuilder(repository=repo).write_for_run(run_id=run_id, output_path=out)
            self.assertTrue(out.exists())
            self.assertEqual(result['run_id'], run_id)
            self.assertGreater(result['bytes'], 500)

    def test_missing_run_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'report-missing.sqlite3'))
            repo.initialize()
            with self.assertRaises(ValueError):
                HtmlReportBuilder(repository=repo).build_for_run(run_id='no-such-run')


if __name__ == '__main__':
    unittest.main()
