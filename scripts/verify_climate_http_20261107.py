"""Read-only loopback HTTP checks for the source-pinned historical climate ML page."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jeju_agent.climate_guide import climate_reference, climate_status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8765')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    parsed = urlsplit(args.base)
    if not (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and
            parsed.path in ('', '/') and not parsed.query and not parsed.fragment and
            parsed.username is None and parsed.password is None):
        parser.error('--base must be a loopback http://127.0.0.1:PORT URL without a path or credentials')
    checks = []

    def get(path, expected_status=200):
        started = time.perf_counter()
        try:
            with urlopen(args.base.rstrip('/') + path, timeout=30) as response:
                code, raw = response.status, response.read()
        except HTTPError as error:
            code, raw = error.code, error.read()
        assert code == expected_status, (path, code, expected_status)
        checks.append({'path': path, 'status': code,
                       'milliseconds': round((time.perf_counter()-started)*1000, 3)})
        return raw

    for endpoint, relative in [('climate', 'index.html'), ('climate-guide.js', 'climate-guide.js'),
                               ('climate-guide.css', 'climate-guide.css')]:
        payload = get('/' + endpoint)
        assert payload == (ROOT / 'ui' / relative).read_bytes(), endpoint

    status = json.loads(get('/api/climate-status'))
    assert status == climate_status(ROOT)
    assert status['reference_period'] == ['2000-01-01', '2021-10-31']
    assert status['source']['id'] == 877 and status['source']['raw_rows'] == 31900
    assert status['source']['original_producer'] == '기상청'
    assert status['source']['hub_publisher'] == '고성빈'
    assert status['current_forecast'] is False and status['rainfall_available'] is False
    assert status['llm_used'] is False and status['ml_applied'] is True
    assert status['model']['test_rows'] == 4140 and status['model']['accuracy_improvement_claimed'] is False
    asset_paths = ['models_climate/config.json']
    config = json.loads((ROOT / asset_paths[0]).read_text(encoding='utf-8'))
    asset_paths += [v['path'] for v in config['assets'].values()] + [v['path'] for v in config['source_files']]
    watched = [ROOT / relative for relative in asset_paths]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}

    # Non-15th request proves day propagation; leap day exercises the fixed annual calendar.
    for station in ['jeju', 'gosan', 'seongsan', 'seogwipo']:
        for month, day in [(4, 27), (2, 29)]:
            path = '/api/climate-reference?' + urlencode({'month': month, 'day': day, 'station': station})
            actual = json.loads(get(path))
            assert actual == climate_reference(ROOT, month, day, station)
            assert actual['requested'] == {'month': month, 'day': day, 'station': station}
            assert len(actual['estimates']) == 4 and len(actual['seasonality']) == 12
            assert actual['selected']['day'] == day and actual['selected']['station'] == station
            assert [(r['month'], r['day']) for r in actual['seasonality']] == [(m, 15) for m in range(1, 13)]
    default = json.loads(get('/api/climate-reference?month=4&day=15'))
    assert default == climate_reference(ROOT, 4, 15, 'jeju')

    bad_reference_queries = [
        '', 'month=4', 'day=15', 'month=0&day=1', 'month=13&day=1', 'month=4&day=0',
        'month=4&day=31', 'month=2&day=30', 'month=1&day=32', 'month=4.0&day=15',
        'month=true&day=15', 'month=&day=15', 'month=4&day=',
        'month=4&day=15&station=unknown', 'month=4&day=15&station=',
        'month=4&day=15&station=Jeju', 'month=4&day=15&year=2026',
        'month=4&day=15&unknown=x', 'month=4&month=5&day=15',
        'month=4&day=15&day=16', 'month=4&day=15&station=jeju&station=gosan',
        'month=4&day=15&lat=33.5&lon=126.5', 'month=4&day=15&station=jeju&station=',
    ]
    for query in bad_reference_queries:
        payload = json.loads(get('/api/climate-reference' + ('?' + query if query else ''), 400))
        assert isinstance(payload.get('error'), str) and payload['error']
        assert 'selected' not in payload and 'estimates' not in payload
    for query in ['year=2026', 'month=4', 'unknown=', 'station=jeju&station=gosan']:
        assert json.loads(get('/api/climate-status?' + query, 400)).get('error')
    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    assert after == before
    report = {'pass': True, 'base': args.base, 'requests': len(checks), 'checks': checks,
              'runtime': 'offline_stdlib_cpu', 'reference_period': status['reference_period'],
              'station_count': 4, 'historical_reference_only': True, 'real_device_gps_used': False,
              'all_outputs_equal_source_pinned_python': True, 'all_assets_unchanged': True,
              'asset_sha256': before, 'timings_are_developer_pc_only': True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('checks', 'asset_sha256')}, ensure_ascii=True))


if __name__ == '__main__':
    main()
