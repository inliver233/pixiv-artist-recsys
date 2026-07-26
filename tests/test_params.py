from __future__ import annotations

import unittest

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.application.params import FullRecommendParams
from pixiv_artist_recsys.config import RecommendationConfig
from pixiv_artist_recsys.jobs import SeedJobRequest


class FullRecommendParamsTests(unittest.TestCase):
    def test_empty_mapping_uses_config_defaults(self) -> None:
        cfg = RecommendationConfig()
        params = FullRecommendParams.from_mapping({}, defaults=cfg)
        self.assertEqual(params.max_seed_artists, cfg.max_seed_artists)
        self.assertEqual(params.max_illusts_for_related, cfg.max_illusts_for_related)
        self.assertEqual(params.seed_sample, cfg.seed_sample)
        # Optional gates stay None → resolved by the facade at execution time.
        self.assertIsNone(params.min_score)
        self.assertIsNone(params.max_results)
        self.assertFalse(params.skip_sync_if_fresh)
        self.assertFalse(params.light_round)

    def test_mapping_overrides_and_type_coercion(self) -> None:
        params = FullRecommendParams.from_mapping(
            {
                'max_seed_artists': '123',
                'min_score': '0.3',
                'allow_ai': 'yes',
                'require_tag_overlap': 'off',
                'seed_sample': 'random',
                'seed_following_sample': 'not-a-mode',
                'skip_sync_if_fresh': '1',
                'light_round': True,
                'stop_words': 'single-word',
                'sample_salt': 42,
            }
        )
        self.assertEqual(params.max_seed_artists, 123)
        self.assertEqual(params.min_score, 0.3)
        self.assertTrue(params.allow_ai)
        self.assertFalse(params.require_tag_overlap)
        self.assertEqual(params.seed_sample, 'random')
        # Invalid modes fall back to the default instead of propagating garbage.
        self.assertEqual(params.seed_following_sample, 'quality_first')
        self.assertTrue(params.skip_sync_if_fresh)
        self.assertTrue(params.light_round)
        self.assertEqual(params.stop_words, ('single-word',))
        self.assertEqual(params.sample_salt, 42)

    def test_to_kwargs_covers_every_field(self) -> None:
        params = FullRecommendParams.from_mapping({'max_results': 50})
        kwargs = params.to_kwargs()
        self.assertEqual(kwargs['max_results'], 50)
        self.assertIsInstance(kwargs['stop_words'], list)
        # Every dataclass field must surface — a new knob added to the class
        # is automatically passed through to the facade.
        from dataclasses import fields
        self.assertEqual(set(kwargs), {f.name for f in fields(FullRecommendParams)})

    def test_seed_job_request_shares_the_same_parsing(self) -> None:
        request = SeedJobRequest.from_mapping(
            {
                'seed_user_id': 7,
                'refresh_token': 'tok',
                'max_illusts_for_related': 6,
                'skip_sync_if_fresh': 'true',
                'min_relative_bookmark_ratio': '0.5',
            }
        )
        self.assertEqual(request.seed_user_id, 7)
        self.assertEqual(request.max_illusts_for_related, 6)
        self.assertTrue(request.skip_sync_if_fresh)
        self.assertEqual(request.min_relative_bookmark_ratio, 0.5)

    def test_seed_job_request_missing_seed_raises(self) -> None:
        with self.assertRaises(ValueError):
            SeedJobRequest.from_mapping({'refresh_token': 'tok'})


if __name__ == '__main__':
    unittest.main()
