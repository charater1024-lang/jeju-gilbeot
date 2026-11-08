"""Aggregate only completed, declared valid stages. Setup trials are retained separately."""
import hashlib,json,statistics
from pathlib import Path
BASE=Path(__file__).resolve().parent
RESULTS=BASE/'results'
rows=[]
for p in sorted(RESULTS.glob('*.json')):
    data=json.loads(p.read_text(encoding='utf-8'))
    if 'benchmark' not in data or 'label' not in data:continue
    assert data['pass'],p.name
    measure=data['memory'];samples=measure['samples']
    intervals=[b['perf_counter']-a['perf_counter'] for a,b in zip(samples,samples[1:])]
    rows.append({'label':data['label'],'kind':data['kind'],'concurrency':data['concurrency'],**data['benchmark'],'memory_max_bytes':measure['max_sampled'],'gpu_success_delta':data['gpu_success_delta'],'cpu_long_fallback_delta':data['cpu_long_fallback_delta'],'sample_interval_median_seconds':statistics.median(intervals) if intervals else None,'sample_interval_max_seconds':max(intervals,default=None),'counter_valid_samples':measure['counter_observed_samples'],'sample_count':len(samples),'stage_file':p.name,'stage_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'cpu_budget_limited':'12logical' in data['label'],'gpu_short_verified':data.get('all_short_requests_gpu_verified'),'stops_returned':sorted({x['response_shape'].get('stop_count') for x in data['raw_requests'] if x['response_shape'].get('stop_count') is not None})})
assert len(rows)==33,len(rows)
idle=json.loads((RESULTS/'idle_after_all_load.json').read_text(encoding='utf-8'))
assert idle['no_requests_during_window'] and idle['after']['semantic']['gpu_resident']
startup=json.loads((RESULTS/'startup.json').read_text(encoding='utf-8'))
all_samples=[s for r in rows for s in json.loads((RESULTS/r['stage_file']).read_text(encoding='utf-8'))['memory']['samples']]
all_samples+=startup['startup_memory_samples']+idle['memory']['samples']
fields=['working_set_bytes','private_commit_bytes','lifetime_peak_working_set_bytes','dedicated_bytes','shared_gpu_ram_bytes']
peaks={k:max(s[k] for s in all_samples if s.get(k) is not None) for k in fields}
total=sum(r['requests'] for r in rows);errors=sum(r['errors'] for r in rows)
summary={'pass':errors==0,'as_of_kst':'2026-11-08','valid_stages':len(rows),'performance_requests':total,'http_and_shape_errors':errors,'rows':rows,'max_bytes':peaks,'max_gib':{k:v/1024**3 for k,v in peaks.items()},'idle_15seconds':{'gpu_resident_before':idle['before']['semantic']['gpu_resident'],'gpu_resident_after':idle['after']['semantic']['gpu_resident'],'first':idle['memory']['first'],'last':idle['memory']['last']},'startup_ready_ms':startup['ready_status']['semantic']['initialized_ms'],'server_pid':idle['after']['server_process_id'],'gpu_model_id':idle['after']['semantic']['model_id'],'gpu_model_sha256':idle['after']['semantic']['model_sha256'],'gpu_single_batch':idle['after']['semantic']['fixed_batch_size'],'gpu_session_model_resident':True,'small_models_on_cpu':True,'road_gpu_ready':idle['after']['road']['gpu_ready'],'long_query_cpu_fallback_observed_tokens':json.loads((RESULTS/'long_fallback_warmup.json').read_text(encoding='utf-8'))['after']['semantic']['last_query_token_count'],'no_actual_center_test':True,'no_future_center_test_commitment':True,'requested_center_budget_suggestion':{'server_ram_gib':6,'server_vram_gib':2,'initial_general_outstanding_requests':4,'initial_heavy_route_outstanding_requests':2,'basis':'Design margin on current-device measured3.63GiB lifetimeRAM/0.75GiB sampledVRAM, slower targetCPU/GPU not converted into a guaranteed capacity. Not an applied service cap.'},'cautions':['Current i9/RTX4090Laptop benchmarks do not establish i7-8700/GTX1060 latency or user capacity.','GPU memory is per-PID WDDM; shared GPU memory is systemRAM and must not be added mechanically to WorkingSet.','WorkingSet/PrivateCommit differ. Max sampled values can miss transients; lifetime peak RAM includes initial CPU fallback loading.','Wave benchmark means up toN requests started together; not a constantN-user arrival process.','HTTP success permits intentionally empty semantic results. Recommendation relevance/field satisfaction are not measured.','33valid stages exclude one archived client-validator setup error; raw setup trial is preserved.','Optional dense-nearest-road-node GPU acceleration became ready during the run; its memory is included. Astar route search and schedule calculation remainedCPU.']}
(BASE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pass':summary['pass'],'stages':len(rows),'requests':total,'errors':errors,'peak_gib':summary['max_gib'],'idle_gpu_resident':True},ensure_ascii=True))
