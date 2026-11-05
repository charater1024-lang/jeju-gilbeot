"""Offline, source-grounded customer-help dialogue. No generative model or logging."""
from contextlib import closing
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

REGIONS={'all','east','west','south','north'}
TOPICS={'menu','tourism','food','place','help'}
REGION_WORDS={'north':['북부','북쪽'], 'east':['동부','동쪽'], 'west':['서부','서쪽'], 'south':['남부','남쪽','서귀포']}
REGION_LABELS={'all':'제주 전체','north':'북부','east':'동부','west':'서부','south':'남부'}
FOODS={'흑돼지':['흑돼지','흑돈','삼겹','오겹'],'갈치':['갈치'],'고기국수':['고기국수','국수'],'해산물':['해산물','해물','횟집','전복'],'카페':['카페','커피'],'한식':['한식']}
THEMES={'해변':['해변','바다','해수욕장'],'박물관':['박물관','미술관','전시','비오는','비가와'],'숲':['숲','숲길'],'오름':['오름','등산'],'산책':['산책','공원','가족','아이와'],'전망':['전망','풍경'],'정원':['정원'],'역사':['역사','유적'],'동굴':['동굴']}
ALIASES={'성산':'seongsan','성산일출봉':'seongsan','함덕':'hamdeok','함덕해변':'hamdeok','협재':'hyeopjae','사려니':'saryeoni','천지연':'cheonjiyeon','정방':'jeongbang','섭지':'seopjikoji','오설록':'osulloc','우도':'udo','한라산':'hallasan'}
HOME=[{'label':'관광지 추천','message':'관광지 추천'},{'label':'먹거리 찾기','message':'먹거리 추천'},{'label':'장소 정보','message':'장소 정보 안내'},{'label':'여행 일정 사용법','message':'여행 일정 사용법'},{'label':'데이터·모델 안내','message':'데이터와 모델 안내'}]

def _norm(value):
    return re.sub(r'[^가-힣a-z0-9]','',unicodedata.normalize('NFKC',str(value or '')).casefold())

def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _db(root):
    return sqlite3.connect((Path(root)/'data_reference/chatbot.sqlite').resolve().as_uri()+'?mode=ro',uri=True)

def _facts(item):
    tags=item.get('observed_tags') or {}
    parts=[f"{item['name']}의 원자료 분류는 ‘{item.get('category') or '장소'}’입니다."]
    if item.get('description'):parts.append(str(item['description']))
    parts.append('기록 주소: '+str(item.get('address') or '원자료에 주소가 없습니다.'))
    if item.get('latitude') is not None and item.get('longitude') is not None:
        parts.append(f"기록 좌표: {float(item['latitude']):.5f}, {float(item['longitude']):.5f}. 실제 입구를 확인한 좌표는 아닙니다.")
    else:parts.append('좌표가 없어 가까운 거리나 지도 위치를 확인할 수 없습니다.')
    fields=[('영업시간',tags.get('opening_hours')),('전화',tags.get('phone') or tags.get('contact:phone')),('이용료',tags.get('charge') or tags.get('fee')),('휠체어',tags.get('wheelchair')),('주차',tags.get('parking'))]
    for label,value in fields:
        if value:parts.append(f'원자료 {label} 표기: {value}.')
    if item.get('source_date'):parts.append('기록 기준: '+str(item['source_date'])+'.')
    if item.get('snapshot_at'):parts.append('자료 수집: '+str(item['snapshot_at'])+'.')
    parts.append('출처: '+str(item.get('source_name') or item.get('source_platform') or '공개 원자료')+'.')
    if item.get('source_overlap_verified') is True:
        parts.append('교차 확인: 제주데이터허브 명부와 지도에서 정규화한 이름 및 250m 이내 위치가 일치한 기록입니다. 현재 운영·입구·명부 주소·공식 지정 관광지 여부는 보증하지 않습니다.')
    if item.get('kind')=='reference':parts.append('관광 분류가 확인되지 않은 여행장소 명부 참조입니다.')
    if item.get('requires_access_point'):parts.append('탐방 입구와 접근 조건을 따로 확인해야 하는 장소입니다.')
    if item.get('requires_ferry'):parts.append('배편과 운항 여부를 따로 확인해야 하는 섬 장소입니다.')
    parts.append('현재 운영·입장·메뉴·요금·통행 가능 여부는 원문과 운영기관에서 확인해 주세요.')
    return '\n'.join(parts)

def build_chatbot(root):
    root=Path(root);started=time.perf_counter();out=root/'data_reference';out.mkdir(exist_ok=True)
    sources={};records=[]
    tourism=out/'tourism.sqlite'
    with closing(sqlite3.connect(tourism.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        for row in db.execute('SELECT data_json FROM places'):
            p=json.loads(row[0]);p['plan_place_id']=p['id'];records.append(p)
    sources['tourism']={'path':'data_reference/tourism.sqlite','sha256':_hash(tourism),'rows':len(records)}
    tag_path=root/'data_raw/osm/jeju_food_overpass.json';tags={}
    if tag_path.exists():
        raw=json.loads(tag_path.read_text(encoding='utf-8'))
        tags={f"osm_{p['type']}_{p['id']}":p.get('tags',{}) for p in raw.get('elements',[]) if p.get('type') in {'node','way','relation'}}
        sources['food_tags']={'path':'data_raw/osm/jeju_food_overpass.json','sha256':_hash(tag_path)}
    food=out/'discovery.sqlite';food_count=0
    with closing(sqlite3.connect(food.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        for row in db.execute('SELECT * FROM restaurants'):
            p=dict(row);p.pop('doc_id',None);p['kind']='food';p['featured']=False
            coord=p.get('coordinate_source');coord=json.loads(coord) if isinstance(coord,str) and coord else coord
            p['plan_place_id']=p['id'] if p.get('source_platform')=='openstreetmap' else coord.get('place_id') if isinstance(coord,dict) else None
            p['source_name']='© OpenStreetMap contributors · ODbL' if p.get('source_platform')=='openstreetmap' else '제주데이터허브 음식점 인허가 기록'
            p['tags']=json.loads(p.pop('tags_json','[]') or '[]');p['observed_tags']=tags.get(p['id'],{})
            p['requires_ferry']=bool(p.get('requires_ferry'));p['requires_access_point']=bool(p.get('requires_access_point'))
            records.append(p);food_count+=1
    sources['food']={'path':'data_reference/discovery.sqlite','sha256':_hash(food),'rows':food_count}
    faq_path=root/'config/chatbot_faq.json';faq=json.loads(faq_path.read_text(encoding='utf-8'))['items'];sources['faq']={'path':'config/chatbot_faq.json','sha256':_hash(faq_path),'rows':len(faq)}
    path=out/'chatbot.building.sqlite';db=sqlite3.connect(path)
    db.executescript('DROP TABLE IF EXISTS answers;CREATE TABLE answers(id TEXT PRIMARY KEY,name TEXT NOT NULL,name_norm TEXT NOT NULL,kind TEXT,region TEXT,featured INTEGER,prepared_text TEXT NOT NULL,data_json TEXT NOT NULL);CREATE INDEX answer_name ON answers(name_norm);CREATE INDEX answer_kind_region ON answers(kind,region);')
    counts={}
    for p in records:
        counts[p['kind']]=counts.get(p['kind'],0)+1
        db.execute('INSERT INTO answers VALUES(?,?,?,?,?,?,?,?)',(p['id'],p['name'],_norm(p['name']),p['kind'],p.get('region','all'),int(bool(p.get('featured'))),_facts(p),json.dumps(p,ensure_ascii=False,separators=(',',':'))))
    db.commit();db.close();path.replace(out/'chatbot.sqlite')
    profile={'schema_version':1,'status':'ready','prepared_answers':len(records),'faq_count':len(faq),'method':'rule_intent_and_slot_dialogue_with_source_prepared_answers_and_existing_tfidf_retrieval','llm_used':False,'offline':True,'data_counts':counts,'sources':sources,'database_bytes':(out/'chatbot.sqlite').stat().st_size,'build_seconds':round(time.perf_counter()-started,3),'answer_count_definition':'교차확인 관광 후보와 음식점 출처 기록별 실제 필드로 렌더링한 안내문입니다. 사람이 작성한 독립 FAQ 수나 전체 고유 장소 수가 아닙니다.','limitations':['자유 생성형 대화나 임의 질문의 완전한 이해를 제공하지 않습니다.','현재 운영·날씨·교통·잔여 주차면·메뉴·인기도를 검증하지 않습니다.','지역·테마 분류와 후속 질문 처리는 규칙이며 검색 관련도는 기존 TF-IDF 모델을 사용합니다.'],'privacy':{'server_conversation_storage':False,'external_requests':False,'device_gps_used':False}}
    profile['privacy'].update(device_gps_used='only_with_explicit_browser_consent',precise_location_persisted=False,precise_location_echoed=False)
    profile['location_recommendation']={'available':True,'consent_required':True,'radius_km':20,'distance':'straight_line','unmapped_nearby_results':False}
    (out/'chatbot_profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8');_faq.cache_clear()
    return profile

@lru_cache(maxsize=4)
def _faq(path,mtime):return json.loads(Path(path).read_text(encoding='utf-8'))['items']

def chat_status(root):
    path=Path(root)/'data_reference/chatbot_profile.json'
    if not path.exists():return {'ready':False,'prepared_answers':0,'faq_count':0,'offline':True,'llm_used':False}
    profile=json.loads(path.read_text(encoding='utf-8'));profile['ready']=(Path(root)/'data_reference/chatbot.sqlite').is_file()
    profile['location_recommendation']={'available':True,'consent_required':True,'radius_km':20,'distance':'straight_line','unmapped_nearby_results':False}
    profile.setdefault('privacy',{}).update(device_gps_used='only_with_explicit_browser_consent',precise_location_persisted=False,precise_location_echoed=False)
    return profile

def _read(root,ident):
    with closing(_db(root)) as db:
        row=db.execute('SELECT data_json,prepared_text FROM answers WHERE id=?',(ident,)).fetchone()
    if not row:return None,None
    from .tourism_guides import enrich_tourism
    original=json.loads(row[0]);item=enrich_tourism(root,original);text=row[1]
    if item.get('name') != original.get('name'):
        # Only the template's leading place name changes; source values stay intact.
        prefix=str(original.get('name') or '')+'의 원자료 분류는'
        if text.startswith(prefix):text=item['name']+'의 원자료 분류는'+text[len(prefix):]
    if item.get('tourism_guide'):
        guide=item['tourism_guide'];text=guide['summary']+'\n관광 안내 출처: '+guide['source_name']+'\n\n'+text
    return item,text

def _state(root,value):
    if value is None:value={}
    if not isinstance(value,dict):raise ValueError('state는 객체여야 합니다.')
    region=value.get('region');topic=value.get('topic')
    state={'region':region if isinstance(region,str) and region in REGIONS else 'all','topic':topic if isinstance(topic,str) and topic in TOPICS else 'menu','last_place_id':None,'choice_ids':[],'last_query':'','offset':0,'nearby':value.get('nearby') is True}
    if isinstance(value.get('last_query'),str):state['last_query']=value['last_query'][:100]
    offset=value.get('offset',0)
    if isinstance(offset,int) and not isinstance(offset,bool) and 0<=offset<=1000:state['offset']=offset
    ident=value.get('last_place_id')
    if isinstance(ident,str) and len(ident)<=120 and _read(root,ident)[0]:state['last_place_id']=ident
    choices=value.get('choice_ids',[])
    if isinstance(choices,list):
        for ident in choices[:5]:
            if isinstance(ident,str) and len(ident)<=120 and ident not in state['choice_ids'] and _read(root,ident)[0]:state['choice_ids'].append(ident)
    return state

def _response(reply,state,intent='menu',source='faq',cards=None,quick=None):
    return {'reply':reply,'cards':cards or [],'quick_replies':HOME if quick is None else quick,'state':state,'intent':intent,'answer_source':source,'offline':True,'llm_used':False,'needs_location':False,'location_used':False}


def _location_request(body):
    """Validate a fresh request-only origin; never copy it into dialogue state."""
    declined=body.get('location_declined',False)
    if not isinstance(declined,bool):raise ValueError('location_declined는 불리언이어야 합니다.')
    raw=body.get('location')
    if raw is None:return None,'declined' if declined else 'not_provided',declined
    if not isinstance(raw,dict):raise ValueError('location은 위도·경도 객체 또는 null이어야 합니다.')
    source=raw.get('source','device')
    if not isinstance(source,str) or source not in {'manual','device'}:raise ValueError('location.source는 manual 또는 device여야 합니다.')
    if raw.get('label') is not None and (not isinstance(raw['label'],str) or len(raw['label'])>100):raise ValueError('location.label은 100자 이내 문자열이어야 합니다.')
    point={'source':source}
    for key,lower,upper in [('latitude',-90,90),('longitude',-180,180),('accuracy_m',0,100000)]:
        if key=='accuracy_m' and raw.get(key) is None:continue
        value=raw.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lower<=value<=upper:
            raise ValueError('위도·경도와 정확도는 허용 범위 안의 유한한 숫자여야 합니다.')
        point[key]=float(value)
    # The explicit decline takes priority even if a caller accidentally supplied an origin.
    if declined:return None,'declined',True
    from .discovery import _point
    if _point(point['latitude'],point['longitude']) is None:return None,'outside_jeju',False
    return point,'low_accuracy' if point.get('accuracy_m',0)>5000 else 'provided',False


def _nearby_words(norm):
    return any(word in norm for word in ['근처','주변','가까운','가까이','내위치','현재위치','gps'])


def _named_nearby(root,message):
    """A named landmark's vicinity is different from the visitor's device origin."""
    norm=_norm(message)
    for relation in ['근처','주변']:
        if relation not in norm:continue
        before=norm.split(relation,1)[0]
        if before and _entity(root,before):return True
    return False


def _need_location(state):
    result=_response('가까운 장소를 찾으려면 위치 사용에 동의한 뒤 브라우저 권한을 허용해 주세요. 위치를 사용하지 않으면 지역·음식·테마로 계속 찾을 수 있습니다.',state,'location_consent','clarification',quick=[{'label':'관광지 찾기','message':'관광지 추천'},{'label':'먹거리 찾기','message':'먹거리 추천'}])
    result.update(needs_location=True,location_status='not_provided',radius_km=20)
    return result

def _dedupe_candidates(rows):
    """Group only equal names with observed coordinates within 500m, prefer curated."""
    from .discovery import _distance
    result=[];seen=set()
    for p in rows:
        if p['id'] in seen:continue
        seen.add(p['id']);match=None
        if all(isinstance(p.get(k),(int,float)) and not isinstance(p.get(k),bool) for k in ['latitude','longitude']):
            for i,old in enumerate(result):
                if _norm(old['name'])==_norm(p['name']) and all(isinstance(old.get(k),(int,float)) for k in ['latitude','longitude']) and _distance((p['latitude'],p['longitude']),(old['latitude'],old['longitude']))<=.5:match=i;break
        if match is None:result.append(p)
        elif p.get('featured') and not result[match].get('featured'):result[match]=p
    return result

def _faq_response(item,state):
    return _response(item['reply'],state,item['id'],'faq',quick=item.get('quick_replies'))

def _fallback(state):
    return _response('이 질문은 준비된 제주 여행 안내 범위에서 이해하지 못했어요. 아래 메뉴를 고르거나 ‘북부 해변 추천’, ‘고기국수 추천’, ‘함덕해수욕장 주소’처럼 짧게 질문해 주세요.',state,'fallback','clarification')

def _short_field_followup(message):
    """Only explicit pronouns or field-only questions may inherit the old place."""
    norm=_norm(message)
    for prefix in ['해당장소의','해당장소','그장소의','그장소','그곳의','그곳','거기의','거기','이곳의','이곳']:
        if norm.startswith(prefix):norm=norm[len(prefix):];break
    endings=['알려주세요','알려줘','보여주세요','보여줘','어떻게돼','어떤가요','어디인가요','뭐인가요','어디야','뭐야','인가요','이야','나요','은','는','요','야']
    for _ in range(3):
        match=next((word for word in endings if norm.endswith(word)),None)
        if not match:break
        norm=norm[:-len(match)]
    return norm in {'주소','위치','영업시간','운영시간','개장시간','입장료','이용료','요금','가격','주차','주차정보','휠체어','휠체어정보','전화','전화번호','연락처','출처','자료원문','근거','몇시'}

def _place_question(message,entities):
    norm=_norm(message)
    if _field(message) or any(word in norm for word in ['정보','소개','자세','상세','어떤곳','어떤장소','메뉴','예약','배편','탐방']):return True
    residual=norm
    for p in entities:
        residual=residual.replace(_norm(p['name']),'')
        for alias,ident in ALIASES.items():
            if ident==p['id']:residual=residual.replace(_norm(alias),'')
    for filler in ['알려주세요','알려줘','보여주세요','보여줘','설명해주세요','설명해줘','제주도','제주','궁금해','어때요','어때','은요','는요','에대해','에대한']:
        residual=residual.replace(filler,'')
    return residual in {'','은','는','이','가','요'}

def _place_tail(after):
    if after.startswith('의'):after=after[1:]
    return not after or _short_field_followup(after) or after in {'정보','소개','소개해줘','알려줘','알려주세요','상세','상세정보','정보알려줘','정보좀알려줘','자세히알려줘','에대해알려줘','은어떤곳이야','는어떤곳이야','어떤곳이야','어때','어때요','추천','추천해줘','궁금해','가궁금해'}

def _entity(root,message):
    norm=_norm(message)
    with closing(_db(root)) as db:
        db.row_factory=sqlite3.Row
        rows=list(db.execute('SELECT name_norm,featured,data_json FROM answers WHERE length(name_norm)>=3 AND instr(?,name_norm)>0 ORDER BY length(name_norm) DESC,featured DESC LIMIT 30',(norm,)))
    prefixes={'','제주','제주도','북부','동부','서부','남부','제주북부','제주동부','제주서부','제주남부'}
    rows=[row for row in rows if norm.split(row['name_norm'],1)[0] in prefixes and _place_tail(norm.split(row['name_norm'],1)[1])]
    if not rows:
        # A short alias must stand alone or be followed by a field/question.
        # "함덕카페 주소" must not silently become the beach's address.
        for alias,ident in sorted(ALIASES.items(),key=lambda pair:-len(pair[0])):
            alias=_norm(alias)
            if alias not in norm:continue
            before,after=norm.split(alias,1)
            if before not in prefixes or not _place_tail(after):continue
            p,_=_read(root,ident)
            if p:return [p]
        return []
    longest=len(rows[0]['name_norm']);rows=[r for r in rows if len(r['name_norm'])==longest]
    from .tourism_guides import enrich_tourism
    if rows[0]['featured']:return [enrich_tourism(root,json.loads(rows[0]['data_json']))]
    unique={}
    for row in rows:
        p=enrich_tourism(root,json.loads(row['data_json']));key=(_norm(p['name']),_norm(p.get('address') or ''),p.get('latitude'),p.get('longitude'))
        unique.setdefault(key,p)
    return list(unique.values())[:5]

def _field(message):
    norm=_norm(message)
    for key,words in [('hours',['영업','운영시간','개장','개방시간','몇시','언제열']),('fee',['요금','입장료','이용료','가격','무료']),('parking',['주차']),('wheelchair',['휠체어','무장애','접근성']),('phone',['전화','연락처']),('address',['주소','어디있','위치']),('source',['출처','자료원문','근거'])]:
        if any(word in norm for word in words):return key
    return None

def _place_answer(root,p,message,state):
    p,text=_read(root,p['id']);topic='food' if p.get('kind')=='food' else 'tourism'
    if state['topic']!=topic:state.update(last_query='',offset=0)
    state.update(topic=topic,last_place_id=p['id'])
    if p['id'] not in state['choice_ids']:state['choice_ids']=[p['id']]
    key=_field(message);tags=p.get('observed_tags') or {}
    labels={'hours':('영업시간',tags.get('opening_hours')),'fee':('이용료',tags.get('charge') or tags.get('fee')),'parking':('주차',tags.get('parking')),'wheelchair':('휠체어',tags.get('wheelchair')),'phone':('전화',tags.get('phone') or tags.get('contact:phone'))}
    if key in labels:
        label,value=labels[key];text=(f"{p['name']}의 원자료 {label} 표기는 ‘{value}’입니다. 현재 상태를 확인한 안내가 아니므로 방문 전에 원문과 운영기관에서 확인해 주세요." if value else f"{p['name']}의 {label} 정보는 확보한 원자료에 없습니다. 확인되지 않은 값을 안내하지 않습니다. 아래 상세 카드의 자료 원문에서 운영기관 안내를 확인해 주세요.")
    elif key=='address':text=(f"{p['name']}의 기록 주소는 {p['address']}입니다. " if p.get('address') else f"{p['name']}의 주소는 원자료에 없습니다. ")+(f"참고 좌표는 {p['latitude']:.5f}, {p['longitude']:.5f}이며 실제 입구는 별도 확인해 주세요." if p.get('latitude') is not None else '좌표가 없어 지도에서 정확한 위치와 거리를 확인할 수 없습니다.')
    elif key=='source':text=f"{p['name']}의 출처는 {p.get('source_name') or p.get('source_platform') or '공개 원자료'}입니다. 기록 기준: {p.get('source_date') or '표기 없음'}, 수집 기준: {p.get('snapshot_at') or '표기 없음'}. 아래 카드의 출처 링크를 확인하세요."
    return _response(text,state,'place_'+(key or 'details'),'prepared_text',[p],[{'label':'주소·위치','message':'주소 알려줘'},{'label':'영업시간 기록','message':'영업시간 알려줘'},{'label':'요금 기록','message':'입장료 알려줘'},{'label':'주차 정보','message':'주차 정보 알려줘'},{'label':'처음으로','message':'처음으로'}])

def chat_reply(root,body):
    root=Path(root)
    if not isinstance(body,dict):raise ValueError('JSON 객체가 필요합니다.')
    message=body.get('message','')
    if not isinstance(message,str) or len(message)>300:raise ValueError('질문은 300자 이내 문자열로 입력하세요.')
    message=message.strip();norm=_norm(message);state=_state(root,body.get('state'));original_state={**state,'choice_ids':list(state['choice_ids'])}
    location,location_status,declined=_location_request(body)
    nearby=_nearby_words(norm)
    next_page=any(word in norm for word in ['다른곳','다른장소','다른거','더보여','더추천','다음추천'])
    nearby=nearby or (next_page and state['nearby'])
    faq_path=root/'config/chatbot_faq.json';faq=_faq(str(faq_path.resolve()),faq_path.stat().st_mtime_ns)
    if not norm or norm in {'처음으로','처음','메뉴','시작','안녕','안녕하세요','대화초기화','리셋'}:
        return _faq_response(faq[0],{'region':'all','topic':'menu','last_place_id':None,'choice_ids':[],'last_query':'','offset':0,'nearby':False})
    for item in faq[1:]:
        if item['id'] in {'tourism_menu','food_menu'} and (location or nearby or declined):continue
        if any(_norm(word)==norm for word in item.get('exact',[])):return _faq_response(item,state)
    for item in faq[1:]:
        if item['id'] in {'data_help','itinerary_help','no_llm','offline_help','privacy_help','scope_help'} and any(_norm(word) in norm for word in item.get('keywords',[])):return _faq_response(item,state)
    if any(word in norm for word in ['대통령','주가','주식','삼성전자','선거','정치','코딩','파이썬','양자역학','미분방정식','진단','처방','법률']):return _fallback(original_state)
    if any(word in norm for word in ['싫어','싫다','말고','빼고','제외','아닌','안갈','안가고','원하지않']):
        return _response('제외하거나 부정하는 조건은 아직 정확히 처리하지 못합니다. 기존 조건은 유지했어요. 원하는 조건만 ‘서부 박물관 추천’처럼 다시 입력해 주세요.',original_state,'clarify_negation','clarification')
    if ('지금' in norm and not nearby) or any(word in norm for word in ['현재영업','현재운영','현재개방','오늘영업','오늘개장','오늘문','실시간','날씨','비와','비오나','대기시간','잔여주차','버스시간','운행시간','교통상황']):
        return _response('현재 날씨·영업·교통·잔여 주차면·대기시간은 이 오프라인 자료로 확인할 수 없습니다. 장소의 기록 정보는 안내할 수 있어요. 현재 정보는 운영기관의 최신 안내를 확인해 주세요.',original_state,'realtime_unavailable')
    if nearby and _named_nearby(root,message):
        return _response('이 질문의 기준은 이름으로 적은 장소입니다. 기기 위치와 혼동하지 않도록 해당 장소 상세의 지도 보기를 누르고 지도에서 기준 장소를 선택해 주변을 찾아 주세요. ‘내 근처 카페 추천’이라고 질문하면 동의한 기기 위치를 기준으로 찾습니다.',state,'nearby_help','clarification')
    if re.search(r'\d{2}\.\d+\s*[,/]\s*1\d{2}\.\d+',message):
        return _response('질문에 적은 숫자를 기기 위치로 읽거나 자동 사용하지 않습니다. 챗봇의 ‘내 위치 사용’에 동의하거나 지도에서 기준 장소를 직접 골라 주세요.',state,'location_help')
    if nearby and location_status=='outside_jeju':
        result=_response('기기 위치가 제주 범위 밖이어서 가까운 제주 장소를 계산하지 않았습니다. 지도에서 제주공항 등 기준 장소를 고르거나 ‘북부 해변 추천’처럼 지역으로 질문해 주세요.',state,'location_outside_jeju','clarification')
        result.update(location_status='outside_jeju',radius_km=20);return result
    if nearby and location is None and not declined:return _need_location(original_state)
    explicit_region=False
    for region,words in REGION_WORDS.items():
        if any(word in norm for word in words):state['region']=region;explicit_region=True;break
    if location and not explicit_region:state['region']='all'
    if any(word in norm for word in ['제주전체','지역초기화','전체지역']):state['region']='all'
    if re.fullmatch(r'(?:첫번째|두번째|세번째|네번째|다섯번째|[1-5]번)(?:장소)?(?:정보|주소|영업시간|입장료|주차)?(?:알려줘|알려주세요|보여줘|상세|자세히|은|는)?',norm):
        index=next((i for i,words in enumerate([['첫번째','1번'],['두번째','2번'],['세번째','3번'],['네번째','4번'],['다섯번째','5번']]) if any(word in norm for word in words)),None)
        choices=state['choice_ids']
        if index is not None and index<len(choices):return _place_answer(root,_read(root,choices[index])[0],message,state)
        return _response('현재 답변에 그 번호의 장소가 없습니다. 관광지나 먹거리를 먼저 찾아 주세요.',state,'clarify_choice','clarification')
    food=next((key for key,words in FOODS.items() if any(_norm(word) in norm for word in words)),None)
    theme=next((key for key,words in THEMES.items() if any(_norm(word) in norm for word in words)),None)
    recommend=any(word in norm for word in ['추천','찾아','찾기','갈만','가볼','둘러','보여'])
    entities=_entity(root,message)
    generic_terms={_norm(word) for groups in [FOODS,THEMES] for key,words in groups.items() for word in [key]+words}
    if (food or theme) and not _field(message) and not any(word in norm for word in ['정보','상세','자세히']):entities=[p for p in entities if _norm(p['name']) not in generic_terms]
    if entities and _place_question(message,entities) and (not recommend or not food and not theme or any(_norm(p['name']) in norm for p in entities)):
        if len(entities)==1:return _place_answer(root,entities[0],message,state)
        state.update(topic='place',choice_ids=[p['id'] for p in entities],last_place_id=None)
        return _response('같거나 비슷한 이름의 기록이 여러 개입니다. 주소와 출처를 보고 원하는 장소를 선택하거나 번호로 알려주세요.',state,'clarify_entity','clarification',entities,[{'label':f'{i+1}번 {p["name"][:18]}','message':f'{i+1}번'} for i,p in enumerate(entities)])
    if _field(message) and _short_field_followup(message) and state.get('last_place_id'):
        return _place_answer(root,_read(root,state['last_place_id'])[0],message,state)
    for item in faq[1:]:
        if item['id']=='nearby_help':continue
        if any(_norm(word) in norm for word in item.get('keywords',[])):return _faq_response(item,state)
    if _field(message) and not nearby:
        return _response('해당 질문의 장소를 확인하지 못했습니다. ‘함덕해수욕장 주소’, ‘성산일출봉 정보’처럼 확보된 장소 이름을 함께 입력하거나 검색 결과의 상세 보기를 눌러 주세요.',original_state,'ask_place','clarification')
    region_only=any(norm in {_norm(word),_norm(word)+'로',_norm(word)+'는',_norm(word)+'에서'} for words in REGION_WORDS.values() for word in words) or norm in {'제주전체','전체지역'}
    if food or '먹거리' in norm or '맛집' in norm or '식당추천' in norm or (nearby and any(word in norm for word in ['식당','음식'])) or norm=='음식추천':topic='food'
    elif theme or '관광' in norm or '여행지' in norm or '가볼' in norm:topic='tourism'
    elif (next_page or region_only) and state['topic'] in {'food','tourism'}:topic=state['topic']
    elif nearby:topic=state['topic'] if state['topic'] in {'food','tourism'} else 'tourism'
    else:topic=None
    if topic:
        if next_page:query=state['last_query'];offset=state['offset']+5
        elif region_only:query=state['last_query'];offset=0
        else:query=(food or '') if topic=='food' else theme or '';offset=0
        state.update(topic=topic,last_query=query,offset=offset,last_place_id=None,nearby=location is not None)
        origin_label='선택한 기준 장소' if location and location.get('source')=='manual' else '동의한 기기 위치'
        search_request={'query':query,'region':state['region'],'location':location,'radius_km':20}
        if topic=='tourism':
            from .tourism import search_tourism
            result=search_tourism(root,{**search_request,'kind':'attraction','limit':100,'offset':0});cards=_dedupe_candidates(result['items'])[offset:offset+5]
            reply=f"{REGION_LABELS[state['region']]}에서 {query+' 관련 ' if query else ''}교차확인 관광지 기록을 찾아봤어요. 두 자료의 이름·위치와 관광 분류를 점검한 말뭉치로 다시 학습한 TF-IDF 후보이며 인기도 순위는 아닙니다."
        else:
            from .discovery import discovery_recommend
            result=discovery_recommend(root,{**search_request,'limit':12})
            rows=_dedupe_candidates(result['restaurants']+([] if location else result['unmapped_restaurants']));cards=rows[offset:offset+5]
            reply=f"{REGION_LABELS[state['region']]}의 {query or '먹거리'} 관련 업소 기록입니다. 상호·업종·관측된 태그의 문자 관련도를 활용하며 실제 메뉴·맛·인기·현재 영업을 확인한 추천은 아닙니다."
        if location:
            subject=(query+' 관련 업소' if query else '먹거리 업소') if topic=='food' else (query+' 관련 교차확인 관광지' if query else '교차확인 관광지')
            order='관련도 분류 후 같은 분류에서 가까운 순입니다.' if query else '가까운 직선거리 순입니다.'
            limits='실제 메뉴·맛·인기·현재 영업은 미확인이며 도로 거리와 다릅니다.' if topic=='food' else '현재 운영·실제 입구·인기도는 미확인이며 도로 거리와 다릅니다.'
            reply=f'{origin_label}에서 직선거리 20km 안의 좌표가 있는 {subject} 기록을 찾았어요. {order} {limits}'
        elif declined:
            reply='위치를 사용하지 않고 선택한 지역·음식·테마 기준으로 찾았습니다. 가까운 순서나 반경 검색을 적용하지 않았습니다. '+reply
        elif location_status=='outside_jeju':
            reply='기기 위치가 제주 범위 밖이어서 가까운 순서나 반경 검색을 적용하지 않았습니다. '+reply
        state['choice_ids']=[p['id'] for p in cards]
        if not cards:reply=(origin_label+'의 직선거리 20km 반경에서 이 조건으로 더 보여드릴 기록이 없습니다. 다른 음식·테마나 지역 검색을 선택해 주세요.' if location else '이 조건에서 더 보여드릴 기록이 없습니다. 다른 테마나 더 넓은 지역을 골라 주세요.')
        if location and location_status=='low_accuracy':reply+=' 기준 위치 오차가 5km보다 커 거리·반경에 큰 오차가 있을 수 있습니다.'
        quick=[{'label':'다른 곳 보기','message':'다른 곳 추천'},{'label':'북부','message':'북부'},{'label':'동부','message':'동부'},{'label':'서부','message':'서부'},{'label':'남부','message':'남부'},{'label':'처음으로','message':'처음으로'}]
        response=_response(reply,state,topic+'_search','model_search',cards,quick)
        response.update(location_used=location is not None,location_status=location_status,location_source=location.get('source') if location else None,radius_km=20 if location else None,distance_basis='provided_location_straight_line' if location else 'not_available')
        return response
    if '정보' in norm or _field(message) or '자세히' in norm:
        return _response('해당 질문의 장소를 확인하지 못했습니다. ‘함덕해수욕장 주소’, ‘성산일출봉 정보’처럼 확보된 장소 이름을 함께 입력하거나 검색 결과의 상세 보기를 눌러 주세요.',original_state,'ask_place','clarification')
    return _fallback(original_state)
