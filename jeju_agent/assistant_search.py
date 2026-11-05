"""Offline retrieval over Jeju records with excerpts from the matching source."""
from collections import Counter
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata

from .assistant_intent import _REGIONS as REGION_ALIASES
from .discovery import REGIONS, RULES, RULE_TRIGGERS, _load_model, _point, _query_vector, _tokens
from .place_trust import place_trust
from .tourism_access import approved_places


HUB_PLACES = 'https://www.jejudatahub.net/data/view/data/1349'
HUB_FOOD = 'https://www.jejudatahub.net/data/view/data/780'
STOP_WORDS = {
    '제주', '제주도', '관광지', '여행지', '관광', '여행', '명소', '추천', '추천해', '추천해줘',
    '추천해주세요', '검색', '검색해줘', '찾아', '찾아줘', '찾아주세요', '알려줘', '알려주세요', '알려',
    '보여줘', '보여주세요', '장소', '정보', '소개', '후보', '모습', '만한', '보고', '싶어',
    '어떤', '있는', '좋은', '좋을까', '곳', '음식점', '식당', '맛집', '있어', '주세요',
}
VIEWING_WRAPPER = re.compile(r'\b(?:바라볼|살펴볼|둘러볼|볼)\s*(?:수\s*있는|만한)\b')
THEME_TERMS = {
    '옛제주': ('전통 가옥', '생활문화', '민속', '조선', '옛 관아'),
    '옛모습': ('전통 가옥', '생활문화', '민속', '조선', '옛 관아'),
}
UNVERIFIABLE = (
    '빼고', '제외', '말고', '아닌', '금지', '현재영업', '지금', '영업중', '영업시간',
    '오늘열', '입장료', '예약가능', '주차가능', '휠체어', '유모차', '반려견', '반려동물',
    '수영가능', '실시간', '근처', '가까운', '주변', '반경', '혼잡', '메뉴',
)


def _words(value):
    return re.findall(r'[가-힣a-z0-9]+', unicodedata.normalize('NFKC', value).casefold())


def _request_terms(query, region):
    terms = []
    normalized = unicodedata.normalize('NFKC', query)
    for word in _words(VIEWING_WRAPPER.sub(' ', normalized)):
        if word in STOP_WORDS:
            continue
        # Strip common Korean particles only when enough of the word remains.
        stem = re.sub(r'(?:에서|으로|에게|은|는|을|를|에|의)$', '', word)
        if stem in STOP_WORDS:
            continue
        term = stem if len(stem) >= 2 else word
        if REGION_ALIASES.get(term) == region:
            continue
        if len(term) >= 2 and term not in STOP_WORDS:
            terms.append(term)
    return list(dict.fromkeys(terms))


def _matching_terms(terms, source_text):
    compact = ''.join(_words(source_text))
    return [term for term in terms if ''.join(_words(term)) in compact]


def _vector(words, idf):
    weights = {term: (1 + math.log(count)) * idf[term]
               for term, count in Counter(_tokens(words)).items() if term in idf}
    norm = math.sqrt(sum(weight * weight for weight in weights.values())) or 1
    return {term: weight / norm for term, weight in weights.items()}


def _similarity(query_vector, document, idf):
    return sum(weight * query_vector.get(term, 0) for term, weight in _vector(document, idf).items())


def _evidence(text, source, terms):
    return {'text': text, 'source_url': source['url'], 'source_name': source['name'],
            'retrieved_at': source['source_date'], 'date_kind': source['date_kind'],
            'matched_terms': terms}


def _attractions(root, terms, expansions, region, limit):
    documents = []
    for item in approved_places(root):
        if region != 'all' and item['region'] != region:
            continue
        hub = item['cross_source']['hub']
        if hub.get('source_url') != HUB_PLACES:
            continue
        trust = place_trust(root, item, purpose='automatic')
        if not trust['automatic_eligible']:
            continue
        guide = item['tourism_guide']
        primary = {'name': '제주데이터허브 여행장소 명부', 'url': HUB_PLACES, 'dataset_id': 1349,
                   'source_date': hub.get('source_date'), 'date_kind': 'hub_reference'}
        secondary = {'name': guide['source_name'], 'url': guide['source_url'],
                     'source_date': guide['retrieved_at'], 'date_kind': 'guide_review'}
        hub_text = ' '.join(filter(None, [hub['name'], hub.get('address')]))
        guide_sentences = re.split(r'(?<=[.!?])\s+', guide['summary'])
        evidence = [(hub_text, primary)] + [(sentence, secondary) for sentence in guide_sentences]
        corpus_text = f"{hub['name']} {hub_text} {guide['summary']}"
        documents.append((item, trust, primary, evidence, corpus_text))

    frequencies = Counter()
    for _, _, _, _, corpus_text in documents:
        frequencies.update(set(_tokens(corpus_text)))
    idf = {term: math.log((1 + len(documents)) / (1 + count)) + 1 for term, count in frequencies.items()}
    query_vector = _vector(' '.join(terms + expansions), idf)
    if not query_vector:
        return []

    ranked = []
    for item, trust, primary, passages, corpus_text in documents:
        if len(_matching_terms(terms, corpus_text)) != len(terms):
            continue
        matches = [(text, source, _matching_terms(terms + expansions, text)) for text, source in passages]
        matches = [match for match in matches if match[2]]
        if not matches:
            continue
        text, source, matched = max(matches, key=lambda match: _similarity(query_vector, match[0], idf))
        name_terms = _matching_terms(terms, item['name'])
        ranked.append((not name_terms, -_similarity(query_vector, corpus_text, idf), item['name'], item['id'], {
            'id': item['id'], 'name': item['name'], 'kind': 'attraction', 'category': item['category'],
            'region': item['region'], 'address': item['cross_source']['hub'].get('address'),
            'primary_source': primary, 'matched_evidence': _evidence(text, source, matched),
            'sources': trust['sources'], 'source_status': 'cross_source_verified',
            'location_basis': 'matched_map_reference', 'automatic_eligible': True,
            'current_opening_verified': False, 'limitations': trust['warnings'],
            'ranking_method': 'hub_and_reviewed_guide_character_tfidf',
        }))
    return [row[-1] for row in sorted(ranked, key=lambda row: row[:4])[:limit]]


def _food(root, terms, region, limit):
    database = root / 'data_reference' / 'discovery.sqlite'
    model_path = root / 'models_discovery' / 'tfidf_model.json'
    model = _load_model(str(model_path.resolve()), model_path.stat().st_mtime_ns,
                        str(database.resolve()), database.stat().st_mtime_ns)
    query = ' '.join(terms)
    vector, _, _ = _query_vector(query, model)
    if not vector:
        return []

    # Enforce the provenance and lexical constraints before applying LIMIT.
    # The learned weights and postings are from the existing read-only index.
    clauses = ['r.source_platform = ?', 'r.source_url = ?']
    parameters = [value for pair in vector.items() for value in pair] + ['jeju_datahub', HUB_FOOD]
    if '편의점' not in terms:
        clauses.append("r.category NOT IN ('편의점', '극장', '공항', '유원지', '백화점', '출장조리')")
    if region != 'all':
        clauses.append('r.region = ?')
        parameters.append(region)
    name_address_category = "lower(replace(r.name || ' ' || coalesce(r.address, '') || ' ' || coalesce(r.category, ''), ' ', ''))"
    evidence_terms = []
    for term in terms:
        alternatives = sorted({term} | {value for group, triggers in RULE_TRIGGERS.items()
                                        if term in triggers for value in RULES[group]})
        evidence_terms.extend(value for value in alternatives if value not in evidence_terms)
        clauses.append('(' + ' OR '.join(f'instr({name_address_category}, ?) > 0' for _ in alternatives) + ')')
        parameters.extend(''.join(_words(value)) for value in alternatives)
    placeholders = ','.join('(?,?)' for _ in vector)
    sql = f'''WITH query_terms(term_id, weight) AS (VALUES {placeholders})
        SELECT r.*, SUM(p.weight * q.weight) AS similarity
        FROM postings p JOIN query_terms q ON p.term_id = q.term_id
        JOIN restaurants r ON r.doc_id = p.doc_id
        WHERE {' AND '.join(clauses)}
        GROUP BY r.doc_id ORDER BY similarity DESC, r.name, r.id LIMIT ?'''
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(sql, parameters + [limit]).fetchall()

    results = []
    for row in rows:
        primary = {'name': '제주데이터허브 음식점 인허가 기록', 'url': HUB_FOOD, 'dataset_id': 780,
                   'source_date': row['source_date'], 'date_kind': 'permit_dataset_reference_date'}
        text = ' · '.join(filter(None, [row['name'], row['category'], row['address']]))
        item = {'id': row['id'], 'name': row['name'], 'kind': 'food', 'category': row['category'],
                'region': row['region'], 'address': row['address'], 'primary_source': primary,
                'matched_evidence': _evidence(text, primary, _matching_terms(evidence_terms, text)),
                'source_status': 'hub_permit_reference', 'location_basis': 'address_only',
                'current_opening_verified': False, 'menu_verified': False,
                'automatic_eligible': False, 'ranking_method': 'hub_permit_indexed_character_tfidf',
                'limitations': ['제주데이터허브 인허가 기준일의 상호·업종·주소입니다. 현재 영업·메뉴는 방문 전 확인하세요.']}
        coordinate = _point(row['latitude'], row['longitude'])
        if row['coordinate_match'] == 'exact_name_and_full_address' and row['coordinate_source'] and coordinate:
            source = json.loads(row['coordinate_source'])
            if (source.get('dataset_id') == '1349' and source.get('source_url') == HUB_PLACES
                    and source.get('join_method') == 'exact_name_and_full_address_after_nfkc_whitespace_normalization'):
                item.update(location_basis='exact_name_full_address_hub_join', latitude=coordinate[0],
                            longitude=coordinate[1], coordinate_source=source)
                item['limitations'].append('상호·전체주소가 일치한 허브 1349의 참고 좌표입니다. 실제 입구는 방문 전 확인하세요.')
        if item['location_basis'] == 'address_only':
            item['limitations'].append('주소만 제공하는 기록입니다. 거리·경로 계산에 사용하지 않습니다.')
        results.append(item)
    return results


def search_assistant(root, query, limit=5, *, kind='attraction', region='all'):
    """Search trusted visitor candidates or permit records using local TF-IDF."""
    if not isinstance(query, str) or len(query) > 160:
        raise ValueError('장소 검색어는 160자 이내 문자열이어야 합니다.')
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError('검색 개수는 1~12 정수여야 합니다.')
    if not isinstance(kind, str) or kind not in {'attraction', 'food'}:
        raise ValueError('관광지 또는 음식점 유형을 확인하세요.')
    if not isinstance(region, str) or region not in REGIONS:
        raise ValueError('지원하지 않는 지역입니다.')
    compact = ''.join(_words(query))
    if any(marker in compact for marker in UNVERIFIABLE):
        return []
    terms = _request_terms(query, region)
    if kind == 'food':
        return _food(Path(root), terms, region, limit) if terms else []
    expansions = list(dict.fromkeys(term for phrase, related in THEME_TERMS.items()
                                    if phrase in compact for term in related))
    return _attractions(Path(root), terms, expansions, region, limit) if terms or expansions else []
