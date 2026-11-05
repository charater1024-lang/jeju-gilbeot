"""Integration checks using public Jeju landmarks only, never device GPS."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
from http_smoke_v5 import Client, artifact_hashes


def smoke(root,base,report_path):
    from jeju_agent.tourism_access import approved_places
    from jeju_agent.place_trust import place_trust
    root=Path(root);before=artifact_hashes(root);client=Client(base)
    approved={p['id']:p for p in approved_places(root)}
    cases=[]
    def request(lat,lon,region='all',label='공개 기준 장소'):
        return {'date':'2026-11-01','transport':'car','start_lat':lat,'start_lon':lon,
                'end_lat':lat,'end_lon':lon,'start_minute':540,'end_minute':1080,
                'budget_krw':100000,'max_stops':3,'query':'','region':region,
                'origin_confirmed':True,'origin_source':'landmark','origin_label':label}
    def verify(name,body,result):
        assert result['data_mode']=='reference'
        assert result['selection_mode']=='automatic'
        assert result['status']=='ok',(name,result.get('message'))
        ids=[p['poi_id'] for p in result['stops']]
        assert ids and len(ids)<=body['max_stops'] and len(ids)==len(set(ids))
        assert not set(ids)&set(body.get('excluded_ids',[]))
        assert all(ident in approved and place_trust(root,approved[ident],purpose='automatic')['automatic_eligible'] for ident in ids)
        assert result['totals']['end_arrival_minute']<=body['end_minute']
        assert result['totals']['travel_cost_krw']<=body['budget_krw']
        assert result['totals']['budget_verified'] is False
        assert all(p.get('predicted_visits') is None for p in result['stops'])
        assert len(result.get('trace',[]))>=4 and result.get('selected_place_evidence')
        trace_text=json.dumps(result['trace'],ensure_ascii=False)
        assert str(body['start_lat']) not in trace_text and str(body['start_lon']) not in trace_text
        assert result.get('privacy',{}).get('precise_location_persisted') is False
        cases.append({'name':name,'pass':True,'status':result['status'],'places':[approved[i]['name'] for i in ids],
                      'place_ids':ids,'duration_minutes':result['totals']['duration_minutes'],
                      'travel_cost_krw':result['totals']['travel_cost_krw'],
                      'exclusion_count':len(result.get('exclusions',[]))})
        return ids
    selected=None;first=None
    for name,lat,lon,region,label in [
        ('north_airport',33.506,126.492,'north','제주공항 공개 기준'),
        ('west_coast',33.395112,126.2402796,'west','협재해수욕장 공개 기준'),
        ('south',33.2467016,126.554642,'south','천지연폭포 공개 기준'),
        ('east',33.424041,126.9307306,'east','섭지코지 공개 기준')]:
        body=request(lat,lon,region,label)
        ids=verify(name,body,client.request('/api/agent/plan',body))
        if selected is None:selected=ids;first=body
    altered=dict(first,excluded_ids=selected)
    replacement=client.request('/api/agent/plan',altered)
    if replacement['status']=='ok':verify('exclude_and_replan',altered,replacement)
    else:
        assert replacement['status']=='infeasible' and replacement['message']
        assert replacement.get('stops',[])==[]
        cases.append({'name':'exclude_and_replan','pass':True,'status':'infeasible'})
    base_body=request(33.506,126.492)
    for name,change in [('unconfirmed',{'origin_confirmed':False}),('outside_jeju',{'start_lat':37.5}),
                        ('nonfinite',{'start_lat':float('nan')}),('missing_explicit_start',{'start_lat':None}),
                        ('invalid_max_stops',{'max_stops':9})]:
        assert client.request('/api/agent/plan',dict(base_body,**change),status=400).get('error')
        cases.append({'name':name,'pass':True,'status':400})
    for name,change in [('too_little_time',{'end_minute':545}),('no_travel_budget',{'budget_krw':0}),
                        ('no_matching_place',{'query':'존재하지않는검색주제99999'})]:
        result=client.request('/api/agent/plan',dict(base_body,**change))
        assert result['status']=='infeasible' and not result.get('stops') and result.get('message'),(name,result)
        cases.append({'name':name,'pass':True,'status':result['status']})
    unsupported=client.request('/api/agent/plan',dict(base_body,transport='bus'))
    assert unsupported['status']=='unsupported' and not unsupported.get('stops')
    assert client.request('/api/recommend',{},status=410)['code']=='synthetic_service_removed'
    after=artifact_hashes(root);assert before==after
    result={'pass':True,'date_kst':'2026-11-01','cases':cases,'api_requests':len(client.exchanges),
            'source_models_and_databases_unchanged':True,'real_gps_requested':False,
            'location_fixture':'public landmarks; no user device location was used',
            'exchanges':client.exchanges,'model_hashes':after}
    Path(report_path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--report',default='docs/추천코스_v15/API검증.json');a=p.parse_args()
    result=smoke(a.root,a.base_url,a.report)
    print(json.dumps({'pass':result['pass'],'cases':len(result['cases']),'requests':result['api_requests']},ensure_ascii=False))
