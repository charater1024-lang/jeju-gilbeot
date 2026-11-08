"""Forecast boundary tests use explicit mocked provider responses, not training data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from jeju_agent import flower_weather as weather

ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 11, 7, 12, 30, tzinfo=weather.KST)
BASE_POINT = {'id': 'osm_tourism_way_1537196430', 'name': '제주목관아',
              'latitude': 33.5139451, 'longitude': 126.5221528,
              'kind': 'attraction', 'source_overlap_verified': True,
              'coordinate_verified': False}


def provider_payload(today=None, latitude=None, longitude=None):
    today = today or FIXED_NOW.date()
    return {'latitude': BASE_POINT['latitude'] if latitude is None else latitude,
            'longitude': BASE_POINT['longitude'] if longitude is None else longitude,
            'timezone': 'Asia/Seoul', 'utc_offset_seconds': 32400,
            'daily_units': dict(weather.EXPECTED_UNITS),
            'daily': {'time': [(today + timedelta(days=i)).isoformat() for i in range(7)],
                      'temperature_2m_min': [8. + i for i in range(7)],
                      'temperature_2m_max': [15. + i for i in range(7)],
                      'precipitation_sum': [0., 1., 2., 3., 0., 0., .5],
                      'wind_speed_10m_max': [2., 3., 4., 5., 3., 2., 1.]}}


class Response:
    def __init__(self, url, payload=None, content_type='application/json', code=200, raw=None):
        self.url = url; self.payload = payload or provider_payload()
        self.headers = {'Content-Type': content_type}; self.code = code
        self.raw = raw; self.read_limits = []
    def __enter__(self):return self
    def __exit__(self, *_):return False
    def getcode(self):return self.code
    def geturl(self):return self.url
    def read(self, maximum):
        self.read_limits.append(maximum)
        raw = self.raw if self.raw is not None else json.dumps(self.payload, ensure_ascii=False).encode('utf-8')
        return raw[:maximum]


class FlowerWeatherTests(unittest.TestCase):
    def setUp(self):
        with weather._CACHE_LOCK:
            weather._CACHE.clear(); weather._POINT_LOCKS.clear()
        self.now = FIXED_NOW; self.clock = 100.
        self.environment = patch.dict(os.environ, {'JEJU_FLOWER_WEATHER_API': '1'})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.catalogue = patch.object(weather, 'approved_places', return_value=[deepcopy(BASE_POINT)])
        self.catalogue.start(); self.addCleanup(self.catalogue.stop)
        self.datetime_patch = patch.object(weather, '_now', side_effect=lambda: self.now)
        self.datetime_patch.start(); self.addCleanup(self.datetime_patch.stop)
        self.clock_patch = patch.object(weather.time, 'monotonic', side_effect=lambda: self.clock)
        self.clock_patch.start(); self.addCleanup(self.clock_patch.stop)
        self.responses = []
        def open_response(request, timeout):
            query = parse_qs(urlsplit(request.full_url).query)
            response = Response(request.full_url, provider_payload(self.now.date(), float(query['latitude'][0]), float(query['longitude'][0])))
            self.responses.append(response)
            return response
        self.opener_patch = patch.object(weather._OPENER, 'open', side_effect=open_response)
        self.open = self.opener_patch.start(); self.addCleanup(self.opener_patch.stop)

    def query(self):return weather.flower_weather(ROOT, BASE_POINT['id'])

    def test_place_list_is_local_exact_and_has_no_coordinate_substitution(self):
        rows = [deepcopy(BASE_POINT), dict(BASE_POINT, id='alias', name='제주목관아 부속 식당'),
                dict(BASE_POINT, id='bad', name='함덕해수욕장', latitude=126.6, longitude=33.5)]
        with patch.object(weather, 'approved_places', return_value=rows):
            self.assertEqual(weather.weather_places(ROOT), [{'id': BASE_POINT['id'], 'name': '제주목관아'}])
        self.open.assert_not_called()

    def test_ambiguous_names_or_duplicate_ids_are_excluded(self):
        for rows in [[BASE_POINT, dict(BASE_POINT, id='second')],
                     [BASE_POINT, dict(BASE_POINT, name='성산일출봉')]]:
            with self.subTest(rows=rows), patch.object(weather, 'approved_places', return_value=rows):
                self.assertEqual(weather.weather_places(ROOT), [])

    def test_request_has_fixed_host_units_and_only_a_public_reference_point(self):
        result = self.query()
        request = self.open.call_args.args[0]; query = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual((urlsplit(request.full_url).scheme, urlsplit(request.full_url).netloc, urlsplit(request.full_url).path),
                         ('https', 'api.open-meteo.com', '/v1/forecast'))
        self.assertEqual(set(query), {'latitude', 'longitude', 'daily', 'wind_speed_unit', 'timezone', 'forecast_days'})
        self.assertEqual(query['daily'], [','.join(weather.DAILY_VARIABLES)])
        self.assertEqual(query['wind_speed_unit'], ['ms']); self.assertEqual(query['timezone'], ['Asia/Seoul'])
        self.assertEqual(query['forecast_days'], ['7']); self.assertEqual(float(query['latitude'][0]), BASE_POINT['latitude'])
        self.assertEqual(self.open.call_args.kwargs, {'timeout': 7})
        self.assertEqual(self.responses[0].read_limits, [512 * 1024 + 1])
        self.assertEqual(len(result['days']), 7); self.assertEqual(result['forecast_period'], ['2026-11-07', '2026-11-13'])
        self.assertTrue(result['current_forecast']); self.assertFalse(result['flower_prediction'])
        self.assertFalse(result['personal_location_used']); self.assertFalse(result['locally_trained_forecast_model'])
        self.assertEqual(result['point']['id'], BASE_POINT['id']); self.assertFalse(result['cached'])
        self.assertEqual(result['source_url'], 'https://open-meteo.com/')
        self.assertEqual(result['licence_url'], 'https://open-meteo.com/en/licence')

    def test_unknown_or_url_like_place_is_rejected_without_network(self):
        for value in ['https://evil.example/', 'unknown', '', None, [], True, 184]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                weather.flower_weather(ROOT, value)
        self.open.assert_not_called()

    def test_environment_disabled_prevents_network_and_cached_response(self):
        self.query(); self.open.reset_mock()
        with patch.dict(os.environ, {'JEJU_FLOWER_WEATHER_API': '0'}), self.assertRaises(weather.FlowerWeatherUnavailable):
            self.query()
        self.open.assert_not_called()

    def test_cache_is_same_day_and_expires_at_thirty_minutes(self):
        first = self.query(); first['days'][0]['t_min_c'] = 999
        self.clock += 1799
        cached = self.query(); self.assertTrue(cached['cached']); self.assertNotEqual(cached['days'][0]['t_min_c'], 999)
        self.assertEqual(self.open.call_count, 1)
        self.clock += 1
        expired = self.query(); self.assertFalse(expired['cached']); self.assertEqual(self.open.call_count, 2)

    def test_cache_invalidates_at_kst_midnight_even_before_ttl(self):
        self.now = FIXED_NOW.replace(hour=23, minute=59)
        self.query(); self.clock += 120; self.now += timedelta(minutes=2)
        result = self.query(); self.assertFalse(result['cached']); self.assertEqual(self.open.call_count, 2)
        self.assertEqual(result['days'][0]['date'], '2026-11-08')

    def test_current_catalogue_point_is_rechecked_before_cache_use(self):
        self.query(); self.open.reset_mock()
        with patch.object(weather, 'approved_places', return_value=[]), self.assertRaises(ValueError):self.query()
        self.open.assert_not_called()

    def test_expired_cache_is_not_returned_after_network_failure(self):
        self.query(); self.clock += 1801
        self.open.side_effect = URLError('unavailable')
        with self.assertRaises(weather.FlowerWeatherUnavailable):self.query()
        self.assertEqual(weather._CACHE, {})

    def test_network_errors_and_redirects_have_no_fabricated_fallback(self):
        for problem in [URLError('unavailable'), TimeoutError(), HTTPError('https://api.open-meteo.com/', 302, 'redirect', {}, None)]:
            with self.subTest(problem=type(problem).__name__):
                self.open.side_effect = problem
                with self.assertRaises(weather.FlowerWeatherUnavailable):self.query()
        self.assertIsNone(weather._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example/'))

    def test_non_json_oversized_redirected_and_provider_error_responses_are_rejected(self):
        cases = [{'content_type': 'text/html', 'raw': b'<h1>blocked</h1>'},
                 {'raw': b'<h1>blocked</h1>'}, {'raw': b' ' * (weather.MAX_RESPONSE_BYTES + 1)},
                 {'raw': b'{"error":true,"reason":"test"}'}, {'raw': b'{"value":NaN}'}, {'code': 503}]
        for overrides in cases:
            with self.subTest(overrides={k:type(v).__name__ for k,v in overrides.items()}):
                self.open.side_effect = lambda request, timeout, spec=overrides: Response(request.full_url, **spec)
                with self.assertRaises(weather.FlowerWeatherUnavailable):self.query()
        self.open.side_effect = lambda request, timeout: Response('https://evil.example/forecast')
        with self.assertRaises(weather.FlowerWeatherUnavailable):self.query()

    def test_wrong_dates_units_timezone_grid_and_incomplete_values_are_rejected(self):
        original = provider_payload(); bad = []
        for field, value in [('timezone', 'UTC'), ('utc_offset_seconds', 0), ('latitude', 37.), ('longitude', 127.8)]:
            p=deepcopy(original);p[field]=value;bad.append(p)
        for field, value in [('temperature_2m_min','K'),('precipitation_sum','inch'),('wind_speed_10m_max','km/h')]:
            p=deepcopy(original);p['daily_units'][field]=value;bad.append(p)
        p=deepcopy(original);p['daily']['time'][0]='2026-11-06';bad.append(p)
        p=deepcopy(original);p['daily']['time'][1]='2026-11-09';bad.append(p)
        for key, value in [('temperature_2m_min',None),('temperature_2m_max',True),('precipitation_sum',-1),('wind_speed_10m_max',-1),('temperature_2m_min',100),('temperature_2m_max',999),('precipitation_sum',9999),('wind_speed_10m_max',999)]:
            p=deepcopy(original);p['daily'][key][0]=value;bad.append(p)
        p=deepcopy(original);p['daily']['wind_speed_10m_max'].pop();bad.append(p)
        for payload in bad:
            with self.subTest(payload=payload):
                self.open.side_effect=lambda request, timeout, p=payload:Response(request.full_url,p)
                with self.assertRaises(weather.FlowerWeatherUnavailable):self.query()
        self.assertEqual(weather._CACHE,{})

    def test_same_point_concurrent_requests_share_one_provider_response(self):
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:self.query(), range(4)))
        self.assertEqual(self.open.call_count,1)
        self.assertEqual(sum(not r['cached'] for r in results),1)

    def test_real_public_catalogue_and_core_data_are_unchanged(self):
        names=['data_reference/tourism.sqlite','data_reference/tourism_guides_v12.json','config/tourism_auto_policy_v15.json']
        watched=[ROOT/name for name in names if (ROOT/name).is_file()]
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
        with patch.object(weather,'approved_places',wraps=__import__('jeju_agent.tourism_access',fromlist=['approved_places']).approved_places):
            places=weather.weather_places(ROOT)
        self.assertTrue(places);self.assertLessEqual(len(places),5)
        self.assertTrue(all(p['name'] in weather.PUBLIC_NAMES for p in places))
        self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in watched})
        self.open.assert_not_called()


if __name__=='__main__':unittest.main()
