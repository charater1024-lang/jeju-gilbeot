"""Validated local file ingestion. Does not download or assume data licenses."""
import csv
import hashlib
import json
import math
from datetime import date
from pathlib import Path
import shutil

POI_FIELDS = ['poi_id','name','category','region','latitude','longitude','tags','indoor','stay_minutes','cost_krw','open_minute','close_minute','source_id']
DEMAND_FIELDS = ['date','poi_id','visits','source_id']

def rows(path, required):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        missing = set(required) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'{Path(path).name}: 누락 컬럼 {sorted(missing)}')
        return list(reader)

def number(row, key, lo, hi, integral=False):
    x = float(row[key])
    if not math.isfinite(x) or not lo <= x <= hi or (integral and not x.is_integer()):
        raise ValueError(f'{key}: 허용 범위 또는 정수 조건 위반 {row[key]}')
    return x

def validate(data_dir, require_real=False):
    base = Path(data_dir)
    pois = rows(base/'pois.csv', POI_FIELDS)
    demand = rows(base/'demand.csv', DEMAND_FIELDS)
    if not pois or not demand:
        raise ValueError('POI와 수요 데이터가 모두 필요합니다.')
    ids, seen, source_ids = set(), set(), set()
    for p in pois:
        if not p['poi_id'].strip() or p['poi_id'] in ids or not p['name'].strip() or not p['source_id'].strip():
            raise ValueError('중복 또는 빈 POI 식별자, 장소명, 출처')
        ids.add(p['poi_id']); source_ids.add(p['source_id'])
        number(p,'latitude',32.9,33.7); number(p,'longitude',126.0,127.0)
        number(p,'stay_minutes',1,720,True); number(p,'cost_krw',0,10000000,True)
        a = number(p,'open_minute',0,1440,True); b = number(p,'close_minute',0,1440,True)
        if a >= b or p['indoor'] not in {'0','1'}:
            raise ValueError('영업시간 또는 indoor 값이 잘못되었습니다.')
    for r in demand:
        date.fromisoformat(r['date'])
        if r['poi_id'] not in ids or not r['source_id'].strip():
            raise ValueError('수요 행의 POI 또는 출처가 유효하지 않습니다.')
        number(r,'visits',0,100000000)
        key = (r['date'], r['poi_id'])
        if key in seen:
            raise ValueError(f'중복 POI 일자 관측치 {key}. 공급자 간 단순 합산은 허용하지 않습니다.')
        seen.add(key); source_ids.add(r['source_id'])
    mode_path = base/'demo_metadata.json'
    mode = json.loads(mode_path.read_text(encoding='utf-8')) if mode_path.exists() else {}
    synthetic = mode.get('synthetic') is True
    registry = base/'source_manifest.json'
    sources = json.loads(registry.read_text(encoding='utf-8')).get('sources',[]) if registry.exists() else []
    if require_real:
        if synthetic or any(sid.casefold().startswith('synthetic') for sid in source_ids):
            raise ValueError('합성 데이터를 실제 데이터로 승인할 수 없습니다.')
        approved = {}
        for s in sources:
            if s.get('status') != 'approved' or not s.get('source_url') or not s.get('license') or not s.get('acquired_at') or s.get('synthetic') is True:
                continue
            if s.get('redistribution_allowed') is not True:
                continue
            if s.get('platform') not in {'jeju_datahub','jeju_bigdata_center'}:
                raise ValueError('출처 platform은 jeju_datahub 또는 jeju_bigdata_center여야 합니다.')
            approved[s.get('source_id')] = s
        if source_ids - set(approved):
            raise ValueError('출처별 URL, 이용조건, 확보일, 재배포 허용 확인이 필요합니다.')
        original_ids = [approved[sid].get('original_dataset_id') for sid in source_ids]
        if any(not isinstance(ident,str) or not ident.strip() for ident in original_ids):
            raise ValueError('각 출처의 원본 데이터셋 식별자 original_dataset_id가 필요합니다.')
        if len(set(original_ids)) != len(original_ids):
            raise ValueError('같은 원본 데이터셋의 허브·센터 유통본을 독립 자료로 중복 등록할 수 없습니다.')
        demand_sources = {r['source_id'] for r in demand}
        for sid in demand_sources:
            s = approved[sid]
            if s.get('granularity') != 'poi_day' or s.get('measure') != 'visits':
                raise ValueError('MVP 수요 모델은 장소별 일별 방문 관측만 지원합니다. 매출·지역 집계는 별도 모델로 분리하세요.')
        platforms = {approved[s]['platform'] for s in source_ids}
        if not {'jeju_datahub','jeju_bigdata_center'} <= platforms:
            raise ValueError('이 프로젝트의 실데이터 완료 기준은 두 플랫폼 자료를 모두 사용하는 것입니다.')
    return {'status':'valid','mode':'synthetic' if synthetic else ('real_validated' if require_real else 'unverified'),
            'pois':len(pois),'observations':len(demand),'source_ids':sorted(source_ids),
            'first_date':min(r['date'] for r in demand),'last_date':max(r['date'] for r in demand)}

def import_data(source_dir, target_dir):
    """Validate all files first; caller explicitly chooses real dataset directory."""
    source, target = Path(source_dir).resolve(), Path(target_dir).resolve()
    result = validate(source, require_real=True)
    if target.exists() and any(target.iterdir()):
        raise ValueError('가져오기 대상 폴더는 비어 있어야 합니다.')
    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in ['pois.csv','demand.csv','source_manifest.json']:
        shutil.copyfile(source/name, target/name)
        hashes[name] = hashlib.sha256((target/name).read_bytes()).hexdigest()
    (target/'demo_metadata.json').write_text(json.dumps({'synthetic':False,'validated':True,'sha256':hashes},ensure_ascii=False,indent=2),encoding='utf-8')
    return dict(result,sha256=hashes)
