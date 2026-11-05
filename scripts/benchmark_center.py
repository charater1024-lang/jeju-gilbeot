"""Offline, CPU-only benchmark of this process; not a center-hardware claim."""
import ctypes
import datetime as dt
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from jeju_agent.insights import food_insight,mobility_insight
from jeju_agent.catalog_store import place_search
from jeju_agent.reference import catalogue,plan_destinations
from jeju_agent.place_trust import place_trust
from jeju_agent.tourism_access import approved_places

def memory():
    if sys.platform!='win32':return {'process_working_set_bytes':None,'peak_working_set_bytes':None}
    from ctypes import wintypes
    class COUNTERS(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in ['peak','current','poolpeak','pool','nonpagedpeak','nonpaged','pagefile','pagefilepeak']]
    p=COUNTERS();p.cb=ctypes.sizeof(p)
    k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=wintypes.HANDLE
    fn=ctypes.WinDLL('psapi',use_last_error=True).GetProcessMemoryInfo
    fn.argtypes=[wintypes.HANDLE,ctypes.POINTER(COUNTERS),wintypes.DWORD];fn.restype=wintypes.BOOL
    if not fn(k.GetCurrentProcess(),ctypes.byref(p),p.cb):return {'process_working_set_bytes':None,'peak_working_set_bytes':None}
    return {'process_working_set_bytes':p.current,'peak_working_set_bytes':p.peak}

def timed(fn,n):
    fn();times=[]
    for _ in range(n):
        start=time.perf_counter();fn();times.append((time.perf_counter()-start)*1000)
    ordered=sorted(times)
    return {'iterations':n,'p50_ms':round(statistics.median(times),3),'p95_ms':round(ordered[min(n-1,int(n*.95))],3),'max_ms':round(max(times),3)}

def main():
    today=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    req={'date':today,'transport':'car','max_stops':8,'start_minute':0,'end_minute':1440,
         'budget_krw':10000000,'start_lat':33.506,'start_lon':126.492,
         'end_lat':33.506,'end_lon':126.492,'origin_confirmed':True,
         'origin_source':'landmark','origin_label':'공개 기준점 제주공항'}
    ids=[p['id'] for p in approved_places(ROOT) if place_trust(ROOT,p)['automatic_eligible']][:8]
    if len(ids)!=8:raise ValueError('현재 출처 정책을 통과한 공개 관광지 8곳이 필요합니다.')
    req['destination_ids']=ids
    def schedule():
        result=plan_destinations(ROOT,req)
        if result['status']!='ok' or len(result['stops'])!=8:
            raise ValueError('정상 8곳 일정이 아니므로 일정 응답시간으로 기록하지 않습니다.')
        return result
    reports={
      'audience_and_food_examples':timed(lambda:food_insight(ROOT,'resident',10,'north'),40),
      'historical_mobility':timed(lambda:mobility_insight(ROOT,today,'daytime'),100),
      'catalogue_query':timed(lambda:place_search(ROOT,'함덕'),100),
      'itinerary_8_places':timed(schedule,5),
    }
    model_bytes=sum(p.stat().st_size for directory in ['models_audience','models_mobility'] for p in (ROOT/directory).glob('*model.json'))
    result={'checked_on':today,'python':platform.python_version(),'platform':platform.platform(),'requires_gpu':False,'network_calls':0,
       'benchmark_scope':'직접 함수 호출의 warm 실행. HTTP·브라우저 메모리나 센터와 같은 하드웨어 측정이 아닙니다.',
       'results':reports,'memory':memory(),'inference_model_bytes':model_bytes,'catalogue_sqlite_bytes':(ROOT/'data_reference'/'catalog.sqlite').stat().st_size,
       'limits':{'http_workers':8,'max_itinerary_places':8,'request_body_bytes':32768},
       'notes':['원본 498MB 버스 CSV는 서비스 요청과 추론에서 로드하지 않습니다.','새 데이터 학습·검색 색인 생성은 별도 관리 작업입니다.','센터 최소사양 장비에서 별도 설치·응답 검증이 필요합니다.']}
    (ROOT/'examples'/'center_runtime_benchmark_v16.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
