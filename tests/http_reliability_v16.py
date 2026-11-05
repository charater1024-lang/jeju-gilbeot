"""Real-source local HTTP regression; fixed public origin, no device location."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from http_smoke_v5 import Client, artifact_hashes


def smoke(root, base, report_path):
    from jeju_agent.place_trust import load_policy
    from jeju_agent.tourism_access import approved_places
    root = Path(root)
    client = Client(base)
    before = artifact_hashes(root)
    policy = load_policy(root)
    names = {p['id']: p['name'] for p in approved_places(root)}
    checks = []

    def request(**updates):
        body = {'date':'2026-11-03','transport':'car',
                'start_lat':33.506,'start_lon':126.492,'end_lat':33.506,'end_lon':126.492,
                'start_minute':540,'end_minute':1200,'budget_krw':100000,'max_stops':3,
                'origin_confirmed':True,'origin_source':'landmark',
                'origin_label':'제주공항 공개 기준점','include_geometry':False}
        body.update(updates)
        return body

    status = client.request('/api/status')
    assert status['service_version'] == 16
    assert status['agent']['llm_used'] is False
    assert status['agent']['autonomous_tool_selection'] is False
    checks.append({'name':'service_scope_is_explicit','pass':True})
    normal = client.request('/api/plan-destinations', request(destination_ids=['osulloc']))
    assert normal['status'] == 'ok'
    assert normal['stops'][0]['trust']['automatic_eligible'] is True
    assert normal['selected_place_evidence'][0]['sources']
    assert normal['totals']['budget_verified'] is False
    checks.append({'name':'manual_approved_place_keeps_evidence','pass':True})

    for ident, rule in policy['automatic_exclusions'].items():
        result = client.request('/api/plan-destinations', request(destination_ids=[ident]))
        assert result['status'] == 'needs_review' and result['stops'] == []
        assert result['totals'] == {} and result['suggestions']
        assert names[ident] in result['message']
        denied = next(p for p in result['exclusions'] if p['id'] == ident)
        assert rule['code'] in [reason['code'] for reason in denied['reasons']]
        assert denied['trust']['sources'] and denied['trust']['policy_reviewed_at']
        checks.append({'name':'manual_recorded_exception','place':names[ident],
                       'pass':True,'status':result['status'],'reason':rule['code']})

    blocked = next(iter(policy['automatic_exclusions']))
    mixed = client.request('/api/plan-destinations', request(destination_ids=['osulloc', blocked]))
    assert mixed['status'] == 'needs_review' and mixed['stops'] == []
    checks.append({'name':'no_silent_drop_or_replacement','pass':True})

    for path in ['/api/plan-destinations','/api/agent/plan']:
        for label, changes, remove in [
            ('unconfirmed', {'origin_confirmed':False}, []),
            ('missing_source', {}, ['origin_source']),
            ('missing_coordinates', {}, ['start_lat','start_lon','end_lat','end_lon']),
            ('missing_return_point', {}, ['end_lon']),
            ('nonfinite', {'start_lat':float('nan')}, []),
            ('outside_jeju', {'start_lat':37.5}, []),
        ]:
            body = request(destination_ids=['osulloc'], **changes)
            for key in remove:
                body.pop(key)
            assert client.request(path, body, status=400).get('error')
            checks.append({'name':'explicit_origin_'+label,'endpoint':path,'pass':True,'status':400})

    for phrase in ['섭지코지 추천','제주목관아 추천해 주세요',
                   '협재해수욕장에 가고 싶어','오설록티뮤지엄을 추천해줘']:
        result = client.request('/api/agent/plan', request(query=phrase, max_stops=1))
        assert result['status'] == 'ok' and len(result['stops']) == 1
        assert result['stops'][0]['trust']['automatic_eligible'] is True
        checks.append({'name':'grounded_name_request','query':phrase,'pass':True,
                       'selected_name':result['stops'][0]['name']})
    for phrase in ['해변 빼고 박물관','섭지코지 제외하고 추천','협재해수욕장 말고',
                   '해변은 싫어','해변 아닌 곳','해변 안 가고 싶어']:
        result = client.request('/api/agent/plan', request(query=phrase))
        assert result['status'] == 'needs_clarification' and result['stops'] == []
        assert result['suggestions']
        checks.append({'name':'negative_intent_needs_clarification','query':phrase,'pass':True})

    assert artifact_hashes(root) == before
    report = {'pass':True,'date_kst':'2026-11-03','checks':checks,
              'api_requests':len(client.exchanges),'exchanges':client.exchanges,
              'source_models_and_databases_unchanged':True,
              'real_device_location_requested':False,'external_hosts_contacted':False,
              'meaning':'Functional regression using public-place fixtures; not field accuracy.'}
    Path(report_path).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--base-url', required=True)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--report', default='docs/개선_v16/API신뢰성.json')
    a = p.parse_args()
    result = smoke(a.root, a.base_url, a.report)
    print(json.dumps({'pass':result['pass'],'checks':len(result['checks']),
                      'api_requests':result['api_requests']},ensure_ascii=False))
