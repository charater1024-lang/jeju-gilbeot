"""Owned isolated GPU-resident app; never reuse/stop user's existing server."""
import json,os,socket,subprocess,time,ctypes
from pathlib import Path
from urllib.request import build_opener,ProxyHandler
BASE=Path(__file__).resolve().parent
ROOT=Path(os.environ["JEJU_CAPACITY_PROJECT_ROOT"]).resolve()
PORT=8791
def main():
    for d in ['results','runtime_tmp']:(BASE/d).mkdir(exist_ok=True)
    with socket.socket() as reservation:
        reservation.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);reservation.bind(('127.0.0.1',PORT))
    env=dict(os.environ);env['TMP']=env['TEMP']=str(BASE/'runtime_tmp');env['PYTHONDONTWRITEBYTECODE']='1';env['JEJU_FLOWER_WEATHER_API']='0'
    out=open(BASE/'results'/'server.stdout.log','w',encoding='utf-8');err=open(BASE/'results'/'server.stderr.log','w',encoding='utf-8')
    args=[str(ROOT/'runtime'/'python.exe'),'-B',str(ROOT/'center_app.py'),'--port',str(PORT),'--no-browser','--semantic-device','dml','--road-gpu']
    p=subprocess.Popen(args,cwd=ROOT,env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
    state={'pid':p.pid,'port':PORT,'owned_test_process':True,'args':args,'started_time_ns':time.time_ns(),'no_real_gps':True,'outbound_weather_disabled':True}
    (BASE/'results'/'server_owner.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    from memory_probe import Probe
    probe=Probe(p.pid);samples=[];opener=build_opener(ProxyHandler({}));ready=None
    deadline=time.perf_counter()+120;next_http=0
    while time.perf_counter()<deadline:
        if p.poll() is not None:raise RuntimeError('Owned server exited; see stderr')
        samples.append(probe.sample())
        if time.perf_counter()>next_http:
            try:
                with opener.open(f'http://127.0.0.1:{PORT}/api/compute-status',timeout=.5) as r:ready=json.load(r)
                break
            except Exception:next_http=time.perf_counter()+.5
        time.sleep(.1)
    probe.close();out.close();err.close()
    report={'owner':state,'ready_status':ready,'startup_memory_samples':samples}
    (BASE/'results'/'startup.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert ready and ready['server_process_id']==p.pid and ready['semantic']['gpu_ready'] and ready['semantic']['gpu_resident'] and ready['semantic']['dml_kernel_events']>0,'Verified resident GPU not ready'
    print(json.dumps({'pass':True,'pid':p.pid,'provider':ready['preload']['provider'],'semantic':ready['semantic'],'startup_samples':len(samples)},ensure_ascii=True))
if __name__=='__main__':main()
