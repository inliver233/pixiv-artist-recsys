from __future__ import annotations

import unittest

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.rank import (
    build_multi_round_consensus,
    campaign_seed_plan,
    extract_round_items,
)
from pixiv_artist_recsys.utils.sampling import hash_sample_ids, sample_ids


class ConsensusTests(unittest.TestCase):
    def test_multi_round_consensus_prefers_overlap(self) -> None:
        rounds = [
            [
                {'artist_user_id': 1, 'score': 0.5, 'confidence': 0.6, 'name': 'a'},
                {'artist_user_id': 2, 'score': 0.9, 'confidence': 0.7, 'name': 'b'},
            ],
            [
                {'artist_user_id': 1, 'score': 0.55, 'confidence': 0.65, 'name': 'a'},
                {'artist_user_id': 3, 'score': 0.8, 'confidence': 0.5, 'name': 'c'},
            ],
            [
                {'artist_user_id': 1, 'score': 0.52, 'confidence': 0.7, 'name': 'a'},
                {'artist_user_id': 2, 'score': 0.4, 'confidence': 0.4, 'name': 'b'},
            ],
        ]
        consensus = build_multi_round_consensus(rounds, min_hits=2, max_results=10)
        ids = [row.artist_user_id for row in consensus]
        self.assertEqual(ids[0], 1)
        self.assertIn(2, ids)
        self.assertNotIn(3, ids)
        self.assertEqual(consensus[0].hit_count, 3)
        self.assertGreater(consensus[0].consensus_score, 0)

    def test_extract_round_items_and_seed_plan(self) -> None:
        payload = {
            'items': [
                {
                    'artist_user_id': 9,
                    'score': 0.4,
                    'confidence': 0.5,
                    'name': 'x',
                    'reasons': ['ok'],
                    'top_illust_ids': [1],
                }
            ]
        }
        items = extract_round_items(payload)
        self.assertEqual(items[0]['artist_user_id'], 9)
        plan = campaign_seed_plan(rounds=4)
        self.assertEqual(len(plan), 4)
        self.assertEqual(plan[0]['sample_salt'], 1)
        modes = {row['seed_sample'] for row in plan}
        self.assertIn('quality_first', modes)
        self.assertTrue({'random', 'hash'} & modes)

    def test_sample_salt_rotates_hash_subset(self) -> None:
        pool = list(range(1, 201))
        a = hash_sample_ids(pool, seed_user_id=7, limit=20, sample_salt=1)
        b = hash_sample_ids(pool, seed_user_id=7, limit=20, sample_salt=2)
        c = hash_sample_ids(pool, seed_user_id=7, limit=20, sample_salt=1)
        self.assertEqual(a, c)
        self.assertNotEqual(a, b)
        via = sample_ids(pool, limit=20, mode='hash', seed_user_id=7, sample_salt=3)
        self.assertEqual(len(via), 20)


if __name__ == '__main__':
    unittest.main()
