"""Optional seven-day external grid forecasts for verified public map points.

No device location is accepted, requested, stored, or transmitted. The catalogue
points are map references, not ASOS stations or verified attraction entrances.
Open-Meteo forecasts are not a locally trained flower/bloom prediction model.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .tourism_access import approved_places

API_URL = 'https://api.open-meteo.com/v1/forecast'
KST = timezone(timedelta(hours=9))
TIMEOUT_SECONDS = 7
MAX_RESPONSE_BYTES = 512 * 1024
CACHE_SECONDS = 30 * 60
PUBLIC_NAMES = ('제주목관아', '성산일출봉', '천지연폭포', '협재해수욕장', '함덕해수욕장')
DAILY_VARIABLES = ('temperature_2m_min', 'temperature_2m_max', 'precipitation_sum', 'wind_speed_10m_max')
EXPECTED_UNITS = {'time': 'iso8601', 'temperature_2m_min': '°C', 'temperature_2m_max': '°C',
                  'precipitation_sum': 'mm', 'wind_speed_10m_max': 'm/s'}
_CACHE = {}
_POINT_LOCKS = {}
_CACHE_LOCK = Lock()


class FlowerWeatherUnavailable(RuntimeError):
    """External forecast unavailable, disabled, stale, or invalid; no fallback."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def _now():
    return datetime.now(KST)


def _finite(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _public_points(root):
    try:
        candidates = approved_places(Path(root))
        named = [p for p in candidates if p.get('name') in PUBLIC_NAMES]
        name_counts = Counter(p.get('name') for p in named)
        id_counts = Counter(p.get('id') for p in named if isinstance(p.get('id'), str))
        points = []
        for name in PUBLIC_NAMES:
            if name_counts[name] != 1:
                continue
            item = next(p for p in named if p.get('name') == name)
            ident, lat, lon = item.get('id'), item.get('latitude'), item.get('longitude')
            if (not isinstance(ident, str) or not ident or len(ident) > 160 or id_counts[ident] != 1
                    or item.get('source_overlap_verified') is not True or item.get('kind') != 'attraction'
                    or not _finite(lat) or not _finite(lon) or not 32.8 <= lat <= 34.0 or not 125.8 <= lon <= 127.1):
                continue
            points.append({'id': ident, 'name': name, 'lat': float(lat), 'lon': float(lon)})
        return points
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
        raise FlowerWeatherUnavailable('공개 기준 장소 자료를 확인할 수 없습니다.') from exc


def weather_places(root):
    """List supported public names/IDs locally; never makes a network request."""
    return [{'id': p['id'], 'name': p['name']} for p in _public_points(root)]


def _read_payload(point):
    query = urlencode({'latitude': format(point['lat'], '.7f'), 'longitude': format(point['lon'], '.7f'),
                       'daily': ','.join(DAILY_VARIABLES), 'wind_speed_unit': 'ms',
                       'timezone': 'Asia/Seoul', 'forecast_days': '7'})
    url = API_URL + '?' + query
    request = Request(url, headers={'User-Agent': 'TamraTtara/1.0 (noncommercial forecast reference)',
                                   'Accept': 'application/json'})
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.getcode() != 200 or response.geturl() != url:
                raise FlowerWeatherUnavailable('날씨 제공자의 응답 경로를 확인할 수 없습니다.')
            content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
            if content_type != 'application/json':
                raise FlowerWeatherUnavailable('날씨 제공자가 JSON 예보를 반환하지 않았습니다.')
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
            raise FlowerWeatherUnavailable('날씨 응답이 허용 크기를 넘었습니다.')
        def bad_constant(_):
            raise ValueError('Non-finite JSON')
        value = json.loads(raw.decode('utf-8'), parse_constant=bad_constant)
        if not isinstance(value, dict) or value.get('error'):
            raise FlowerWeatherUnavailable('날씨 제공자가 예보를 반환하지 않았습니다.')
        return value
    except FlowerWeatherUnavailable:
        raise
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, UnicodeError, TypeError, AttributeError, RecursionError) as exc:
        raise FlowerWeatherUnavailable('날씨 API에 연결할 수 없습니다. 잠시 뒤 다시 확인해 주세요.') from exc


def _validated_days(payload, point, today):
    try:
        if payload.get('timezone') != 'Asia/Seoul' or payload.get('utc_offset_seconds') != 32400:
            raise ValueError('timezone')
        grid_lat, grid_lon = payload.get('latitude'), payload.get('longitude')
        if (not _finite(grid_lat) or not _finite(grid_lon)
                or abs(grid_lat - point['lat']) > .5 or abs(grid_lon - point['lon']) > .5):
            raise ValueError('forecast grid location')
        units, daily = payload['daily_units'], payload['daily']
        if not isinstance(units, dict) or not isinstance(daily, dict) or any(units.get(k) != v for k, v in EXPECTED_UNITS.items()):
            raise ValueError('daily units')
        dates = [(today + timedelta(days=i)).isoformat() for i in range(7)]
        if daily.get('time') != dates:
            raise ValueError('seven current consecutive KST dates')
        for key in DAILY_VARIABLES:
            values = daily[key]
            if not isinstance(values, list) or len(values) != 7 or not all(_finite(v) for v in values):
                raise ValueError('complete finite daily values')
        days = []
        for i, date in enumerate(dates):
            low, high = daily['temperature_2m_min'][i], daily['temperature_2m_max'][i]
            rain, wind = daily['precipitation_sum'][i], daily['wind_speed_10m_max'][i]
            if not -60 <= low <= high <= 65 or not 0 <= rain <= 2000 or not 0 <= wind <= 150:
                raise ValueError('physical relationship')
            days.append({'date': date, 't_min_c': float(low), 't_max_c': float(high),
                         'precipitation_mm': float(rain), 'wind_max_ms': float(wind)})
        return days, {'lat': float(grid_lat), 'lon': float(grid_lon)}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise FlowerWeatherUnavailable('날씨 응답의 날짜·단위·수치를 확인할 수 없습니다.') from exc


def _usable_cache(entry, now, clock):
    if not entry:
        return False
    age = clock - entry['clock']
    result = entry['result']
    expected = [(now.date() + timedelta(days=i)).isoformat() for i in range(7)]
    return (0 <= age < CACHE_SECONDS and entry['retrieved_date'] == now.date()
            and [d['date'] for d in result['days']] == expected)


def flower_weather(root, place_id):
    """Fetch only a selected, currently approved public point's seven-day grid forecast."""
    if os.environ.get('JEJU_FLOWER_WEATHER_API', '1').strip() == '0':
        raise FlowerWeatherUnavailable('외부 날씨 API가 운영 설정에서 꺼져 있습니다.')
    if not isinstance(place_id, str) or not place_id or len(place_id) > 160:
        raise ValueError('목록에 있는 공개 기준 장소를 선택해 주세요.')
    point = next((p for p in _public_points(root) if p['id'] == place_id), None)
    if point is None:
        raise ValueError('목록에 있는 공개 기준 장소를 선택해 주세요.')
    key = (str(Path(root).resolve()), point['id'], point['lat'], point['lon'])
    with _CACHE_LOCK:
        point_lock = _POINT_LOCKS.setdefault(key, Lock())
    # Coalesce same-point requests, without blocking requests for other points.
    with point_lock:
        now, clock = _now(), time.monotonic()
        with _CACHE_LOCK:
            entry = _CACHE.get(key)
            if _usable_cache(entry, now, clock):
                result = deepcopy(entry['result']); result['cached'] = True
                return result
            _CACHE.pop(key, None)
        payload = _read_payload(point)
        retrieved = _now()
        days, grid_point = _validated_days(payload, point, retrieved.date())
        result = {'schema_version': 1, 'available': True, 'provider': 'Open-Meteo',
                  'source_url': 'https://open-meteo.com/', 'licence_url': 'https://open-meteo.com/en/licence',
                  'pricing_url': 'https://open-meteo.com/en/pricing', 'attribution': 'Weather data by Open-Meteo.com',
                  'point': dict(point), 'point_type': 'published_attraction_map_reference_not_ASOS_station',
                  'forecast_grid_point': grid_point, 'retrieved_at': retrieved.isoformat(timespec='seconds'),
                  'forecast_period': [days[0]['date'], days[-1]['date']], 'days': days,
                  'units': {'temperature': '°C', 'precipitation': 'mm', 'wind_speed': 'm/s'},
                  'current_forecast': True, 'flower_prediction': False, 'cached': False,
                  'personal_location_used': False, 'locally_trained_forecast_model': False,
                  'usage': 'noncommercial_open_access',
                  'limitations': ['선택한 공개 지도 기준점 주변의 외부 격자 예보입니다. 기상청 관측소 관측값이나 관광지 현장 측정값이 아닙니다.',
                                  '꽃의 개화·만개·현재 꽃 상태를 예측하지 않습니다. 과거 축제 일정과 현재 예보를 구분해 확인하세요.',
                                  '예보는 수집 시점 이후 바뀔 수 있습니다. 7일 범위 밖의 여행 날씨·야외 안전·운항을 보장하지 않습니다.',
                                  '개인 GPS 대신 목록에서 선택한 공개 관광지 좌표만 날씨 제공자에게 보냅니다.']}
        with _CACHE_LOCK:
            if len(_CACHE) >= 10:
                oldest = min(_CACHE, key=lambda k: _CACHE[k]['clock']); _CACHE.pop(oldest, None)
            _CACHE[key] = {'clock': time.monotonic(), 'retrieved_date': retrieved.date(), 'result': deepcopy(result)}
        return result
