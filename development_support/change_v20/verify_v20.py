"""Exercise v20 through bundled Python, Node and a loopback HTTP server."""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs/모델다양화_v20'
PYTHON = ROOT / 'runtime/python.exe'
TEST_DATE = '2026-11-06'
EXAMPLES = ('examples/itinerary_export_v4.json', 'examples/location_ui_v7.json')
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))


def read_json(relative):
    return json.loads((ROOT / relative).read_text('utf-8'))


def write_json(name, value):
    (DOCS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def full_regressions(node):
    command = [str(PYTHON), str(ROOT / 'dev.py'), 'test']
    if node:
        command.extend(('--node', node))
    saved = {name: (ROOT / name).read_bytes() for name in EXAMPLES}
    try:
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=600)
        (DOCS / '전체회귀검사.log').write_text(process.stdout + '\n' + process.stderr, 'utf-8')
        assert process.returncode == 0, process.stderr[-3500:] + process.stdout[-1000:]
        report = json.loads(process.stdout.strip().splitlines()[-1])
        assert report['python']['pass'] and report['ui']['status'] == 'completed' and report['ui']['pass']
        return report
    finally:
        for name, content in saved.items():
            if (ROOT / name).read_bytes() != content:
                (ROOT / name).write_bytes(content)


def preserved_serving_models():
    """Compare the three retained model families against their v19 file receipts."""
    prefixes = ('models_audience/', 'models_mobility/', 'models_dining/')
    records = [row for row in read_json('SERVICE_MANIFEST_v19.json')['files']
               if row['path'].startswith(prefixes)]
    assert all(any(row['path'].startswith(prefix) for row in records) for prefix in prefixes)
    for row in records:
        path = ROOT / row['path']
        with path.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == row['sha256'], row['path']
    return len(records)


def check_core_and_route(call):
    from jeju_agent.audience_model import predict_audience
    from jeju_agent.bus_v20 import get_bus_candidate
    from jeju_agent.dining_model import predict_dining
    from jeju_agent.mobility_model import predict_mobility
    from jeju_agent.model_runtime_v20 import active_route_demand
    from jeju_agent.route_demand import get_route_demand

    food = call('/api/insights/food?audience=resident&month=6&region=all')
    old_food = predict_audience(ROOT / 'models_audience/audience_model.json', 'resident', 6)
    assert all(food[key] == old_food[key] for key in ('categories', 'model', 'source_id', 'source_url'))
    mobility = call(f'/api/insights/mobility?date={TEST_DATE}&period=daytime')
    assert mobility == predict_mobility(ROOT / 'models_mobility/mobility_model.json', TEST_DATE, 'daytime')
    dining = call('/api/data-guide?kind=dining&month=6')
    old_dining = predict_dining(ROOT, month=6, limit=20)
    assert dining['model'] == old_dining['model']
    assert [row[:3] for row in dining['rows']] == [
        [item['category'], item['parent_category'], f"{item['predicted_share_percent']:,.1f}%"]
        for item in old_dining['items']
    ]
    assert any(row['value'] == '90.7%' and '1790/1974' in row['label'] for row in dining['metrics'])

    baseline = get_route_demand(ROOT, date=TEST_DATE, limit=12)
    active = active_route_demand(ROOT, date=TEST_DATE, limit=12)
    codes = [item['route_id'] for item in baseline['items']]
    candidate = get_bus_candidate(ROOT, '561', TEST_DATE, groups=codes)
    assert [item['route_id'] for item in active['items']] == codes
    assert active['runtime_llm'] is False and active['source'] == baseline['source']
    assert [item['prediction'] for item in active['items']] == [
        round(row['prediction'], 1) for row in candidate['predictions']
    ]
    assert any(a['prediction'] != b['prediction'] for a, b in zip(active['items'], baseline['items']))
    assert all(item['current_route_mapping_verified'] is False for item in active['items'])
    for key in ('evaluation_route_count', 'serving_route_count', 'evaluated_cell_coverage_percent',
                'all_test_observed_cells', 'evaluation_period'):
        assert active['metrics'][key] == baseline['metrics'][key], key
    tolerance = active['metrics']['within_20_percent']
    assert (tolerance['hits'], tolerance['denominator']) == (13535, 28092)
    assert active['metrics']['mae'] == candidate['metrics']['mae']

    route = call(f'/api/data-guide?kind=route&date={TEST_DATE}')
    assert [row[:2] for row in route['rows']] == [
        [item['route_id'], f"{item['prediction']:,.1f}명/일"] for item in active['items']
    ]
    assert any(row['value'] == '48.2%' and '13535/28092' in row['label'] for row in route['metrics'])
    assert any(row['value'] == '5.0명/일' and '평균오차' in row['label'] for row in route['metrics'])
    assert any('250' in note and '202' in note and '43.7%' in note for note in route['notes'])
    assert any('현재 운행 노선' in note for note in route['notes'])
    assistant = call('/api/assistant', {'message': f'{TEST_DATE} 노선별 하루 승차 수요 비교'})
    assert assistant['status'] == 'ok' and assistant['analysis']['rows'] == route['rows']
    assert assistant['analysis']['sources'] == route['sources']
    assert any('48.2%' in note and '13535/28092' in note for note in assistant['analysis']['notes'])


def check_tourism(call):
    from jeju_agent.tourism import search_tourism

    frozen = read_json('models_candidates_v20/retrieval/retrieval_metrics.json')['domains']['tourism']
    before = frozen['incumbent_service']['details']
    after = frozen['production_constrained_rerank']['details']
    assert len(before) == len(after) == 22
    changes = 0
    for original, selected in zip(before, after):
        body = {'query': original['query'], 'kind': 'attraction', 'limit': 12}
        legacy = search_tourism(ROOT, body)
        served = call('/api/tourism', body, label=original['query'])
        old_items, new_items = legacy['items'], served['items']
        assert [row['id'] for row in old_items[:5]] == original['returned_ids']
        assert [row['id'] for row in new_items[:5]] == selected['returned_ids']
        assert {row['id']: row for row in old_items} == {row['id']: row for row in new_items}
        assert old_items[5:] == new_items[5:]
        for key in ('total', 'next_cursor', 'next_offset', 'available_categories', 'applied_filters',
                    'warnings', 'attributions', 'privacy'):
            assert legacy[key] == served[key], (original['query'], key)
        changes += old_items != new_items
    assert changes > 0

    # Public airport coordinate exercises distance and radius without using GPS.
    for label, body in (
        ('blank query', {'query': '', 'limit': 12}),
        ('public coordinate and radius', {'query': '바다', 'limit': 12, 'radius_km': 30,
                                          'location': {'latitude': 33.5104, 'longitude': 126.4914}}),
        ('later page', {'query': '바다', 'limit': 12, 'offset': 5}),
        ('short page', {'query': '바다', 'limit': 4}),
    ):
        legacy = search_tourism(ROOT, body)
        served = call('/api/tourism', body, label=label)
        assert legacy == served, label
        if 'location' in body:
            assert served['items'] and served['radius_applied']
            assert all(0 <= item['distance_km'] <= 30 for item in served['items'])
    return {'authored_test_cases': len(after), 'changed_response_orders': changes,
            'scope': 'Frozen authored proxy cases reproduced through the API. No field accuracy claim.'}


def check_service(call):
    status = call('/api/status')
    assert status['service_version'] == 20 and status['runtime'] == 'offline_cpu'
    assert status['ready'] and status['synthetic_service_enabled'] is False
    ledger = call('/api/model-evaluation')
    assert ledger == read_json('data_reference/model_portfolio_v20.json')
    assert ledger['all_service_models_93_proven'] is False
    assert len({item['id'] for item in ledger['models']}) == 9
    assert all(item['field_accuracy_proven'] is False for item in ledger['models'])
    regressions = {item['source_id']: item for item in ledger['models'] if item['type'] == 'regression'}
    expected = {'1048': (252, 288), '1047': (1790, 1974), '512': (699, 847), '561': (13535, 28092)}
    assert {key: (item['metric']['hits'], item['metric']['total'])
            for key, item in regressions.items()} == expected
    check_core_and_route(call)
    tourism = check_tourism(call)
    for kind in ('walk', 'beach', 'accessible', 'amenity'):
        data = call('/api/data-guide?' + urlencode({'kind': kind}))
        assert data['rows'] and data['sources']
    call('/api/data-guide?kind=route&date=2026-02-31', expected=400)
    draft = call('/api/assistant', {'message': '제주공항에서 오전 10시에 차로 출발해서 3시간 안에 돌아오는 코스 짜줘.'})
    assert draft['status'] == 'needs_confirmation'
    plan = call('/api/assistant', {'action': 'confirm', 'state': draft['state'], 'origin_choice': 'candidate'})
    assert plan['status'] == 'ok' and plan['route']['stops']
    call('/api/recommend', {}, expected=410)
    about = call('/about')
    assert 'id="model-goal-report"' in about and 'model-evaluation.js' in about
    script = call('/model-evaluation.js')
    assert '/api/model-evaluation' in script
    return tourism


def http_regressions():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    opener = build_opener(ProxyHandler({}))
    checks = []

    def call(path, body=None, *, expected=200, label=None):
        data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
        req = Request(base + path, data=data, headers={'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=40) as response:
                status, payload = response.status, response.read()
        except HTTPError as exc:
            status, payload = exc.code, exc.read()
        assert status == expected, (path, label, status, payload[:300])
        checks.append({'method': req.get_method(), 'path': path, 'case': label, 'status': status})
        return json.loads(payload) if payload[:1] in (b'{', b'[') else payload.decode('utf-8')

    with (DOCS / '로컬서버.log').open('w', encoding='utf-8') as log:
        server = subprocess.Popen([str(PYTHON), str(ROOT / 'dev.py'), 'run', '--port', str(port)],
                                  cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            for _ in range(80):
                if server.poll() is not None:
                    raise RuntimeError(f'HTTP server exited with status {server.returncode}')
                try:
                    with opener.open(base + '/api/status', timeout=2):
                        break
                except (OSError, URLError):
                    time.sleep(0.25)
            else:
                raise RuntimeError('HTTP server startup timed out')
            tourism = check_service(call)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
    write_json('HTTP통합검사.json', {'pass': True, 'checks': checks, 'tourism': tourism})
    return len(checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', help='Optional Node executable. Otherwise use dev.py discovery.')
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    DOCS.mkdir(parents=True, exist_ok=True)
    report = full_regressions(args.node)
    print('Full regression passed', report['python'], flush=True)
    preserved = preserved_serving_models()
    http_checks = http_regressions()
    ui_checks = report['ui']['checks']
    summary = {
        'pass': True, 'service_version': 20, 'date_kst': TEST_DATE,
        'python_tests': report['python']['tests'],
        'ui_test_files': sum(not row['name'].startswith('syntax:') for row in ui_checks),
        'javascript_syntax_files': sum(row['name'].startswith('syntax:') for row in ui_checks),
        'http_checks': http_checks, 'retained_model_files_hash_verified': preserved,
        'legacy_examples_restored': True, 'actual_browser_visual_review': False,
        'center_hardware_review': False, 'runtime_llm': False, 'synthetic_service_enabled': False,
    }
    write_json('검증결과_v20.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
