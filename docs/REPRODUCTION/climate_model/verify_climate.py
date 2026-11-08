"""Read-only standard-library verification on the deployment Python."""
import calendar,datetime,json,math,sys,time,tracemalloc
from pathlib import Path
from climate_runtime import features,calendar_day,load_model,load_model_value,predict,sha,STATIONS
from prepare_climate import build
from freeze_climate_protocol import row_digest
HERE=Path(__file__).resolve().parent;TRIAL=HERE/'trial_01'
def main():
 manifest=json.loads((TRIAL/'artifact_manifest.json').read_text(encoding='utf-8'))
 for name,expected in manifest['files'].items():assert sha(TRIAL/name)==expected
 assert sha(HERE/'climate_runtime.py')==manifest['runtime_sha256']
 rows,sources,audit=build()
 for item in sources:assert item['sha256']==manifest['source_files_sha256'][item['file']]
 split=json.loads((TRIAL/'split_frozen.json').read_text(encoding='utf-8'));byid={r['id']:r for r in rows};seen=set();dateparts={}
 for part,refs in split['rows'].items():
  for ref in refs:
   assert ref['id'] not in seen;seen.add(ref['id']);r=byid[ref['id']];assert row_digest(r)==ref['row_sha256']
   if r['date'] in dateparts:assert dateparts[r['date']]==part
   dateparts[r['date']]=part
 assert len(seen)==31900
 assert calendar_day(2,28)<calendar_day(2,29)<calendar_day(3,1)
 assert len(features('jeju',2,29))==10
 for month,day in [(0,1),(13,1),(2,30),(4,31),(True,1)]:
  try:features('jeju',month,day)
  except ValueError:pass
  else:raise AssertionError('invalid calendar accepted')
 try:features('invalid',1,1)
 except ValueError:pass
 else:raise AssertionError('invalid station accepted')
 tracemalloc.start();tick=time.perf_counter();model=load_model(TRIAL/'climate_model.json');loadseconds=time.perf_counter()-tick;current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
 # Identical verified bytes->dict validation contract used by the HTTP backend.
 load_model_value(json.loads((TRIAL/'climate_model.json').read_bytes()))
 profilecount=0
 for station in STATIONS:
  for month in range(1,13):
   for day in range(1,calendar.monthrange(2000,month)[1]+1):
    result=predict(model,station['id'],month,day)
    if model['deployment_status']=='adoptable':assert result['available'] and result['lower_c']<=result['upper_c'] and all(math.isfinite(result[k]) for k in ['point_c','lower_c','upper_c']) and result['current_forecast'] is False
    else:assert result['available'] is False
    profilecount+=1
 # This is a local runtime benchmark on repeated valid calendar inputs, not a scientific accuracy estimate.
 times=[]
 for _ in range(100):
  tick=time.perf_counter();predict(model,'jeju',4,15);times.append((time.perf_counter()-tick)*1000)
 times.sort()
 bad=json.loads((TRIAL/'climate_model.json').read_bytes());bad['feature_names'][0]='wrong'
 try:load_model_value(bad)
 except ValueError:pass
 else:raise AssertionError('bad feature schema accepted')
 result={'python':sys.version,'stdlib_only':True,'source_checksums':'pass','artifact_checksums':'pass','chronological_splits':'pass','same_day_all_stations_same_partition':'pass','calendar_validity_and_feb29':'pass','all_valid_station_calendar_profiles':profilecount,'runtime_output_guards':'pass','model_validation_rejects_wrong_schema':'pass','model_bytes':(TRIAL/'climate_model.json').stat().st_size,'model_sha256':sha(TRIAL/'climate_model.json'),'load_seconds_local':loadseconds,'load_traced_current_mib':current/1048576,'load_traced_peak_mib':peak/1048576,'single_station_query_100_runs_ms':{'median':times[50],'p95':times[94],'max':times[-1]},'benchmark_limit':'Development-PC only; not measured on center i7-8700. Tracemalloc is Python allocations, not whole process RSS. This component allocates no GPU VRAM.','adoption_status':model['deployment_status']}
 (TRIAL/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=True))
if __name__=='__main__':main()
