"""Offline, source-grounded customer-help dialogue. No generative model or logging."""
from contextlib import closing
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

DEFAULT_RADIUS = 20
PAGE_SIZE = 5
NEARBY_RELATIONS = r'근처|주변|부근|인근|주위|가까운|가까이|반경'
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
    profile['location_recommendation']={'available':True,'consent_required':True,'radius_km':DEFAULT_RADIUS,'radius_range_km':[1,100],'distance':'straight_line','unmapped_nearby_results':False}
    (out/'chatbot_profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8');_faq.cache_clear()
    return profile

@lru_cache(maxsize=4)
def _faq(path,mtime):return json.loads(Path(path).read_text(encoding='utf-8'))['items']

def chat_status(root, *, learned_search=True):
    path=Path(root)/'data_reference/chatbot_profile.json'
    if not path.exists():return {'ready':False,'prepared_answers':0,'faq_count':0,'offline':True,'llm_used':False}
    profile=json.loads(path.read_text(encoding='utf-8'));profile['ready']=(Path(root)/'data_reference/chatbot.sqlite').is_file()
    profile['location_recommendation']={'available':True,'consent_required':True,'radius_km':DEFAULT_RADIUS,'radius_range_km':[1,100],'distance':'straight_line','unmapped_nearby_results':False}
    profile.setdefault('privacy',{}).update(device_gps_used='only_with_explicit_browser_consent',precise_location_persisted=False,precise_location_echoed=False)
    if not learned_search:
        profile['method']='rule_intent_and_verified_reference_lookup'
        profile['limitations']=[note for note in profile.get('limitations',[]) if 'TF-IDF' not in note]
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
    radius = value.get('radius_km')
    state['radius_km'] = radius if type(radius) in (int, float) and 1 <= radius <= 100 else DEFAULT_RADIUS
    count = value.get('result_limit')
    state['result_limit'] = count if type(count) is int and 1 <= count <= PAGE_SIZE else PAGE_SIZE
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
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not lower<=value<=upper:
            raise ValueError('위도·경도와 정확도는 허용 범위 안의 유한한 숫자여야 합니다.')
        point[key]=float(value)
    # The explicit decline takes priority even if a caller accidentally supplied an origin.
    if declined:return None,'declined',True
    from .discovery import _point
    if _point(point['latitude'],point['longitude']) is None:return None,'outside_jeju',False
    return point,'low_accuracy' if point.get('accuracy_m',0)>5000 else 'provided',False


def _nearby_words(norm):
    return bool(re.search(NEARBY_RELATIONS + r'|내위치|현재위치|gps', norm))



def _named_nearby(norm):
    """A named or unclear landmark is never substituted with the visitor's location."""
    relation = re.search(NEARBY_RELATIONS, norm)
    if not relation or not relation.start():
        return False
    before = re.sub(r'\d+(?:km|킬로미터)$', '', norm[:relation.start()])
    if not before:
        return False
    context_words = [
        '지금', '현재', '오늘', '제주도', '제주', '전체', '내가있는곳', '내위치', '현재위치',
        '더', '좀', '가장', '제일', '최대한', '나와', '나랑',
        '사용자위치', '선택한기준장소', '기준장소', '기준위치', '현재선택한', '내', '제', '우리',
        '에서', '의', '를', '로', '기준으로',
        *[word for words in REGION_WORDS.values() for word in words],
    ]
    return re.fullmatch('(?:' + '|'.join(context_words) + ')+', before) is None


def _need_location(state, radius):
    result = _response(
        '가까운 장소를 찾으려면 위치 사용에 동의한 뒤 브라우저 권한을 허용해 주세요. '
        '위치를 사용하지 않으면 지역·음식·테마로 계속 찾을 수 있습니다.',
        state, 'location_consent', 'clarification',
        quick=[{'label': '관광지 찾기', 'message': '관광지 추천'}, {'label': '먹거리 찾기', 'message': '먹거리 추천'}],
    )
    result.update(needs_location=True, location_status='not_provided', radius_km=radius)
    return result


def _search_limits(message):
    """Read supported straight-line distances and result counts before stripping punctuation."""
    raw = unicodedata.normalize('NFKC', message).casefold()
    decimal = r'[+-]?\d+(?:\.\d+)?'
    # Consume grouped and scientific forms as whole tokens before rejecting them.
    number = rf'(?<![\d.,+\-a-z]){decimal}(?:\s*[e,]\s*{decimal})*'
    distance = re.findall(rf'({number})\s*(?:km|킬로미터)', raw)
    if distance or re.search(r'반경|\bkm\b|킬로미터|[0-9.]\s*(?:km|m\b|미터)', raw):
        range_or_lower_bound = re.search(r'[~∼]|(?:km|킬로미터)\s*(?:이상|초과|보다\s*(?:멀|먼)|부터)', raw)
        if (len(distance) != 1 or range_or_lower_bound or not re.fullmatch(decimal, distance[0])
                or not 1 <= float(distance[0]) <= 100):
            return None, None, '직선거리 반경은 1~100km에서 한 값으로 입력해 주세요. 예를 들어 ‘내 근처 반경 5km 카페 추천’이라고 물어볼 수 있어요.'
    count_pattern = rf'({number}|(?<![가-힣])(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열))\s*(?:곳|군데|개(?!월))'
    counts = re.findall(count_pattern, raw)
    word_count = {'한': 1, '두': 2, '세': 3, '네': 4, '다섯': 5}
    count = None
    if counts:
        count = word_count.get(counts[0])
        if count is None and re.fullmatch(r'\d+', counts[0]):
            count = int(counts[0])
        if len(counts) != 1 or count is None or not 1 <= count <= PAGE_SIZE:
            return None, None, '한 번에 1~5곳을 보여드릴 수 있어요. 원하는 수를 고르거나 ‘다른 곳 추천’으로 이어서 찾아보세요.'
    return float(distance[0]) if distance else None, count, None


def _requested_region(norm):
    regions = {region for region, words in REGION_WORDS.items() if any(word in norm for word in words)}
    words = ('제주전체', '지역초기화', '전체지역')
    if any(word in norm for word in words):
        regions.add('all')
    region_only = norm in words or any(
        re.fullmatch(word + r'(?:로|는|에서|어때|어때요|는어때|는어때요|로바꿔줘|로바꿔주세요)?', norm)
        for region_words in REGION_WORDS.values() for word in region_words
    )
    return regions, region_only


def _unsupported_condition(norm, recommend):
    if any(word in norm for word in ['피하', '피해서', '피해줘', '추천하지', '추천안', '안추천',
                                     '싫어', '싫다', '말고', '빼고', '빼줘', '빼주', '빼줄', '제외',
                                     '아닌', '안갈', '안가고', '가지않', '가지말', '원하지않']):
        return 'clarify_negation', '제외 조건을 이 상담에서 적용할 수 없어요. 원하는 조건만 ‘서부 박물관 추천’처럼 입력해 주세요.'
    access_condition = any(word in norm for word in [
        '반려견', '반려동물', '애견', '강아지', '휠체어', '무장애', '계단', '유모차', '수영가능', '물놀이가능', '안전한',
    ])
    if access_condition and (recommend or any(word in norm for word in ['동반', '계단없는', '계단이없는', '함께갈'])):
        return 'clarify_access', '요청하신 동반·시설·접근 조건을 확인할 수 있는 자료가 없어요. 해당 조건 없이 장소를 찾은 뒤 공식 안내에서 방문 조건을 확인해 주세요.'
    if not recommend:
        return None, None
    if re.search(r'(?:차|자동차|도보|걸어서|버스|택시)로?\d+분|(?:버스|대중교통|택시).*(?:갈수|갈만|추천|접근)|(?:분|시간)(?:이내|안에|거리)', norm):
        return 'clarify_transport', '상담의 거리 검색은 직선거리만 지원해요. 이동시간이나 버스 접근 조건을 확인한 추천을 제공할 수 없습니다.'
    if any(word in norm for word in ['무료', '이하인', '입장료없는', '원미만', '원이하']):
        return 'clarify_price', '현재 입장료나 가격으로 장소를 걸러낼 수 없어요. 특정 장소 이름을 입력하면 확보된 요금 기록을 확인할 수 있습니다.'
    return None, None


def _visit_review_card(root, item):
    if item.get('kind') != 'attraction' or item.get('source_overlap_verified') is not True:
        return item
    from .place_trust import place_trust

    trust = place_trust(root, item, purpose='manual')
    if trust['automatic_eligible']:
        return item
    specific = trust['checks']['specific_review']
    official = next((source for source in trust['sources'] if source['kind'] == 'tourism_guide'), {})
    return {
        **item,
        'visit_review': {
            'required': True,
            'reasons': trust['reasons'],
            'source_url': specific.get('source_url') or official.get('url'),
            'reviewed_at': specific.get('reviewed_at') or official.get('checked_at'),
        },
    }

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
    endings = [
        '알려주실수있나요', '알려주세요', '알려줘', '보여주세요', '보여줘', '어떻게되나요',
        '어떻게돼요', '어떻게돼', '어떤가요', '어디인가요', '뭐인가요', '어디야', '뭐야',
        '가능한가요', '가능해요', '가능해', '에열어요', '까지하나요', '인가요', '이야', '나요', '좀', '은', '는', '이', '가', '요', '야',
    ]
    for _ in range(3):
        match=next((word for word in endings if norm.endswith(word)),None)
        if not match:break
        norm=norm[:-len(match)]
    return norm in {'주소','위치','어디','어디있','어디에있','어디쯤','영업시간','운영시간','개장시간','입장료','이용료','요금','가격','주차','주차정보','휠체어','휠체어정보','전화','전화번호','연락처','출처','자료원문','근거','몇시'}

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
    field_after_particle = after[:1] in {'은', '는', '이', '가'} and _short_field_followup(after[1:])
    return not after or _short_field_followup(after) or field_after_particle or after in {'정보','소개','소개해줘','알려줘','알려주세요','상세','상세정보','정보알려줘','정보좀알려줘','자세히알려줘','에대해알려줘','은어떤곳이야','는어떤곳이야','어떤곳이야','어때','어때요','추천','추천해줘','궁금해','가궁금해'}

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
    for key,words in [('hours',['영업','운영시간','개장','개방시간','몇시','언제열']),('fee',['요금','입장료','이용료','가격','무료']),('parking',['주차']),('wheelchair',['휠체어','무장애','접근성']),('phone',['전화','연락처']),('address',['주소','어디있','어디에있','어디쯤','어디야','어디예요','어디인가요','위치']),('source',['출처','자료원문','근거'])]:
        if any(word in norm for word in words):return key
    return None

def _place_answer(root,p,message,state):
    p,text=_read(root,p['id']);topic='food' if p.get('kind')=='food' else 'tourism'
    if state['topic'] != topic:
        state.update(last_query='', offset=0, nearby=False, radius_km=DEFAULT_RADIUS, result_limit=PAGE_SIZE)
    state.update(topic=topic,last_place_id=p['id'])
    state['choice_ids'] = [p['id']]
    key=_field(message);tags=p.get('observed_tags') or {}
    labels={'hours':('영업시간',tags.get('opening_hours')),'fee':('이용료',tags.get('charge') or tags.get('fee')),'parking':('주차',tags.get('parking')),'wheelchair':('휠체어',tags.get('wheelchair')),'phone':('전화',tags.get('phone') or tags.get('contact:phone'))}
    if key in labels:
        label,value=labels[key];text=(f"{p['name']}의 원자료 {label} 표기는 ‘{value}’입니다. 현재 상태를 확인한 안내가 아니므로 방문 전에 원문과 운영기관에서 확인해 주세요." if value else f"{p['name']}의 {label} 정보는 확보한 원자료에 없습니다. 확인되지 않은 값을 안내하지 않습니다. 아래 상세 카드의 자료 원문에서 운영기관 안내를 확인해 주세요.")
    elif key=='address':text=(f"{p['name']}의 기록 주소는 {p['address']}입니다. " if p.get('address') else f"{p['name']}의 주소는 원자료에 없습니다. ")+(f"참고 좌표는 {p['latitude']:.5f}, {p['longitude']:.5f}이며 실제 입구는 별도 확인해 주세요." if p.get('latitude') is not None else '좌표가 없어 지도에서 정확한 위치와 거리를 확인할 수 없습니다.')
    elif key=='source':text=f"{p['name']}의 출처는 {p.get('source_name') or p.get('source_platform') or '공개 원자료'}입니다. 기록 기준: {p.get('source_date') or '표기 없음'}, 수집 기준: {p.get('snapshot_at') or '표기 없음'}. 아래 카드의 출처 링크를 확인하세요."
    return _response(text,state,'place_'+(key or 'details'),'prepared_text',[_visit_review_card(root, p)],[{'label':'주소·위치','message':'주소 알려줘'},{'label':'영업시간 기록','message':'영업시간 알려줘'},{'label':'요금 기록','message':'입장료 알려줘'},{'label':'주차 정보','message':'주차 정보 알려줘'},{'label':'처음으로','message':'처음으로'}])

def _ask_place(state):
    return _response(
        '해당 질문의 장소를 확인하지 못했습니다. ‘함덕해수욕장 주소’, ‘성산일출봉 정보’처럼 '
        '확보된 장소 이름을 함께 입력하거나 검색 결과의 상세 보기를 눌러 주세요.',
        state, 'ask_place', 'clarification',
    )


def chat_reply(root, body, *, learned_search=True):
    root = Path(root)
    if not isinstance(body, dict):
        raise ValueError('JSON 객체가 필요합니다.')
    message = body.get('message', '')
    if not isinstance(message, str) or len(message) > 300:
        raise ValueError('질문은 300자 이내 문자열로 입력하세요.')
    restart_page = body.get('restart_page', False)
    if not isinstance(restart_page, bool):
        raise ValueError('restart_page는 불리언이어야 합니다.')
    message = message.strip()
    norm = _norm(message)
    state = _state(root, body.get('state'))
    original_state = {**state, 'choice_ids': list(state['choice_ids'])}
    location, location_status, declined = _location_request(body)
    explicit_nearby = _nearby_words(norm)
    next_page = any(word in norm for word in ['다른곳', '다른장소', '다른거', '더보여', '더추천', '다음추천'])
    faq_path = root / 'config/chatbot_faq.json'
    faq = _faq(str(faq_path.resolve()), faq_path.stat().st_mtime_ns)
    if not norm or norm in {'처음으로', '처음', '메뉴', '시작', '안녕', '안녕하세요', '대화초기화', '리셋'}:
        return _faq_response(faq[0], _state(root, None))
    for item in faq[1:]:
        if any(_norm(word) == norm for word in item.get('exact', [])):
            return _faq_response(item, state)
    for item in faq[1:]:
        if item['id'] in {'data_help', 'itinerary_help', 'no_llm', 'offline_help', 'privacy_help', 'scope_help'} and any(
            _norm(word) in norm for word in item.get('keywords', [])
        ):
            return _faq_response(item, state)

    if any(word in norm for word in ['대통령', '주가', '주식', '삼성전자', '선거', '정치', '코딩',
                                     '파이썬', '양자역학', '미분방정식', '진단', '처방', '법률']):
        return _fallback(original_state)

    recommend = any(word in norm for word in ['추천', '찾아', '찾기', '갈수있', '갈만', '갈곳', '가볼', '둘러', '보여'])
    unsupported, explanation = _unsupported_condition(norm, recommend)
    if unsupported:
        return _response(explanation, original_state, unsupported, 'clarification')
    realtime = any(word in norm for word in ['실시간', '날씨', '비와', '비오나', '대기시간', '잔여주차',
                                               '버스시간', '배시간표', '배편시간', '시간표', '운행시간',
                                               '운항시간', '교통상황', '문열었', '문닫았', '문연',
                                               '영업중', '운영중', '열려있는'])
    has_current_filter = any(word in norm for word in ['지금', '오늘', '현재', '당일', '내일', '주말', '주중',
                                                                  '월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']) and any(
        word in norm for word in ['영업', '운영', '개장', '개방', '입장', '휴무', '문열', '문닫', '열려']
    )
    if realtime or has_current_filter or ('지금' in norm and not explicit_nearby):
        return _response(
            '현재 날씨·영업·교통·잔여 주차면·대기시간은 이 오프라인 자료로 확인할 수 없습니다. '
            '장소의 기록 정보는 안내할 수 있어요. 현재 정보는 운영기관의 최신 안내를 확인해 주세요.',
            original_state, 'realtime_unavailable',
        )
    if re.search(r'\d{2}\.\d+\s*[,/]\s*1\d{2}\.\d+', message):
        return _response(
            '질문에 적은 숫자를 기기 위치로 읽거나 자동 사용하지 않습니다. '
            '챗봇의 ‘내 위치 사용’에 동의하거나 지도에서 기준 장소를 직접 골라 주세요.',
            original_state, 'location_help',
        )
    radius, result_limit, limit_error = _search_limits(message)
    if limit_error:
        return _response(limit_error, original_state, 'clarify_limits', 'clarification')
    explicit_radius = radius is not None
    explicit_nearby = explicit_nearby or explicit_radius
    if explicit_nearby and _named_nearby(norm):
        return _response(
            '이름으로 적은 장소나 앞서 살펴본 장소는 지도에서 기준 위치로 고른 뒤 주변을 찾아 주세요. '
            '‘내 근처 카페 추천’은 동의한 기기 위치나 직접 고른 기준 장소로 검색합니다.',
            original_state, 'nearby_help', 'clarification',
        )

    regions, region_only = _requested_region(norm)
    if len(regions) > 1:
        return _response('검색할 지역을 하나만 골라 주세요. 예를 들어 ‘북부 해변 추천’이나 ‘제주 전체 해변 추천’이라고 물어보세요.',
                         original_state, 'clarify_regions', 'clarification')
    explicit_region = bool(regions)
    if explicit_region:
        state['region'] = next(iter(regions))

    ordinal = re.fullmatch(r'(첫번째|두번째|세번째|네번째|다섯번째|[1-9]번)(?:장소)?(.*)', norm)
    if ordinal and _place_tail(ordinal[2]):
        words = ['첫번째', '두번째', '세번째', '네번째', '다섯번째']
        index = words.index(ordinal[1]) if ordinal[1] in words else int(ordinal[1][0]) - 1
        choices = state['choice_ids']
        if index < len(choices):
            return _place_answer(root, _read(root, choices[index])[0], message, state)
        return _response('현재 답변에 그 번호의 장소가 없습니다. 관광지나 먹거리를 먼저 찾아 주세요.',
                         original_state, 'clarify_choice', 'clarification')

    foods = [key for key, words in FOODS.items() if any(_norm(word) in norm for word in words)]
    themes = [key for key, words in THEMES.items() if any(_norm(word) in norm for word in words)]
    food = foods[0] if foods else None
    theme = themes[0] if themes else None
    entities = _entity(root, message)
    field = _field(message)
    if (food or theme) and not field and not any(word in norm for word in ['정보', '상세', '자세히']):
        generic_terms = {_norm(word) for group in (FOODS, THEMES) for key, words in group.items() for word in [key, *words]}
        entities = [place for place in entities if _norm(place['name']) not in generic_terms]
    if not explicit_nearby and entities and _place_question(message, entities) and (
        not recommend or not food and not theme or any(_norm(place['name']) in norm for place in entities)
    ):
        if len(entities) == 1:
            return _place_answer(root, entities[0], message, state)
        state.update(topic='place', choice_ids=[place['id'] for place in entities], last_place_id=None)
        cards = [_visit_review_card(root, place) for place in entities]
        return _response(
            '같거나 비슷한 이름의 기록이 여러 개입니다. 주소와 출처를 보고 원하는 장소를 선택하거나 번호로 알려주세요.',
            state, 'clarify_entity', 'clarification', cards,
            [{'label': f'{i+1}번 {place["name"][:18]}', 'message': f'{i+1}번'} for i, place in enumerate(cards)],
        )
    if field and _short_field_followup(message) and state.get('last_place_id'):
        return _place_answer(root, _read(root, state['last_place_id'])[0], message, state)

    for item in faq[1:]:
        nearby_usage = item['id'] == 'nearby_help' and any(word in norm for word in ['사용법', '방법', '권한', '동의'])
        if (item['id'] != 'nearby_help' or nearby_usage) and any(_norm(word) in norm for word in item.get('keywords', [])):
            return _faq_response(item, state)
    if field and not explicit_nearby:
        return _ask_place(original_state)

    food_requested = bool(food or any(word in norm for word in ['먹거리', '맛집', '식당추천']) or
                          explicit_nearby and any(word in norm for word in ['식당', '음식']))
    tourism_requested = bool(theme or any(word in norm for word in ['관광', '여행지', '명소']))
    if len(foods) > 1 or len(themes) > 1 or food_requested and tourism_requested:
        return _response('음식이나 관광 테마를 한 가지씩 골라 주세요.', original_state,
                         'clarify_topics', 'clarification')
    topic = None
    if food_requested:
        topic = 'food'
    elif tourism_requested or '가볼' in norm:
        topic = 'tourism'

    prior_topic = original_state['topic']
    named_topic = topic is not None
    closer_followup = bool(re.fullmatch(r'(?:좀)?더가까운(?:곳|장소)(?:추천해줘|추천)?', norm))
    followup = next_page or region_only or explicit_nearby or result_limit is not None or explicit_region and recommend
    if topic is None and followup and prior_topic in {'food', 'tourism'}:
        topic = prior_topic
    elif topic is None and explicit_nearby:
        topic = 'tourism'
    if topic is None:
        return _ask_place(original_state) if '정보' in norm or field or '자세히' in norm else _fallback(original_state)

    query_changed = bool(food or theme or topic != prior_topic)
    new_constraints = explicit_region or explicit_nearby or result_limit is not None or query_changed or restart_page
    paging = next_page and not new_constraints
    nearby = explicit_nearby or next_page and original_state['nearby'] and not explicit_region
    inherit_query = followup and topic == prior_topic and (next_page or not named_topic)
    query = food or theme or (original_state['last_query'] if inherit_query else '')
    if radius is None:
        radius = original_state['radius_km'] if nearby and (next_page or closer_followup) else DEFAULT_RADIUS
    if result_limit is None:
        result_limit = original_state['result_limit'] if next_page or closer_followup else PAGE_SIZE
    offset = min(1000, original_state['offset'] + result_limit) if paging else 0
    if nearby:
        if location_status == 'outside_jeju':
            result = _response(
                '제주 범위 밖의 위치로는 주변을 계산할 수 없어요. 지도에서 제주 내 기준 장소를 고르거나 지역 이름으로 질문해 주세요.',
                original_state, 'location_outside_jeju', 'clarification',
            )
            result.update(location_status='outside_jeju', radius_km=radius)
            return result
        if location is None and not declined:
            return _need_location(original_state, radius)
        if location is None and (explicit_radius or radius != DEFAULT_RADIUS):
            return _response('반경 조건을 적용하려면 기준 위치가 필요해요. 지도에서 기준 장소를 고르거나 지역 이름으로 다시 물어봐 주세요.',
                             original_state, 'location_help', 'clarification')
        if location and not explicit_region and not (closer_followup or next_page and original_state['nearby']):
            state['region'] = 'all'
    else:
        location, location_status, declined = None, 'not_requested', False

    state.update(topic=topic, last_query=query, offset=offset, last_place_id=None, nearby=location is not None,
                 radius_km=radius, result_limit=result_limit)
    origin_label = '선택한 기준 장소' if location and location.get('source') == 'manual' else '동의한 기기 위치'
    search_request = {'query': query, 'region': state['region'], 'location': location, 'radius_km': radius}
    if topic == 'tourism':
        from .tourism import search_tourism
        result = search_tourism(root, {**search_request, 'kind': 'attraction', 'limit': 100, 'offset': 0}, learned=learned_search)
        rows = _dedupe_candidates(result['items'])
        reply = (f"{REGION_LABELS[state['region']]}에서 {query+' 관련 ' if query else ''}교차확인 관광지 기록을 찾아봤어요. "
                 '명부와 지도에서 확인한 이름·위치와 관광 분류를 기준으로 검색했습니다. 인기도 순위는 아닙니다.')
    else:
        from .discovery import discovery_recommend
        result = discovery_recommend(root, {**search_request, 'limit': 12}, learned=learned_search)
        rows = _dedupe_candidates(result['restaurants'] + ([] if location else result['unmapped_restaurants']))
        reply = (f"{REGION_LABELS[state['region']]}의 {query or '먹거리'} 관련 업소 기록입니다. "
                 '업소명·업종·기록된 분류를 기준으로 찾았습니다. 실제 메뉴와 영업 여부는 방문 전 확인해 주세요.')
    cards = [_visit_review_card(root, item) for item in rows[offset:offset + result_limit]]
    local_area = f" · {REGION_LABELS[state['region']]} 조건" if state['region'] != 'all' else ''
    if location:
        subject = (query + ' 관련 업소' if query else '먹거리 업소') if topic == 'food' else (
            query + ' 관련 교차확인 관광지' if query else '교차확인 관광지')
        order = '관련도 분류 후 같은 분류에서 가까운 순입니다.' if query else '가까운 직선거리 순입니다.'
        limits = '실제 메뉴·맛·인기·현재 영업은 미확인이며 도로 거리와 다릅니다.' if topic == 'food' else (
            '현재 운영·실제 입구·인기도는 미확인이며 도로 거리와 다릅니다.')
        reply = f'{origin_label}에서 직선거리 {radius:g}km 안에서 좌표가 있는 {subject} 기록을 찾았어요{local_area}. {order} {limits}'
    elif declined:
        reply = '위치를 사용하지 않아 가까운 순서나 반경 검색을 적용하지 않았습니다. ' + reply
    state['choice_ids'] = [place['id'] for place in cards]
    if not cards:
        reply = (f'{origin_label}의 직선거리 {radius:g}km 반경{local_area}에서 보여드릴 기록이 없습니다. '
                 '다른 음식·테마나 지역 검색을 선택해 주세요.' if location else
                 '이 조건에서 보여드릴 기록이 없습니다. 다른 테마나 더 넓은 지역을 골라 주세요.')
    if location and location_status == 'low_accuracy':
        reply += ' 기준 위치 오차가 5km보다 커 거리·반경에 큰 오차가 있을 수 있습니다.'
    quick = [
        {'label': '다른 곳 보기', 'message': '다른 곳 추천'}, {'label': '북부', 'message': '북부'},
        {'label': '동부', 'message': '동부'}, {'label': '서부', 'message': '서부'},
        {'label': '남부', 'message': '남부'}, {'label': '처음으로', 'message': '처음으로'},
    ]
    response = _response(reply, state, topic+'_search', 'model_search' if learned_search else 'reference_lookup', cards, quick)
    response.update(location_used=location is not None, location_status=location_status,
                    location_source=location.get('source') if location else None,
                    radius_km=radius if location else None,
                    distance_basis='provided_location_straight_line' if location else 'not_available')
    return response
