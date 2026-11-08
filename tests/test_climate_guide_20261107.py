"""Historical climate contract and fail-closed integrity checks; fixtures stay in TempDir."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jeju_agent import climate_guide as climate
from jeju_agent import climate_features


class ClimateGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / climate.CONFIG_PATH).read_text(encoding='utf-8'))
        cls.evaluation = json.loads((ROOT / cls.config['assets']['evaluation']['path']).read_text(encoding='utf-8'))
        cls.model = climate_features.load_model(ROOT / cls.config['assets']['model']['path'])
        cls.asset_paths = [climate.CONFIG_PATH] + [v['path'] for v in cls.config['assets'].values()] + [v['path'] for v in cls.config['source_files']]

    def copy_assets(self):
        temp = tempfile.TemporaryDirectory(prefix='jeju_climate_integrity_')
        self.addCleanup(temp.cleanup)
        target = Path(temp.name).resolve()
        for relative in self.asset_paths:
            output = (target / relative).resolve()
            self.assertTrue(output.is_relative_to(target))
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, output)
        return target

    def test_status_discloses_real_source_period_and_holdout_results(self):
        result = climate.climate_status(ROOT)
        self.assertTrue(result['available'])
        self.assertTrue(result['ml_applied'])
        self.assertFalse(result['current_forecast'])
        self.assertFalse(result['rainfall_available'])
        self.assertFalse(result['llm_used'])
        self.assertEqual(result['runtime'], 'offline_stdlib_cpu')
        self.assertEqual(result['reference_period'], ['2000-01-01', '2021-10-31'])
        self.assertEqual(result['source']['id'], 877)
        self.assertEqual(result['source']['original_producer'], '기상청')
        self.assertEqual(result['source']['hub_publisher'], '고성빈')
        self.assertEqual(result['source']['distribution_portal'], '제주데이터허브')
        self.assertEqual(result['source']['raw_rows'], 31900)
        self.assertFalse(result['source']['direct_center_production_claimed'])
        self.assertEqual(result['model']['train_period'], ['2000-01-01', '2016-12-31'])
        self.assertEqual(result['model']['validation_period'], ['2019-01-01', '2021-10-31'])
        self.assertEqual(result['model']['test_rows'], self.evaluation['test_rows'])
        self.assertAlmostEqual(result['model']['test_mae_c'], self.evaluation['point_test']['mae_c'])
        self.assertAlmostEqual(result['model']['interval_coverage'], self.evaluation['interval_test']['coverage'])
        self.assertAlmostEqual(result['model']['baseline_mae_c'], self.evaluation['baseline_test'][self.evaluation['best_dev_selected_baseline']]['point']['mae_c'])
        self.assertFalse(result['model']['accuracy_improvement_claimed'])
        self.assertFalse(result['model']['year_feature_used'])
        self.assertFalse(result['model']['current_weather_input_used'])
        self.assertEqual(result['model']['annual_test'], self.evaluation['per_year'])
        self.assertAlmostEqual(result['model']['latest_year_test']['interval_coverage'], .6875)
        self.assertAlmostEqual(result['model']['latest_year_test']['bias_c'], self.evaluation['per_year']['2021']['point']['bias_prediction_minus_observed_c'])
        self.assertTrue(any('68.8%' in message for message in result['limitations']))
        self.assertNotIn('selected', result)

    def test_requested_date_reaches_every_station_and_selected_value(self):
        for station in ['jeju', 'gosan', 'seongsan', 'seogwipo']:
            with self.subTest(station=station):
                result = climate.climate_reference(ROOT, 8, 23, station)
                self.assertEqual(result['requested'], {'month': 8, 'day': 23, 'station': station})
                self.assertEqual([r['station'] for r in result['estimates']], ['jeju', 'gosan', 'seongsan', 'seogwipo'])
                for row in result['estimates']:
                    self.assertEqual(row, climate_features.predict(self.model, row['station'], 8, 23))
                    self.assertEqual((row['month'], row['day']), (8, 23))
                    for key in ('point_c', 'lower_c', 'upper_c'):
                        self.assertTrue(math.isfinite(row[key]))
                    self.assertLessEqual(row['lower_c'], row['upper_c'])
                self.assertEqual(result['selected'], next(r for r in result['estimates'] if r['station'] == station))

    def test_seasonality_uses_twelve_monthly_fifteenths_not_the_requested_day(self):
        result = climate.climate_reference(ROOT, '04', '27', 'seongsan')
        self.assertEqual(result['requested'], {'month': 4, 'day': 27, 'station': 'seongsan'})
        self.assertEqual(len(result['seasonality']), 12)
        self.assertEqual([(r['month'], r['day']) for r in result['seasonality']], [(m, 15) for m in range(1, 13)])
        self.assertEqual(result['seasonality'], [climate_features.predict(self.model, 'seongsan', m, 15) for m in range(1, 13)])
        self.assertEqual(result['selected']['day'], 27)

    def test_february_twenty_ninth_is_a_valid_year_free_calendar_input(self):
        for station in ['jeju', 'gosan', 'seongsan', 'seogwipo']:
            with self.subTest(station=station):
                result = climate.climate_reference(ROOT, 2, 29, station)
                self.assertEqual(result['selected'], climate_features.predict(self.model, station, 2, 29))
                self.assertEqual(result['selected']['day'], 29)
                self.assertFalse(result['current_forecast'])

    def test_invalid_noninteger_month_or_day_cannot_be_coerced(self):
        for value in [True, False, None, 4.0, [], {}, '4.0', '+4', '-1', ' 4', '4 ', '0004', '', '４']:
            with self.subTest(value=repr(value), field='month'), self.assertRaises(ValueError):
                climate.climate_reference(ROOT, value, 15)
            with self.subTest(value=repr(value), field='day'), self.assertRaises(ValueError):
                climate.climate_reference(ROOT, 4, value)

    def test_impossible_calendar_dates_are_rejected(self):
        for month, day in [(0, 1), (13, 1), (1, 0), (1, 32), (2, 30), (2, 31), (4, 31), (6, 31), (9, 31), (11, 31)]:
            with self.subTest(month=month, day=day), self.assertRaises(ValueError):
                climate.climate_reference(ROOT, month, day)

    def test_station_requires_an_exact_registered_identifier(self):
        for station in ['제주', 'Jeju', 'jeju ', '', 'unknown', '../jeju', None, True, 1, [], {}]:
            with self.subTest(station=repr(station)), self.assertRaises(ValueError):
                climate.climate_reference(ROOT, 4, 15, station)

    def test_cached_results_reject_same_size_same_mtime_changes_in_every_asset(self):
        target = self.copy_assets()
        climate.climate_reference(target, 4, 15)
        for relative in self.asset_paths:
            path = target / relative
            before = path.read_bytes()
            stat = path.stat()
            with self.subTest(asset=relative):
                path.write_bytes(bytes([before[0] ^ 1]) + before[1:])
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                self.assertEqual(path.stat().st_size, stat.st_size)
                with self.assertRaises(climate.ClimateDataError):
                    climate.climate_status(target)
                with self.assertRaises(climate.ClimateDataError):
                    climate.climate_reference(target, 4, 15)
            path.write_bytes(before)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertTrue(climate.climate_status(target)['available'])

    def test_cached_results_reject_each_missing_asset(self):
        target = self.copy_assets()
        climate.climate_reference(target, 4, 15)
        for relative in self.asset_paths:
            path = target / relative
            content = path.read_bytes()
            with self.subTest(asset=relative):
                # Remove a single known fixture; never modify real source/model files.
                path.unlink()
                with self.assertRaises(climate.ClimateDataError):
                    climate.climate_status(target)
                with self.assertRaises(climate.ClimateDataError):
                    climate.climate_reference(target, 4, 15)
            path.write_bytes(content)
            self.assertTrue(climate.climate_status(target)['available'])

    def test_an_empty_data_root_fails_without_fabricated_guidance(self):
        with tempfile.TemporaryDirectory(prefix='jeju_climate_empty_') as temporary:
            for function, args in [(climate.climate_status, ()), (climate.climate_reference, (4, 15))]:
                with self.subTest(function=function.__name__), self.assertRaises(climate.ClimateDataError):
                    function(Path(temporary), *args)

    def test_read_only_queries_preserve_all_real_assets_and_tourism_policy(self):
        watched = [ROOT / relative for relative in self.asset_paths] + [
            ROOT / 'config/tourism_overlap_policy.json', ROOT / 'config/place_trust_policy_v15.json',
            ROOT / 'data_reference/tourism.sqlite']
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
        climate.climate_status(ROOT)
        for station in ['jeju', 'gosan', 'seongsan', 'seogwipo']:
            climate.climate_reference(ROOT, 10, 7, station)
        after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
