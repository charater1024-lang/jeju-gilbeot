"""Small read-only SQLite indexes for the shared-PC runtime."""
import csv
import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from pathlib import Path

REGIONS={'all','east','west','south','north'}
INDUSTRY_MAP={
 '한식 음식점업':['한식','분식','식육(숯불구이)','탕류(보신용)'],
 '중식 음식점업':['중국식'], '일식 음식점업':['일식','횟집'],
 '서양식 음식점업':['경양식'], '기타 외국식 음식점업':['외국음식전문점(인도,태국등)'],
 '비알콜 음료점업':['커피숍','다방','전통찻집'],
 '피자 햄버거 샌드위치 및 유사 음식점업':['패스트푸드'], '빵 및 과자류 소매업':['제과점영업']}

def access_flags(name,address,lat,lon):
    # Conservative geographic guards are not a road or ferry network. They stop
    # obvious sea crossings and summit aliases from becoming a car itinerary.
    islands=[(33.48,33.54,126.939,126.98),(33.10,33.15,126.25,126.29),
             (33.15,33.19,126.25,126.29),(33.295,33.33,126.13,126.175),
             (33.400,33.417,126.218,126.237)]
    island_name=re.sub(r'\s+','',name) in {'우도','마라도','가파도','차귀도','비양도','추자도'}
    ferry=island_name or any(t in address for t in ['우도면','마라리','가파리','마라도','가파도','추자도']) or any(a<=lat<=b and c<=lon<=d for a,b,c,d in islands)
    summit_distance=math.hypot((lat-33.3617)*111,(lon-126.5295)*92.8)
    business_name=any(t in name.casefold() for t in ['호텔','게스트','펜션','식당','카페','리조트','특산품','아래첫마을','c.c','cc'])
    mountain=summit_distance<3 or (not business_name and (any(t in name for t in ['백록담','윗세오름','남벽분기점','사라오름']) or '한라산' in name))
    return bool(ferry),bool(mountain)

def generic_itinerary_label(name):
    compact=re.sub(r'\s+','',name)
    return bool(re.search(r'\d+일차|\d+일째|첫째날|둘째날|셋째날',compact)) or compact in {'렌트카반납','렌터카반납','숙소','아침','점심','저녁','공항도착','체크인','체크아웃','출발','도착','휴식'}

def region_for(address):
    if any(t in address for t in ['구좌읍','성산읍','우도면','표선면']):return 'east'
    if any(t in address for t in ['한림읍','한경면','애월읍','대정읍','안덕면']):return 'west'
    return 'south' if '서귀포시' in address or '남원읍' in address else 'north'

def build_store(root):
    root=Path(root);out=root/'data_reference';out.mkdir(exist_ok=True)
    path=out/'catalog.sqlite';temp=out/'catalog.building.sqlite'
    db=sqlite3.connect(temp)
    db.executescript('''DROP TABLE IF EXISTS restaurants;DROP TABLE IF EXISTS places;
      CREATE TABLE restaurants(id TEXT PRIMARY KEY,name TEXT,category TEXT,address TEXT,region TEXT,status TEXT,source_date TEXT,source_url TEXT,search_text TEXT);
      CREATE INDEX food_region_category ON restaurants(region,category,name);
      CREATE INDEX food_category ON restaurants(category,name);
      CREATE TABLE places(id TEXT PRIMARY KEY,name TEXT,address TEXT,latitude REAL,longitude REAL,region TEXT,source_date TEXT,source_url TEXT,requires_ferry INTEGER,requires_access_point INTEGER,search_text TEXT);
      CREATE INDEX place_region_name ON places(region,name);
      CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);''')
    foods=json.loads((out/'restaurants.json').read_text(encoding='utf-8'))
    db.executemany('INSERT INTO restaurants VALUES(?,?,?,?,?,?,?,?,?)',[(p['id'],p['name'],p['category'],p['address'],p['region'],p['status'],p['source_date'],p['source_url'],(p['name']+' '+p['address']+' '+p['category']).casefold()) for p in foods['items']])
    source=root/'data_raw'/'hub'/'hub_1349_5802.csv';seen=set();accepted=[];excluded=0;duplicates=0;generic=0;raw=0
    with source.open(encoding='utf-8-sig',newline='') as handle:
        for row in csv.DictReader(handle):
            raw+=1;name=row['장소명'].strip();address=(row['도로명주소'] or row['지번주소']).strip()
            if generic_itinerary_label(name):generic+=1;continue
            try:lat=float(row['위도']);lon=float(row['경도'])
            except (ValueError,TypeError):excluded+=1;continue
            if not name or not address or not math.isfinite(lat) or not math.isfinite(lon) or not (32.9<=lat<=33.7 and 126.0<=lon<=127.0):excluded+=1;continue
            key=(name,address,round(lat,7),round(lon,7))
            if key in seen:duplicates+=1;continue
            seen.add(key);ident='hub1349_'+hashlib.sha256('|'.join(map(str,key)).encode()).hexdigest()[:16]
            ferry,access=access_flags(name,address,lat,lon)
            accepted.append((ident,name,address,lat,lon,region_for(address),row['수정일시'][:10],'https://www.jejudatahub.net/data/view/data/1349',int(ferry),int(access),(name+' '+address).casefold()))
    db.executemany('INSERT INTO places VALUES(?,?,?,?,?,?,?,?,?,?,?)',accepted)
    summary={'food_rows':len(foods['items']),'food_source_date':foods.get('source_date'),'place_raw_rows':raw,'place_indexed_rows':len(accepted),'excluded_missing_or_outside_main_island':excluded,'duplicate_rows_removed':duplicates,'generic_itinerary_labels_removed':generic,
             'place_source_date':max(p[6] for p in accepted),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
             'notes':['검색 장소는 원자료 참조 좌표이며 실제 입구·운영·요금은 검증하지 않았습니다.','좌표 검수 범위는 제주 본섬 주변이며 외곽 섬이나 본섬 밖 데이터 일부는 제외했습니다.','주차·해변 시설은 실시간 정보가 아닙니다.']}
    db.executemany('INSERT INTO meta VALUES(?,?)',[(k,json.dumps(v,ensure_ascii=False)) for k,v in summary.items()])
    db.commit();db.close();temp.replace(path)
    (out/'catalog_profile.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return dict(summary,sqlite_bytes=path.stat().st_size)

def _connect(root):
    path=Path(root)/'data_reference'/'catalog.sqlite'
    if not path.is_file():raise ValueError('검색 색인이 없습니다. scripts/build_catalog.py를 실행하세요.')
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    return closing(db)

def _limit(value,maximum=50):
    try:n=int(value)
    except (ValueError,TypeError):raise ValueError('검색 개수는 정수여야 합니다.')
    if not 1<=n<=maximum:raise ValueError(f'검색 개수는 1~{maximum}이어야 합니다.')
    return n

def _region(region):
    if region not in REGIONS:raise ValueError('지원하지 않는 지역입니다.')

def food_search(root,query='',region='all',limit=6,categories=None):
    _region(region);limit=_limit(limit);needle=str(query).strip().casefold()[:100]
    clauses=[];parameters=[]
    if region!='all':clauses.append('region=?');parameters.append(region)
    if needle:
        escaped=needle.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        clauses.append("search_text LIKE ? ESCAPE '\\'");parameters.append('%'+escaped+'%')
    if categories:
        clauses.append('category IN ('+','.join('?' for _ in categories)+')');parameters.extend(categories)
    where=' WHERE '+' AND '.join(clauses) if clauses else ''
    with _connect(root) as db:
        total=db.execute('SELECT count(*) FROM restaurants'+where,parameters).fetchone()[0]
        items=[dict(r) for r in db.execute('SELECT id,name,category,address,region,status,source_date,source_url FROM restaurants'+where+' ORDER BY name,address LIMIT ?',parameters+[limit])]
        date=json.loads(db.execute("SELECT value FROM meta WHERE key='food_source_date'").fetchone()[0])
    return {'items':items,'total':total,'source_date':date,'sort':'alphabetical_not_popularity','note':'과거 인허가 기록이며 현재 영업·맛·인기도를 검증한 목록이 아닙니다.'}

def affinity_food(root,categories,region='all',limit=6):
    items=[];used=set();pools=[]
    for category in categories:
        raw_categories=INDUSTRY_MAP.get(category['name'],[])
        if not raw_categories:continue
        matches=food_search(root,region=region,limit=2,categories=raw_categories)['items']
        pools.append((category,matches))
    for turn in range(2):
        for category,matches in pools:
            if turn>=len(matches):continue
            p=matches[turn]
            if p['id'] in used:continue
            used.add(p['id']);p.update(affinity_category=category['name'],category_affinity=category['share'],reason='집단별 업종 경향을 참고한 이름순 예시이며 개별 업체 인기 순위가 아닙니다.')
            items.append(p)
            if len(items)>=limit:return items
    return items

def _place(row):
    p=dict(row);p.pop('search_text',None)
    p.update(category='장소 참조',region_label={'east':'동부','west':'서부','south':'남부','north':'북부'}[p['region']],featured=False,image=None,tags=[],
             description='허브 여행장소 목록의 주소·좌표 참조입니다. 운영·입구·요금은 별도 확인해 주세요.',source_name='제주데이터허브 비짓제주 여행장소',metadata_verified=False,
             requires_ferry=bool(p['requires_ferry']),requires_access_point=bool(p['requires_access_point']))
    return p

def place_search(root,query='',region='all',limit=12):
    _region(region);limit=_limit(limit);needle=str(query).strip().casefold()[:100]
    if len(needle)<2:return {'items':[],'total':0,'source_date':'2025-09-18','message':'장소명 또는 주소를 두 글자 이상 입력하세요.'}
    escaped=needle.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
    where=" WHERE search_text LIKE ? ESCAPE '\\'";params=['%'+escaped+'%']
    if region!='all':where+=' AND region=?';params.append(region)
    with _connect(root) as db:
        total=db.execute('SELECT count(*) FROM places'+where,params).fetchone()[0]
        items=[_place(r) for r in db.execute('SELECT * FROM places'+where+' ORDER BY name,address LIMIT ?',params+[limit])]
        date=json.loads(db.execute("SELECT value FROM meta WHERE key='place_source_date'").fetchone()[0])
    return {'items':items,'total':total,'source_date':date,'note':'원자료의 대표 좌표 참조이며 현재 운영 상태와 실제 진입로는 확인하지 않았습니다.'}

def resolve_place(root,ident):
    with _connect(root) as db:row=db.execute('SELECT * FROM places WHERE id=?',(ident,)).fetchone()
    return _place(row) if row else None

def parking(root,region='all'):
    _region(region);path=Path(root)/'data_reference'/'parking_reference.json'
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'items':[]}
    items=[]
    for raw in data['items']:
        p={k:v for k,v in raw.items() if k!='raw_row'};p['region']=region_for(p['address'])
        if region!='all' and p['region']!=region:continue
        p.update(fee=None,availability=None);items.append(p)
    return {'items':items,'total':len(items),'source_date':'2025-09-18','note':'여행장소 이름에 주차가 포함된 위치 참고 6곳입니다. 전체 공영주차장 목록·운영·요금·잔여면수는 아닙니다.'}
