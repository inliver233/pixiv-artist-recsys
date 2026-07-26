from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.candidate import cofollow_jaccard, graph_recall, personalized_pagerank
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class PersonalizedPageRankTests(unittest.TestCase):
    def test_multi_seed_neighbor_outranks_single_seed_neighbor(self) -> None:
        # Seeds 1 and 2 both follow 100; only seed 1 follows 200.
        edges = [(1, 100), (2, 100), (1, 200), (3, 300)]
        scores = personalized_pagerank(
            edges,
            seed_weights={1: 1.0, 2: 1.0},
            min_seed_hits=1,
        )
        self.assertGreater(scores.get(100, 0.0), scores.get(200, 0.0))

    def test_multi_hit_filter_drops_single_seed_reach(self) -> None:
        edges = [(1, 100), (2, 100), (1, 200)]
        scores = personalized_pagerank(
            edges,
            seed_weights={1: 1.0, 2: 1.0},
            min_seed_hits=2,
        )
        self.assertIn(100, scores)
        self.assertNotIn(200, scores)

    def test_empty_inputs_return_empty(self) -> None:
        self.assertEqual(personalized_pagerank([], seed_weights={1: 1.0}), {})
        self.assertEqual(personalized_pagerank([(1, 2)], seed_weights={}), {})


class CofollowJaccardTests(unittest.TestCase):
    def test_candidate_sharing_followers_with_followed_scores(self) -> None:
        # Followed artist 10 has followers {1,2,3}; candidate 500 shares {1,2}.
        edges = [(1, 10), (2, 10), (3, 10), (1, 500), (2, 500)]
        scores = cofollow_jaccard(edges, followed_ids={10}, min_shared=2)
        self.assertIn(500, scores)
        # Jaccard = |{1,2}| / |{1,2,3}| = 2/3
        self.assertAlmostEqual(scores[500], 2 / 3, places=4)

    def test_single_shared_follower_filtered(self) -> None:
        edges = [(1, 10), (2, 10), (1, 500)]
        scores = cofollow_jaccard(edges, followed_ids={10}, min_shared=2)
        self.assertNotIn(500, scores)

    def test_followed_artists_never_scored_as_candidates(self) -> None:
        edges = [(1, 10), (2, 10), (1, 20), (2, 20)]
        scores = cofollow_jaccard(edges, followed_ids={10, 20}, min_shared=2)
        self.assertEqual(scores, {})


class GraphRecallTests(unittest.TestCase):
    def test_graph_recall_combines_ppr_and_jaccard(self) -> None:
        # Followed 10, 20 both follow candidate 500; candidate 600 followed only by 10.
        edges = [(10, 500), (20, 500), (10, 600), (10, 20)]
        result = graph_recall(
            edges,
            followed_ids={10, 20},
            seed_quality={10: 1000.0, 20: 500.0},
        )
        self.assertGreater(result.node_count, 0)
        self.assertIn(500, result.ppr_scores)
        # 600 reached from one seed only → multi-hit filtered.
        self.assertNotIn(600, result.ppr_scores)
        # PPR scores normalized to peak 1.0.
        self.assertAlmostEqual(max(result.ppr_scores.values()), 1.0, places=6)

    def test_graph_recall_without_seeds_in_graph_is_empty(self) -> None:
        result = graph_recall([(1, 2)], followed_ids={99})
        self.assertEqual(result.ppr_scores, {})
        self.assertEqual(result.jaccard_scores, {})


class FollowEdgeStorageTests(unittest.TestCase):
    def test_record_and_fetch_follow_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'edges.sqlite3'))
            repo.initialize()
            repo.record_follow_edges(
                edges=[(1, 2), (1, 2), (2, 3), (5, 5), (0, 9)],  # dup / self-loop / zero dropped
                now_epoch=1000.0,
            )
            edges = sorted(repo.fetch_follow_edges())
            self.assertEqual(edges, [(1, 2), (2, 3)])

    def test_legacy_evidence_edges_parsed_from_source_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RecommendationRepository(SQLiteDatabase(Path(tmpdir) / 'legacy-edges.sqlite3'))
            repo.initialize()
            repo.replace_artist_candidates(
                seed_user_id=7,
                candidates=[
                    (500, 'seed_artist_following', 'following-of:10', 0.55, 'x'),
                    (500, 'seed_artist_following', 'following-of:20', 0.55, 'x'),
                    (600, 'user_related', 'user:10', 1.0, 'not-an-edge'),
                ],
            )
            edges = sorted(repo.fetch_seed_following_evidence_edges(seed_user_id=7))
            self.assertEqual(edges, [(10, 500), (20, 500)])


if __name__ == '__main__':
    unittest.main()
