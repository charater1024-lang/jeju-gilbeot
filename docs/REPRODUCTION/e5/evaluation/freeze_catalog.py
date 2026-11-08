"""Freeze source-only semantic evaluation partitions before candidate scoring."""
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(r'C:\Users\user\Documents\AI작업물\제주AI빅데이터활용')
OUT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
from jeju_agent.tourism_access import approved_places
from jeju_agent.place_trust import trust_request,place_trust

raw=(ROOT/'data_reference/tourism_guides_v12.json').read_bytes()
guides={g['id']:g for g in json.loads(raw.decode('utf-8'))['guides']}
rows=[]
with trust_request(ROOT,as_of=date(2026,11,7)):
    for item in approved_places(ROOT):
        trust=place_trust(ROOT,item,as_of=date(2026,11,7))
        if trust['checks']['official_guide']['status']!='official_source_record_verified':continue
        guide=guides[item['id']]
        rows.append({'id':item['id'],'name':item['cross_source']['hub']['name'].strip(),
                     'guide_name':guide['name'],'summary':guide['summary'],
                     'source_url':guide['source_url'],'retrieved_at':guide['retrieved_at'],
                     'automatic_eligible':trust['automatic_eligible']})
assert len(rows)==62,len(rows)
seed='jeju-semantic-eval-20261107-v1'
rows.sort(key=lambda r:hashlib.sha256((seed+':'+r['id']).encode()).hexdigest())
for i,row in enumerate(rows):row['partition']='train' if i<40 else 'dev' if i<50 else 'holdout'
document={'schema_version':1,'as_of':'2026-11-07','seed':seed,
          'partition_method':'Sort sha256(seed + colon + place_id); first40 train, next10 dev, last12 holdout.',
          'source_sha256':hashlib.sha256(raw).hexdigest(),'count':62,'rows':rows}
target=OUT/'source_partitions.json'
assert not target.exists(), 'Never replace a frozen partition silently'
target.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
for group in ['dev','holdout']:
    print(group)
    for row in rows:
        if row['partition']==group:print(json.dumps(row,ensure_ascii=False))
