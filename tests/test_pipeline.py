from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.pipeline import RecommendationPipeline, RecommendationRequest
from pixiv_artist_recsys.services import (
    DryRunCandidateRetriever,
    DryRunIngestService,
    DryRunProfileService,
    DryRunRankService,
)
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class PipelineTests(unittest.TestCase):
    def test_pipeline_runs_and_persists_dry_run_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / "pipeline.sqlite3"))
            repo.initialize()
            pipeline = RecommendationPipeline(
                repository=repo,
                ingest_service=DryRunIngestService(),
                profile_service=DryRunProfileService(),
                candidate_retriever=DryRunCandidateRetriever(),
                rank_service=DryRunRankService(),
            )

            run = pipeline.run(RecommendationRequest(seed_user_id=7, refresh_token_ref="masked:token", max_results=5))

            self.assertEqual(run.seed_user_id, 7)
            self.assertEqual(len(run.items), 1)
            self.assertEqual(run.items[0].artist.name, "dry-run-artist")
            self.assertEqual(repo.count_rows("recommendation_runs"), 1)
            self.assertEqual(repo.count_rows("recommendation_items"), 1)


if __name__ == "__main__":
    unittest.main()
