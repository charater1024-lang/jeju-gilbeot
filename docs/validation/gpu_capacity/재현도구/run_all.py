import json,subprocess,sys,time
from pathlib import Path
BASE=Path(__file__).resolve().parent
protocol={'as_of_kst':'2026-11-08','scope':'Current development PC owned loopback server, not center hardware','workloads':['GPU short semantic queries','Mixed GPU search, tabular models, climate, rule chat, automatic route','Long-query CPU fallback with GPU still resident','512 request mixed waves, up to8 requests started together'],'concurrency':[1,2,4,8,12,16,24,32],'minimum_requests_per_step':64,'minimum_waves_per_step':4,'http_timeout_seconds':30,'monitor_requested_interval_seconds':.1,'pass_rule':'HTTP200 and valid response structure, no timeout, model remains resident, no monitoring error or resource stop','latency_reporting_rules':{'interactive_p95_ms':2000,'general_p95_ms':5000,'meaning':'Chosen reporting thresholds, not measured field user requirements'},'safety_stops':{'server_ram_gib':6,'server_dedicated_vram_gib':2,'system_available_ram_min_gib':8},'no_external_network':True,'no_real_user_gps':True,'no_model_training_or_threshold_tuning':True,'server_compute_slots':8,'connection_limit':48,'gpu_encoder_session':1,'gpu_batch':1,'gpu_encoder_execution_serialized':True,'no_center_throughput_conversion':True,'empty_search_result_is_valid_scoped_response_not_recommendation_quality':True}
(BASE/'results'/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
for part in ['short','mixed','long','soak']:
    print(json.dumps({'starting_part':part,'time_ns':time.time_ns()}),flush=True)
    r=subprocess.run([sys.executable,str(BASE/'load_benchmark.py'),'--part',part],cwd=BASE)
    if r.returncode:raise SystemExit(r.returncode)
print(json.dumps({'all_parts_completed':True,'time_ns':time.time_ns()}),flush=True)
