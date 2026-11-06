"""Audit deployed models with actual artifacts and isolated integrity failures."""
import datetime as dt
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from jeju_agent.assistant_search import search_assistant
from jeju_agent.audience_v23 import predict_audience_v23
from jeju_agent.dining_model import MODEL_RELATIVE, SOURCE_RELATIVE, predict_dining
from jeju_agent.model_portfolio import digest
from jeju_agent.place_trust import place_trust
from jeju_agent.quality_v23 import operating_evaluation
from jeju_agent.server import operational_check


ROOT = Path(__file__).resolve().parents[1]


class ModelDataEdgeTests(unittest.TestCase):
    def test_all_24_audience_profiles_have_ranked_bounded_shares_and_same_evidence(self):
        report = {row['id']: row for row in operating_evaluation(ROOT)['models']}
        expected = report['audience_distribution']
        for audience in ('resident', 'tourist'):
            for month in range(1, 13):
                with self.subTest(audience=audience, month=month):
                    profile = predict_audience_v23(ROOT, audience, str(month))
                    categories = profile['categories']
                    shares = [row['share'] for row in categories]
                    self.assertEqual(profile['source_id'], '1048')
                    self.assertEqual(profile['month'], month)
                    self.assertEqual(len({row['name'] for row in categories}), 8)
                    self.assertEqual([row['rank'] for row in categories], list(range(1, 9)))
                    self.assertEqual(shares, sorted(shares, reverse=True))
                    self.assertTrue(all(math.isfinite(value) and 0 <= value <= 1 for value in shares))
                    self.assertAlmostEqual(sum(shares), 1, delta=0.000004)
                    metric = profile['metrics']['model']['within_tolerance']
                    for key in ('hits', 'total', 'percent'):
                        self.assertEqual(metric[key], expected['metric'][key])
                    self.assertEqual(metric['threshold_percentage_points'], expected['fixed_tolerance'])

    def test_audience_invalid_month_or_group_fails_before_prediction(self):
        for month in (0, 13, '01', '', None, True, 1.5, 'NaN', '1e0', '1' * 4096):
            with self.subTest(month=str(month)[:20]), self.assertRaises(ValueError):
                predict_audience_v23(ROOT, 'resident', month)
        for group in ('', 'all', '제주도민', 'Resident', None, [], True):
            with self.subTest(group=group), self.assertRaises(ValueError):
                predict_audience_v23(ROOT, group, 1)

    def test_all_12_dining_profiles_and_filter_denominator(self):
        report = {row['id']: row for row in operating_evaluation(ROOT)['models']}
        expected = report['dining_detail']
        for month in range(1, 13):
            with self.subTest(month=month):
                full = predict_dining(ROOT, month=month, limit=100)
                filtered = predict_dining(ROOT, month=month, category='커피전문점', limit=1)
                missing = predict_dining(ROOT, month=month, category='없는분류재현표식', limit=100)
                self.assertEqual(full['source']['dataset_id'], '1047')
                self.assertEqual(full['source']['missing_months_imputed'], 0)
                self.assertEqual(full['total_matches'], 94)
                self.assertEqual(full['returned_count'], 94)
                shares = [row['predicted_share_percent'] for row in full['items']]
                self.assertTrue(all(math.isfinite(value) and 0 <= value <= 100 for value in shares))
                self.assertAlmostEqual(sum(shares), 100, delta=0.00005)
                self.assertEqual(shares, sorted(shares, reverse=True))
                self.assertEqual(len(filtered['items']), 1)
                self.assertEqual(filtered['items'][0], next(row for row in full['items']
                                                            if row['category'] == '커피전문점'))
                self.assertEqual(missing['items'], [])
                self.assertEqual(missing['filtered_share_percent'], 0)
                metric = full['metrics']['within_tolerance']['0.25']
                self.assertEqual((metric['within'], metric['total']),
                                 (expected['metric']['hits'], expected['metric']['total']))
                self.assertAlmostEqual(metric['percent'], expected['metric']['percent'], places=6)

    def test_dining_invalid_boundaries_and_small_limit(self):
        for options in ({'month': 0}, {'month': 13}, {'month': float('inf')}, {'month': 1.5},
                        {'month': False}, {'limit': 0}, {'limit': 101}, {'limit': '1.5'},
                        {'limit': True}, {'category': '가' * 101}, {'category': []}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                predict_dining(ROOT, **options)
        self.assertEqual(len(predict_dining(ROOT, month=12, limit=1)['items']), 1)

    def test_public_guide_replays_22_frozen_queries_with_current_routing(self):
        directory = ROOT / 'development_support' / 'retrieval_v20'
        benchmark = json.loads((directory / 'benchmark.json').read_text('utf-8'))
        frozen = json.loads((directory / 'benchmark_freeze.json').read_text('utf-8'))
        self.assertEqual(digest(benchmark), frozen['benchmark_sha256'])
        cases = [case for case in benchmark['cases'] if case['domain'] == 'guide' and case['split'] == 'test']
        self.assertEqual(len(cases), 22)

        def trust_at_audit_date(root, item, **options):
            return place_trust(root, item, **options, as_of=dt.date(2026, 11, 6))

        with patch('jeju_agent.assistant_search.place_trust', trust_at_audit_date):
            for case in cases:
                with self.subTest(case=case['id']):
                    items = search_assistant(ROOT, case['query'], limit=5, include_route_restricted=True)
                    if case['relevant_ids']:
                        self.assertTrue(items)
                        self.assertIn(items[0]['id'], case['relevant_ids'])
                    else:
                        self.assertEqual(items, [])


class ModelReadinessRegressionTests(unittest.TestCase):
    """Ensure readiness follows the validated 1047 serving path."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        files = (
            'config/place_trust_policy_v15.json',
            'data_reference/tourism.sqlite',
            'data_reference/tourism_guides_v12.json',
            'data_reference/model_portfolio_v20.json',
            'models_candidates_v23/audience/protocol.json',
            'models_candidates_v23/audience/selection.json',
            'models_candidates_v23/audience/result.json',
            'models_candidates_v23/audience/serving_profile.json',
            'models_audience/audience_model.json',
            'data_raw/hub/hub_1048_5832.csv',
            MODEL_RELATIVE,
            SOURCE_RELATIVE,
        )
        for relative in files:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        source_receipts = 'data_raw/tourism/v12/official_fields'
        shutil.copytree(ROOT / source_receipts, self.root / source_receipts)
        self.assertEqual(predict_dining(self.root)['status'], 'historical_pattern')

    def assert_unready(self):
        health = operational_check(self.root)
        self.assertFalse(health['models_ready'], health)
        self.assertEqual(health['unavailable_models'], ['1047'])
        self.assertGreater(health['automatic_places'], 0)

    def test_valid_1047_serving_files_are_ready(self):
        health = operational_check(self.root)
        self.assertTrue(health['models_ready'], health)
        self.assertEqual(health['unavailable_models'], [])

    def test_missing_1047_source_must_not_report_ready(self):
        (self.root / SOURCE_RELATIVE).unlink()
        with self.assertRaises(FileNotFoundError) as failure:
            predict_dining(self.root)
        self.assertEqual(Path(failure.exception.filename).name, Path(SOURCE_RELATIVE).name)
        self.assert_unready()

    def test_corrupt_1047_model_must_not_report_ready(self):
        (self.root / MODEL_RELATIVE).write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '외식 모델 형식'):
            predict_dining(self.root)
        self.assert_unready()

    def test_replaced_1047_source_fails_even_after_a_warm_cache(self):
        self.assertTrue(operational_check(self.root)['models_ready'])
        with (self.root / SOURCE_RELATIVE).open('ab') as damaged:
            damaged.write(b'\n')
        with self.assertRaisesRegex(ValueError, '해시'):
            predict_dining(self.root)
        self.assert_unready()
