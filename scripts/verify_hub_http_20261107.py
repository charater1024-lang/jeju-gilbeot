"""Read-only loopback integration checks for installed historical Hub insights."""
import argparse,hashlib,json,sys,time
from pathlib import Path
from urllib.parse import urlencode,urlsplit
from urllib.request import urlopen
from urllib.error import HTTPError
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from jeju_agent.hub_insights import visitor_patterns

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://127.0.0.1:8765');parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    u=urlsplit(a.base);assert u.scheme=='http' and u.hostname=='127.0.0.1' and u.path in ('','/') and not u.query and not u.fragment
    checks=[]
    def get(path,status=200):
        started=time.perf_counter()
        try:
            with urlopen(a.base.rstrip('/')+path,timeout=30) as response:code,raw=response.status,response.read()
        except HTTPError as exc:code,raw=exc.code,exc.read()
        assert code==status,(path,code,status)
        checks.append({'path':path,'status':code,'milliseconds':round((time.perf_counter()-started)*1000,2)})
        return raw
    for name in ['insights','hub-insights.js','hub-insights.css']:
        raw=get('/'+name);local=ROOT/'ui'/('index.html' if name=='insights' else name)
        assert hashlib.sha256(raw).digest()==hashlib.sha256(local.read_bytes()).digest()
    visitors=visitor_patterns(ROOT)
    for place in visitors['places']:
        for audience in ['domestic','foreign']:
            data=json.loads(get('/api/hub-visitor-patterns?'+urlencode({'place':place['key'],'audience':audience})))
            assert data==visitor_patterns(ROOT,place['key'],audience)
            assert data['available'] and not data['ml_applied'] and not data['selected']['forecast']['available']
            assert len(data['selected']['monthly_series'])==192 and len(data['selected']['seasonality'])==12
    for suffix in ['', '?region=unknown', '?region=..%2F..%2F']:
        data=json.loads(get('/api/hub-regional-patterns'+suffix,410))
        assert data['code']=='regional_consumption_retired' and 'selected' not in data
    for path in ['/api/hub-visitor-patterns?audience=all','/api/hub-visitor-patterns?place=unknown']:
        assert 'error' in json.loads(get(path,400))
    report={'pass':True,'base':a.base,'requests':len(checks),'checks':checks,'visitor_places':6,'regional_profiles':0,'regional_endpoint_retired':True,'runtime':'stdlib_cpu','real_device_gps_used':False,'all_outputs_equal_source_pinned_python':True,'timings_are_developer_pc_only':True}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=True))
if __name__=='__main__':main()
