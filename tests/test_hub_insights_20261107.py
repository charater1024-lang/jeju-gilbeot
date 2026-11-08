"""Read-only source alignment, tamper rejection and historical-scope tests."""
import csv
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from jeju_agent import hub_insights as insights

ROOT = Path(__file__).resolve().parents[1]


class HubInsightsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = ROOT / '.test_tmp'
        cls.scratch.mkdir(exist_ok=True)

    def copy_assets(self, regional=False):
        temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.addCleanup(temp.cleanup)
        target = Path(temp.name)
        paths = ([insights.REGIONAL_MODEL_PATH] +
                 [f'data/hub_insights/regional/raw_758_{attachment}.csv' for attachment, _ in insights.REGIONAL_SOURCES]
                 if regional else [spec['path'] for spec in insights.VISITOR_SOURCES.values()])
        for relative in paths:
            out = target / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, out)
        return target

    def test_missing_assets_are_unavailable_not_fabricated_statistics(self):
        with tempfile.TemporaryDirectory(dir=self.scratch) as temp:
            for function in (insights.visitor_patterns, insights.regional_patterns):
                result = function(Path(temp))
                self.assertFalse(result['available'])
                self.assertFalse(result['ml_applied'])
                self.assertIsNone(result['selected'])
                self.assertEqual(result['items'], [])

    def test_queries_accept_only_exact_registered_keys(self):
        for place in ('국립 제주 박물관', '성산', '../성산일출봉', None, True):
            with self.subTest(place=place), self.assertRaises(ValueError):
                insights.visitor_patterns(ROOT, place)
        for audience in ('all', 'resident', 'foreigner', None):
            with self.subTest(audience=audience), self.assertRaises(ValueError):
                insights.visitor_patterns(ROOT, audience=audience)
        for region in ('구좌읍', '제주시 |구좌읍', '제주시|모르는동', '제주시|구좌읍|추가', None):
            with self.subTest(region=region), self.assertRaises(ValueError):
                insights.regional_patterns(ROOT, region)

    def test_visitor_history_is_exact_observed_source_including_recorded_zeros(self):
        result = insights.visitor_patterns(ROOT, '국립제주박물관', 'foreign')
        source = ROOT / insights.VISITOR_SOURCES['foreign']['path']
        with source.open(encoding='cp949', newline='') as stream:
            actual = {r['날짜'].replace('.', '-'): int(r['관광객수']) for r in csv.DictReader(stream)
                      if r['관광지명'] == '국립제주박물관'}
        returned = {r['month']: r['count'] for r in result['selected']['monthly_series']}
        self.assertEqual(returned, actual)
        self.assertEqual(len(returned), 192)
        self.assertEqual(sum(value == 0 for value in returned.values()), 3)
        self.assertEqual(result['selected']['name'], '국립 제주 박물관')
        self.assertEqual(len(result['places']), 6)
        self.assertFalse(result['ml_applied'])
        self.assertFalse(result['selected']['forecast']['available'])
        self.assertIsNone(result['selected']['forecast']['count'])
        self.assertEqual(result['selected']['forecast']['as_of_month'], '2024-12')

    def test_seasonality_preserves_per_year_denominator_and_period(self):
        result = insights.visitor_patterns(ROOT, '비자림')
        selected = result['selected']
        self.assertEqual(selected['seasonality_period'], {'start_month': '2018-01', 'end_month': '2024-12'})
        self.assertEqual(len(selected['seasonality']), 12)
        self.assertTrue(all(row['count_years'] == 7 for row in selected['seasonality']))
        self.assertAlmostEqual(sum(row['share'] for row in selected['seasonality']), 1)
        history = {row['month']: row['count'] for row in selected['monthly_series']}
        expected_january = sum(history[f'{year}-01'] / sum(history[f'{year}-{m:02d}'] for m in range(1, 13))
                               for year in range(2018, 2025)) / 7
        self.assertAlmostEqual(selected['seasonality'][0]['share'], expected_january)

    def test_same_size_same_mtime_source_change_cannot_reuse_cached_approval(self):
        temp = self.copy_assets()
        source = temp / insights.VISITOR_SOURCES['domestic']['path']
        insights._visitor_observations(temp)
        stat = source.stat()
        raw = source.read_bytes()
        source.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with self.assertRaises(insights.HubInsightDataError):
            insights.visitor_patterns(temp)

    def test_missing_month_is_rejected_even_with_a_new_valid_fixture_hash(self):
        # A modified copy tests calendar validation; fixtures never enter serving.
        temp = self.copy_assets()
        spec = dict(insights.VISITOR_SOURCES['domestic'])
        source = temp / spec['path']
        rows = source.read_text(encoding='cp949').splitlines()
        rows = [row for row in rows if not row.startswith('2009.01,국립제주박물관,')]
        content = ('\r\n'.join(rows) + '\r\n').encode('cp949')
        source.write_bytes(content)
        spec['sha256'] = hashlib.sha256(content).hexdigest()
        with patch.dict(insights.VISITOR_SOURCES, {'domestic': spec}):
            with self.assertRaises(insights.HubInsightDataError):
                insights._visitor_observations(temp)

    def test_ambiguous_existing_place_mapping_is_not_resolved_by_guessing(self):
        from jeju_agent.tourism_access import approved_places
        places = approved_places(ROOT)
        original = next(p for p in places if p['name'] == '비자림')
        with patch('jeju_agent.tourism_access.approved_places', return_value=places + [dict(original, id='duplicate_fixture')]):
            with self.assertRaises(insights.HubInsightDataError):
                insights.visitor_patterns(ROOT)

    def test_regional_profiles_are_historical_complete_and_not_geographic(self):
        result = insights.regional_patterns(ROOT, '제주시|구좌읍')
        self.assertTrue(result['ml_applied'])
        self.assertEqual(len(result['areas']), 39)
        self.assertEqual(result['period'], {'start_month': '2020-06', 'end_month': '2021-05'})
        self.assertEqual(result['model']['pca_dimension'], 2)
        self.assertEqual(result['model']['cluster_count'], 3)
        selected = result['selected']
        self.assertEqual(len(selected['shares']), 6)
        self.assertAlmostEqual(sum(row['share'] for row in selected['shares']), 1)
        self.assertEqual(len(selected['nearest']), 3)
        self.assertNotIn(selected['key'], {row['key'] for row in selected['nearest']})
        self.assertEqual([r['distance'] for r in selected['nearest']], sorted(r['distance'] for r in selected['nearest']))
        self.assertTrue(all(r['distance_kind'] == 'projected_clr_distance_not_geographic_or_probability'
                            for r in selected['nearest']))
        self.assertTrue(all(r['not_itinerary_place'] for r in selected['nearest']))

    def test_regional_shares_equal_actual_12month_category_sums(self):
        result = insights.regional_patterns(ROOT, '제주시|구좌읍')
        categories = {row['name'] for row in result['selected']['shares']}
        counts = {name: 0.0 for name in categories}
        months = {f'2020-{month:02d}' for month in range(6, 13)} | {f'2021-{month:02d}' for month in range(1, 6)}
        observed = {name: set() for name in categories}
        for attachment, _ in insights.REGIONAL_SOURCES:
            with (ROOT / f'data/hub_insights/regional/raw_758_{attachment}.csv').open(encoding='cp949', newline='') as stream:
                for row in csv.DictReader(stream):
                    if row['시도명'] == '제주시' and row['읍면동명'] == '구좌읍' and row['년월'] in months and row['업종명'] in categories:
                        counts[row['업종명']] += float(row['이용자수'])
                        observed[row['업종명']].add(row['년월'])
        self.assertTrue(all(value == months for value in observed.values()))
        total = sum(counts.values())
        for row in result['selected']['shares']:
            self.assertAlmostEqual(row['share'], counts[row['name']] / total)

    def test_regional_model_and_source_changes_fail_closed(self):
        temp = self.copy_assets(regional=True)
        model = temp / insights.REGIONAL_MODEL_PATH
        raw = model.read_bytes()
        model.write_bytes(raw[:-1] + b' ')
        with self.assertRaises(insights.HubInsightDataError):
            insights.regional_patterns(temp)
        shutil.copy2(ROOT / insights.REGIONAL_MODEL_PATH, model)
        source = temp / 'data/hub_insights/regional/raw_758_2002.csv'
        raw = source.read_bytes()
        source.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaises(insights.HubInsightDataError):
            insights.regional_patterns(temp)

    def test_queries_do_not_write_assets_or_relax_tourism_policy(self):
        from jeju_agent.tourism_access import approved_places
        from jeju_agent.place_trust import place_trust
        watched = [ROOT / 'config/tourism_overlap_policy.json', ROOT / 'config/place_trust_policy_v15.json',
                   ROOT / 'data_reference/tourism.sqlite', ROOT / insights.REGIONAL_MODEL_PATH]
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
        insights.visitor_patterns(ROOT)
        insights.regional_patterns(ROOT)
        self.assertEqual(before, {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched})
        places = approved_places(ROOT)
        self.assertEqual(len(places), 68)
        eligible = [place for place in places if place_trust(ROOT, place, as_of=date(2026, 11, 7))['automatic_eligible']]
        self.assertEqual(len(eligible), 40)


if __name__ == '__main__':
    unittest.main()
