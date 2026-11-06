"""Dated travel references retrieved with a locally fitted character TF-IDF model."""
from collections import Counter
import copy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata


def _compact(text):
    return ''.join(re.findall(r'[가-힣a-z0-9]+', unicodedata.normalize('NFKC', text).casefold()))


def _grams(text):
    text = _compact(text)
    return [text[i:i+n] for n in (2, 3) for i in range(len(text)-n+1)]


def _vector(text, idf):
    weights = {t: (1 + math.log(c)) * idf[t] for t, c in Counter(_grams(text)).items() if t in idf}
    norm = math.sqrt(sum(v*v for v in weights.values())) or 1
    return {t: v/norm for t, v in weights.items()}


@lru_cache(maxsize=4)
def _load(path, modified, size, receipt_modified, learned=True):
    file = Path(path)
    raw = file.read_bytes()
    receipt = json.loads((file.parent.parent / 'data_raw' / 'hub_v18' / 'BUILD_RECEIPT.json').read_text(encoding='utf-8'))
    if hashlib.sha256(raw).hexdigest() != receipt['output_sha256']:
        raise ValueError('여행 참고자료 무결성 확인에 실패했습니다.')
    data = json.loads(raw)
    if data.get('schema_version') != 1 or any(item.get('route_eligible') is not False for item in data['items']):
        raise ValueError('여행 참고자료 형식을 확인하세요.')
    vectors = [_vector(item['search_text'], data['search_model']['idf']) for item in data['items']] if learned else None
    return data, vectors


STOP = {'제주', '제주도', '관광', '여행', '추천', '추천해줘', '찾아줘', '찾아주세요', '보여줘', '알려줘', '있는', '있고', '좋은',
        '곳', '곳을', '장소', '정보', '해변', '해수욕장', '올레', '올레길', '산책', '산책로', '숲길', '코스', '여행지', '정도',
        '걷기', '걷고', '싶어', '싶어요', '이내', '안에', '시간', '분', '무장애', '휠체어', '유모차'}


def _terms(query):
    query = re.sub(r'\d+(?:\.\d+)?\s*(?:시간|분|km|킬로미터)', ' ', query, flags=re.I)
    terms = []
    for token in re.findall(r'[가-힣a-z0-9]+', unicodedata.normalize('NFKC', query).casefold()):
        token = re.sub(r'(?:에서|으로|을|를|은|는|의|에)$', '', token)
        if len(token) > 1 and token not in STOP:
            terms.append(token)
    return list(dict.fromkeys(terms))


def search_travel_context(root, *, kind='walk', query='', max_minutes=None, limit=8, learned=True):
    """Search historical source facts. Results are not automatic route candidates."""
    if not isinstance(kind, str) or kind not in {'walk', 'beach', 'accessible', 'amenity'}:
        raise ValueError('지원하지 않는 여행정보 유형입니다.')
    if not isinstance(query, str) or len(query) > 160:
        raise ValueError('검색어는 160자 이내 문자열이어야 합니다.')
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('표시 개수는 1~20 정수여야 합니다.')
    if max_minutes is not None and (type(max_minutes) not in (int, float) or not math.isfinite(max_minutes) or not 1 <= max_minutes <= 1440):
        raise ValueError('걷기 시간은 1~1440분 범위의 숫자여야 합니다.')
    if max_minutes is not None and kind != 'walk':
        raise ValueError('시간 제한은 걷기 코스에만 적용할 수 있습니다.')
    root = Path(root)
    path = root / 'data_reference' / 'travel_context_v18.json'
    receipt = root / 'data_raw' / 'hub_v18' / 'BUILD_RECEIPT.json'
    data, vectors = _load(str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size, receipt.stat().st_mtime_ns, learned)
    if learned:
        model = {k: v for k, v in data['search_model'].items() if k != 'idf'}
        model['vocabulary'] = len(data['search_model']['idf'])
    else:
        model = {'algorithm': 'verified_travel_reference_lookup', 'learned_component': None}
    source_ids = {'walk': {'hub871', 'hub497_origin'}, 'beach': {'hub784'}, 'accessible': {'hub858'}, 'amenity': {'public15109369'}}[kind]
    notes = {
        'walk': ['올레는 2021년 공개 미리보기 19코스만 포함합니다. 전 코스 목록이 아닙니다.',
                 '시간 제한은 제공 소요시간의 상한에 적용하며 이동·복귀·배편을 포함하지 않습니다. 소요시간 미제공 숲길은 제외합니다.'],
        'beach': ['2023년 시설 수·주차 규모이며 현재 시설 운영과 실시간 잔여 주차면은 미확인입니다.'],
        'accessible': ['2021년 무장애 여행지 명부의 위치 기록이며 현재 접근성이나 전체 구간 통행을 보장하지 않습니다.'],
        'amenity': ['2022년 기록이며 운영시간·영업상태는 당시 원문입니다. 현재 이용·주차·충전 가능 여부는 미확인입니다.'],
    }[kind]
    evidence_note = 'TF-IDF 검색 관련성은 실제 이용자 정답으로 평가하지 않았습니다.' if learned else '자료에 명시된 검색어, 시설, 최대 걷기 시간 조건을 확인합니다.'
    response = {'status': 'ok', 'kind': kind, 'query': query,
                'scope': '기준일이 있는 실제 자료의 검색·비교이며 현재 운영·통제·접근성을 확인한 코스가 아닙니다.',
                'model': model, 'available_counts': data['available_counts'],
                'sources': copy.deepcopy([source for source in data['sources'] if source['id'] in source_ids]), 'items': [],
                'limitations': ['모든 결과는 참고자료이며 자동 일정에 편입하지 않습니다.',
                                evidence_note] + notes}
    compact = _compact(query)
    if any(token in compact for token in ('없는', '없고', '말고', '제외', '빼고', '아닌', '않은', '이상', '최소', '넘게')):
        response.update(status='unsupported', message='이 검색은 시설이 있는 조건과 걷기 최대 시간만 지원합니다. 제외 조건·최소 시간은 적용할 수 없습니다.')
        return response
    if any(token in compact for token in ('실시간', '지금영업', '현재영업', '주차가능', '충전가능', '수영가능', '통행가능', '예약가능', '혼잡', '근처', '가까운', '주변')):
        response.update(status='unsupported', message='현재 상태나 가까운 순서는 이 기준일 자료로 확인할 수 없습니다. 시설명·지역명으로 검색하세요.')
        return response
    if max_minutes is None and kind == 'walk':
        match = re.search(r'(\d+(?:\.\d+)?)\s*(시간|분)', query)
        if match:
            max_minutes = float(match[1]) * (60 if match[2] == '시간' else 1)
            if not 1 <= max_minutes <= 1440:
                raise ValueError('걷기 시간은 1~1440분 범위여야 합니다.')
    terms = _terms(query)
    filters = []
    facility_terms = {'화장실': '화장실(동)', '샤워장': '샤워장', '식수대': '식수대', '주차장': '주차규모(대)', '주차': '주차규모(대)'}
    if kind == 'beach':
        for term in list(terms):
            if term in facility_terms:
                filters.append(facility_terms[term])
                terms.remove(term)
    query_vector = _vector(' '.join(terms), data['search_model']['idf']) if learned else {}
    ranked = []
    for index, item in enumerate(data['items']):
        if item['kind'] != kind:
            continue
        if max_minutes is not None and (item.get('max_minutes') is None or item['max_minutes'] > max_minutes):
            continue
        if any((item['known'].get(field) or 0) <= 0 for field in filters):
            continue
        text = _compact(item['search_text'])
        if terms and not all(_compact(term) in text for term in terms):
            continue
        score = sum(value * vectors[index].get(term, 0) for term, value in query_vector.items()) if learned else 0
        duration = item.get('max_minutes')
        ranked.append((-score, duration if duration is not None else 99999, item['name'], item['id'], item))
    ranked.sort(key=lambda row: row[:4])
    for row in ranked[:limit]:
        item = copy.deepcopy(row[-1])
        item.pop('search_text', None)
        item['matched_terms'] = terms
        item['ranking_method'] = model['algorithm'] if terms else 'source_name_and_provided_duration_order'
        response['items'].append(item)
    response['matched_count'] = len(ranked)
    if response['items']:
        returned_sources = {item['source_id'] for item in response['items']}
        response['sources'] = [source for source in response['sources'] if source['id'] in returned_sources]
    response['applied_max_minutes'] = max_minutes
    response['applied_facility_filters'] = filters
    response['message'] = f'기준일 자료에서 {len(ranked)}개 기록을 찾았습니다.' if ranked else '해당 조건을 충족하는 근거가 수록 자료에 없습니다. 다른 조건으로 검색하세요.'
    return response
