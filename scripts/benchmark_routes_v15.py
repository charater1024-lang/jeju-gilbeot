"""Verify bounded automatic routes on fixed public Jeju reference coordinates."""
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
from jeju_agent.orchestrator import run_agent


def hashes():
    paths=list((ROOT/'data_reference').glob('*.sqlite'))
    for folder in ['models_audience','models_mobility','models_tourism','models_discovery']:
        paths.extend((ROOT/folder).glob('*.json'))
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def body(region,lat,lon,**changes):
    request={'date':'2026-11-01','transport':'car','start_lat':lat,'start_lon':lon,
             'end_lat':lat,'end_lon':lon,'start_minute':540,'end_minute':1080,
             'budget_krw':80000,'max_stops':3,'query':'','region':region,
             'origin_confirmed':True,'origin_source':'landmark',
             'origin_label':'공개 장소 검증 기준점','include_geometry':False}
    request.update(changes)
    return request


def main():
    before=hashes();reports=[];elapsed=[]
    fixtures=[('공항 부근','north',33.506,126.492),('협재 부근','west',33.394,126.239),
              ('천지연 부근','south',33.247,126.554),('섭지코지 부근','east',33.425,126.929)]
    with patch('socket.socket',side_effect=AssertionError('No network is allowed in offline route verification')):
        for name,region,lat,lon in fixtures:
            samples=[];request=body(region,lat,lon)
            for _ in range(5):
                started=time.perf_counter();result=run_agent(ROOT,request)
                samples.append((time.perf_counter()-started)*1000)
                assert result['status']=='ok' and 1<=len(result['stops'])<=3
                assert result['totals']['end_arrival_minute']<=request['end_minute']
                assert result['totals']['travel_cost_krw']<=request['budget_krw']
                assert len({p['poi_id'] for p in result['stops']})==len(result['stops'])
                assert all(p['trust']['eligible'] and p['trust']['automatic_eligible'] for p in result['stops'])
            elapsed.extend(samples)
            removed=result['stops'][0]['poi_id']
            replacement=run_agent(ROOT,dict(request,excluded_ids=[removed]))
            assert replacement['status']=='ok' and removed not in [p['poi_id'] for p in replacement['stops']]
            reports.append({'fixture':name,'region':region,'public_reference':{'latitude':lat,'longitude':lon},
                'status':result['status'],'stops':[{'id':p['poi_id'],'name':p['name']} for p in result['stops']],
                'return_minute':result['totals']['end_arrival_minute'],'estimated_travel_cost_krw':result['totals']['travel_cost_krw'],
                'excluded_then_replanned':True,'removed_id':removed,
                'p50_ms':round(statistics.median(samples),3),'max_ms':round(max(samples),3)})
        failures=[]
        for label,changes in [('5분',{'end_minute':545}),('자동차 이동비0원',{'budget_krw':0}),('검색결과없음',{'query':'zxqv987654'})]:
            result=run_agent(ROOT,body('north',33.506,126.492,**changes))
            assert result['status']=='infeasible' and not result['stops'] and result['suggestions']
            failures.append({'fixture':label,'status':result['status'],'explained':True})
        geometry=run_agent(ROOT,body('north',33.506,126.492,include_geometry=True))
        assert geometry['status']=='ok'
        assert geometry['route_geometry'] and geometry['route_geometry']['kind'] in {'road','straight_line'}
        assert geometry['route_geometry']['contains_private_location'] is True
    after=hashes();assert before==after
    result={'pass':True,'checked_date_kst':'2026-11-01','service_version':15,
        'scope':'Fixed public-place coordinates, direct function execution on this development PC; not a center-hardware or actual trip-accuracy claim.',
        'real_device_gps_used':False,'external_network_calls':0,'function_calls':28,
        'real_place_scenarios':reports,'infeasible_scenarios':failures,
        'road_reference':{'kind':geometry['route_geometry']['kind'],'contains_private_location':True,
                          'is_navigation_or_realtime_traffic':False},
        'model_and_database_hashes_unchanged':True,'artifact_sha256':after,
        'selection_latency_ms':{'iterations':len(elapsed),'p50':round(statistics.median(elapsed),3),
                                'p95':round(sorted(elapsed)[max(0,int(len(elapsed)*.95)-1)],3),'max':round(max(elapsed),3)},
        'warnings':['Planning times and movement costs are assumptions, not observed trip times or a full travel budget.',
                    'Current opening, reservation, fees and actual access points remain previsit checks.']}
    path=ROOT/'docs/추천코스_v15/경로검증.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='artifact_sha256'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
