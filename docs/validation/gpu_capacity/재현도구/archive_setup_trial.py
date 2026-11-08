import hashlib,json,shutil
from pathlib import Path
BASE=Path(__file__).resolve().parent
file=BASE/'results'/'route_stress_c1_max8stops.json'
DEST=BASE/'results'/'setup_trials';DEST.mkdir(exist_ok=True)
saved=DEST/'route8_with_incorrect_3stop_client_validator.json'
assert file.resolve().is_relative_to(BASE.resolve()) and saved.resolve().is_relative_to(BASE.resolve())
if not saved.exists():shutil.copy2(file,saved)
assert hashlib.sha256(file.read_bytes()).digest()==hashlib.sha256(saved.read_bytes()).digest()
data=json.loads(saved.read_text(encoding='utf-8'))
note={'excluded_from_final_capacity_stats':True,'reason':'The test client incorrectly applied its normal max3stop validator to the separate max8stop scenario. All32 HTTPresponses were200 and all32 returned8stops. Corrected client validation accepts1..8 for the stress case; service code not changed.','http_statuses':data['benchmark']['status_counts'],'stop_counts':[r['response_shape'].get('stop_count') for r in data['raw_requests']],'original_sha256':hashlib.sha256(saved.read_bytes()).hexdigest()}
(DEST/'exclusion_note.json').write_text(json.dumps(note,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(note,ensure_ascii=True))
