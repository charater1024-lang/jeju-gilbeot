"""Loopback read-only checks; live external weather is an explicit opt-in."""
import argparse,hashlib,json,sys,time
from pathlib import Path
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.dont_write_bytecode=True;ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from jeju_agent.flower_seasons import flower_status,flower_seasons

def main():
    p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:8765');p.add_argument('--output',type=Path,required=True);p.add_argument('--check-live-weather',action='store_true');a=p.parse_args()
    u=urlsplit(a.base);assert u.scheme=='http' and u.hostname=='127.0.0.1' and u.path in ('','/') and not u.query and not u.fragment
    checks=[]
    def request(path,status=200,body=None,origin=None):
        payload=None if body is None else json.dumps(body).encode();headers={'Content-Type':'application/json','Origin':origin or a.base}
        req=Request(a.base.rstrip('/')+path,data=payload,headers=headers);tick=time.perf_counter()
        try:
            with urlopen(req,timeout=20) as response:code,raw=response.status,response.read()
        except HTTPError as exc:code,raw=exc.code,exc.read()
        if status is not None:assert code==status,(path,code,status)
        checks.append({'path':path,'status':code,'milliseconds':round((time.perf_counter()-tick)*1000,2)});return code,raw
    for name in ['flowers','flower-guide.js','flower-guide.css']:
        _,raw=request('/'+name);local=ROOT/'ui'/('index.html' if name=='flowers' else name)
        assert hashlib.sha256(raw).digest()==hashlib.sha256(local.read_bytes()).digest()
    status=json.loads(request('/api/flower-status')[1]);assert status==flower_status(ROOT)
    assert not status['flower_prediction']['available'] and not status['flower_ml_trained']
    default=json.loads(request('/api/flower-seasons')[1]);assert default==flower_seasons(ROOT)
    for flower in status['flowers']:
        for pref in ['cool','mild','warm']:
            args={'flower':flower['id'],'preference':pref,'station':'seogwipo'}
            got=json.loads(request('/api/flower-seasons?'+urlencode(args))[1]);assert got==flower_seasons(ROOT,**args)
            assert len(got['month_comparisons'])==12 and got['temperature_ml_applied'] and not got['flower_prediction_available']
    for station in ['jeju','gosan','seongsan']:
        got=json.loads(request('/api/flower-seasons?'+urlencode({'station':station}))[1]);assert got==flower_seasons(ROOT,station=station)
    for suffix in ['flower=bad','flower=','preference=hot','station=bad','year=2027','flower=cherry&flower=camellia','GPS=33,126']:
        assert json.loads(request('/api/flower-seasons?'+suffix,400)[1])['error']
    for suffix in ['year=2027','unknown=']:
        assert json.loads(request('/api/flower-status?'+suffix,400)[1])['error']
    for body in [{'place_id':'unknown'},{'latitude':33.5,'longitude':126.5},{'place_id':True}]:
        assert json.loads(request('/api/flower-weather',400,body)[1])['error']
    request('/api/flower-weather',403,{'place_id':'unknown'},'https://example.invalid')
    weather_checked=False;weather_available=None
    if a.check_live_weather:
        point=status['weather']['places'][0]
        code,raw=request('/api/flower-weather',None,{'place_id':point['id']});weather=json.loads(raw);weather_checked=True
        assert code in {200,503}
        if code==200:
            assert weather['available'] and weather['current_forecast'] and not weather['flower_prediction'] and len(weather['days'])==7
            assert weather['point']['id']==point['id'] and weather['provider']=='Open-Meteo';weather_available=True
        else:assert weather['code']=='flower_weather_unavailable';weather_available=False
    report={'pass':True,'base':a.base,'requests':len(checks),'checks':checks,'temperature_ml_only':True,'new_bloom_model_trained':False,
            'historical_schedules_are_not_bloom_labels':True,'real_device_GPS_used':False,'external_weather_checked':weather_checked,'external_weather_available':weather_available}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=True))
if __name__=='__main__':main()
