"""Bounded owned-loopback GPU-residency load test. No external calls or GPS."""
import argparse,ctypes,hashlib,json,math,os,statistics,subprocess,threading,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
from memory_probe import Probe
BASE=Path(__file__).resolve().parent
ROOT=Path(os.environ["JEJU_CAPACITY_PROJECT_ROOT"]).resolve()
OWNER=json.loads((BASE/'results'/'server_owner.json').read_text(encoding='utf-8'))
URL='http://127.0.0.1:'+str(OWNER['port'])
PID=OWNER['pid']
QUERY_FILE=ROOT/'docs'/'GPU모델실험_20261107'/'평가'/'dev_queries.json'
CASES=[v for v in json.loads(QUERY_FILE.read_text(encoding='utf-8'))['cases'] if v['kind']=='supported'][:6]
LONG_QUERY=('제주 숲 해안 자연 산책 박물관 역사 화산 오름 바다 전통 마을 '*5)[:160]
DAY=dict(start_lat=33.506,start_lon=126.492,end_lat=33.506,end_lon=126.492,origin_confirmed=True,origin_source='landmark',origin_label='제주공항',date=datetime.now(timezone(timedelta(hours=9))).date().isoformat(),transport='car',start_minute=540,end_minute=1080,budget_krw=100000,max_stops=3)
LOCAL=threading.local()
def opener():
    if not hasattr(LOCAL,'opener'):LOCAL.opener=build_opener(ProxyHandler({}))
    return LOCAL.opener
def fetch(path,body=None,timeout=30):
    data=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
    req=Request(URL+path,data=data,headers={'Content-Type':'application/json','Origin':URL,'Accept':'application/json'})
    with opener().open(req,timeout=timeout) as response:return response.status,json.load(response)
def status():
    code,data=fetch('/api/compute-status')
    assert code==200 and data['server_process_id']==PID and data['semantic']['gpu_ready'] and data['semantic']['gpu_resident'] and data['semantic']['dml_kernel_events']>0
    return data
def case_sem(i):return ('semantic','/api/semantic-guide-search',{'query':CASES[i%6]['query']},'semantic')
def workload(kind,i):
    if kind=='semantic_short':return case_sem(i)
    if kind=='semantic_long':return ('semantic_long','/api/semantic-guide-search',{'query':LONG_QUERY},'long')
    if kind=='route_stress':return ('auto_route8','/api/agent/plan',dict(DAY,query='',region='all',max_stops=8,start_minute=0,end_minute=1440,budget_krw=10000000),'auto_route8')
    mixed=[
        case_sem(i),case_sem(i+1),
        ('1048','/api/observed-reference?audience=resident&month=6',None,'1048'),
        ('1047','/api/data-guide?kind=dining&month=6',None,'1047'),
        ('guide','/api/guide-search',{'query':'성산일출봉'},'guide'),
        ('climate','/api/climate-reference?month=4&day=15&station=jeju',None,'climate'),
        ('auto_route','/api/agent/plan',dict(DAY,query='',region='north'),'auto_route'),
        ('rule_chat','/api/chat',{'message':'성산일출봉 안내'},'rule_chat')]
    return mixed[i%len(mixed)]
def valid(kind,data):
    # Empty results are an intentional score/scope refusal, not an HTTP failure.
    # GPU execution is separately verified from counter deltas; relevance is not measured here.
    if kind=='semantic':return isinstance(data,list) and all(isinstance(x,dict) and x.get('id') and x.get('name') for x in data)
    if kind=='long':return isinstance(data,list)  # Scope rules may correctly reject this composite question.
    if kind=='1048':return isinstance(data,dict) and bool(data.get('categories'))
    if kind=='1047':return isinstance(data,dict) and bool(data.get('rows'))
    if kind=='guide':return isinstance(data,list) and bool(data) and data[0].get('name')=='성산일출봉'
    if kind=='climate':return data.get('selected',{}).get('available') is True and len(data.get('seasonality',[]))==12
    if kind in ['auto_route','auto_route8']:return data.get('status')=='ok' and 1<=len(data.get('stops',[]))<=(8 if kind=='auto_route8' else 3)
    if kind=='rule_chat':return isinstance(data.get('reply'),str) and data.get('llm_used') is False and data.get('location_used') is False
    return False
def request(case,barrier=None):
    name,path,body,kind=case
    if barrier:barrier.wait(timeout=60)
    start=time.perf_counter();start_ns=time.time_ns()
    try:
        code,data=fetch(path,body)
        okay=code==200 and valid(kind,data)
        error=None if okay else 'response_validation_failed'
        shape={'length':len(data) if isinstance(data,list) else None,'keys':sorted(data) if isinstance(data,dict) else None,'stop_count':len(data.get('stops',[])) if kind in ['auto_route','auto_route8'] and isinstance(data,dict) else None}
    except HTTPError as e:
        code=e.code;error='HTTP_'+str(code);okay=False;shape={};e.close()
    except Exception as e:
        code=None;error=type(e).__name__+': '+str(e)[:180];okay=False;shape={}
    return {'case':name,'path':path,'started_ns':start_ns,'ended_ns':time.time_ns(),'ms':(time.perf_counter()-start)*1000,'pass':okay,'status':code,'error':error,'response_shape':shape}
def summarize(rows,wall):
    values=sorted(r['ms'] for r in rows)
    return {'requests':len(rows),'successes':sum(r['pass'] for r in rows),'errors':sum(not r['pass'] for r in rows),'p50_ms':statistics.median(values),'p95_ms':values[math.ceil(.95*len(values))-1],'max_ms':max(values),'wall_seconds':wall,'completed_requests_per_second':len(rows)/wall,'percentile':'nearest rank ceil(.95*N)','status_counts':{str(c):sum(r['status']==c for r in rows) for c in {r['status'] for r in rows}}}
def global_gpu():
    try:
        p=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        return {'scope':'whole_gpu_all_processes_not_service_only','raw':p.stdout.strip(),'success':p.returncode==0}
    except Exception as e:return {'error':str(e)}
class Monitor:
    def __init__(self,label):
        self.label=label;self.probe=Probe(PID);self.samples=[];self.done=threading.Event();self.error=None;self.limit=None
        self.worker=threading.Thread(target=self.loop,daemon=True)
    def loop(self):
        while not self.done.is_set():
            try:
                s=self.probe.sample();self.samples.append(s)
                if s['working_set_bytes']>6*1024**3:self.limit='service_ram_above_6GiB'
                if s.get('dedicated_bytes') is not None and s['dedicated_bytes']>2*1024**3:self.limit='service_dedicated_vram_above_2GiB'
                if s['system_ram_available_bytes']<8*1024**3:self.limit='system_free_ram_below_8GiB'
            except Exception as e:self.error=str(e);break
            self.done.wait(.1)
    def start(self):self.worker.start();return self
    def finish(self):
        self.done.set();self.worker.join(timeout=5)
        self.samples.append(self.probe.sample());self.probe.close()
        fields=['working_set_bytes','private_commit_bytes','lifetime_peak_working_set_bytes','dedicated_bytes','shared_gpu_ram_bytes']
        peaks={f:max((s[f] for s in self.samples if s.get(f) is not None),default=None) for f in fields}
        return {'interval_requested_seconds':.1,'samples':self.samples,'max_sampled':peaks,'first':self.samples[0],'last':self.samples[-1],'counter_errors':[s['gpu_counter_errors'] for s in self.samples if s.get('gpu_counter_errors')],'counter_observed_samples':sum(bool(s.get('gpu_process_counter_observed')) for s in self.samples),'error':self.error,'safety_limit':self.limit,'definition':'RAM WorkingSet resident physical; PrivateCommit virtual commitment; GPU Dedicated and Shared separate; sampled maxima can miss sub-sample transients; lifetime peak can predate this phase.'}
def stage(kind,workers,minimum=64,waves=None,label_suffix=''):
    before=status();gpu_before=global_gpu();label=f'{kind}_c{workers}{label_suffix}'
    monitor=Monitor(label).start();rows=[];started_ns=time.time_ns();start=time.perf_counter()
    n_waves=waves or max(4,math.ceil(minimum/workers))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for wave in range(n_waves):
                if monitor.limit:break
                gate=threading.Barrier(workers+1)
                jobs=[pool.submit(request,workload(kind,wave*workers+j),gate) for j in range(workers)]
                gate.wait(timeout=60);rows.extend(job.result(timeout=40) for job in jobs)
    finally:measure=monitor.finish()
    wall=time.perf_counter()-start;ended_ns=time.time_ns();after=status()
    out={'label':label,'kind':kind,'concurrency':workers,'waves':n_waves,'started_ns':started_ns,'ended_ns':ended_ns,'benchmark':summarize(rows,wall),'memory':measure,'status_before':before,'status_after':after,'gpu_before':gpu_before,'gpu_after':global_gpu(),'raw_requests':rows,'gpu_success_delta':after['semantic']['successful_queries']-before['semantic']['successful_queries'],'cpu_long_fallback_delta':after['semantic']['cpu_long_query_fallbacks']-before['semantic']['cpu_long_query_fallbacks']}
    out['pass']=out['benchmark']['errors']==0 and not measure['error'] and not measure['safety_limit'] and not measure['counter_errors'] and measure['counter_observed_samples']>0
    out['interactive_threshold_p95_2s']=out['pass'] and out['benchmark']['p95_ms']<=2000
    out['general_threshold_p95_5s']=out['pass'] and out['benchmark']['p95_ms']<=5000
    if kind=='semantic_short':out['all_short_requests_gpu_verified']=out['gpu_success_delta']==out['benchmark']['successes'] and out['cpu_long_fallback_delta']==0;out['pass']=out['pass'] and out['all_short_requests_gpu_verified']
    (BASE/'results'/(label+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    small={'label':label,'pass':out['pass'],**out['benchmark'],'memory_mib':{k:round(v/1024**2,2) if v is not None else None for k,v in measure['max_sampled'].items()},'gpu_success_delta':out['gpu_success_delta'],'cpu_long_fallback_delta':out['cpu_long_fallback_delta']}
    print(json.dumps(small,ensure_ascii=True),flush=True)
    return out
def warmup():
    checks=[]
    for i in range(6):
        b=status();row=request(case_sem(i));a=status()
        assert row['pass'] and a['semantic']['successful_queries']>b['semantic']['successful_queries'] and a['semantic']['cpu_long_query_fallbacks']==b['semantic']['cpu_long_query_fallbacks'],{'request':row,'before':b['semantic'],'after':a['semantic']}
        checks.append(dict(row,last_gpu_token_count=a['semantic'].get('last_query_token_count')))
    short_state=status()
    for i in range(8):
        row=request(workload('mixed',i));checks.append(row);assert row['pass'],row
    final=status()
    (BASE/'results'/'warmup.json').write_text(json.dumps({'pass':True,'checks':checks,'short_only_state':short_state,'fully_warm_state':final},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'warmup_pass':True,'pid':PID,'road':final['road'],'samples':len(checks)},ensure_ascii=True),flush=True)
def long_warm():
    b=status();r=request(workload('semantic_long',0));a=status()
    assert r['pass'] and a['semantic']['cpu_long_query_fallbacks']>b['semantic']['cpu_long_query_fallbacks'] and a['semantic']['last_query_token_count']>64 and a['semantic']['gpu_resident']
    result={'pass':True,'request':r,'before':b,'after':a,'query':LONG_QUERY}
    (BASE/'results'/'long_fallback_warmup.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'long_fallback_warmup':True,'tokens':a['semantic']['last_query_token_count']},ensure_ascii=True),flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('--part',choices=['warmup','short','mixed','long','soak'],required=True);a=p.parse_args()
    if a.part=='warmup':warmup()
    elif a.part in ['short','mixed']:
        for n in [1,2,4,8,12,16,24,32]:
            r=stage('semantic_short' if a.part=='short' else 'mixed',n)
            if r['memory']['safety_limit']:break
    elif a.part=='long':
        long_warm()
        for n in [1,4,8,16]:stage('semantic_long',n,minimum=32)
        # Return to GPU short requests while both CPU/GPU sessions remain resident.
        stage('semantic_short',8,minimum=64,label_suffix='_after_cpu_fallback')
    else:
        # Consecutive waves of up to eight requests; each wave completes before next.
        stage('mixed',8,waves=64,label_suffix='_soak512')
    print(json.dumps({'part_finished':a.part},ensure_ascii=True),flush=True)
if __name__=='__main__':main()
