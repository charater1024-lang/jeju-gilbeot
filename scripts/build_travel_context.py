"""Build dated travel-reference records and unsupervised search weights from real files."""
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parent.parent


def grams(text):
    text = ''.join(re.findall(r'[가-힣a-z0-9]+', unicodedata.normalize('NFKC', text).casefold()))
    return [text[i:i+n] for n in (2, 3) for i in range(len(text)-n+1)]


def read_csv(path):
    raw = path.read_bytes()
    for encoding in ('utf-8-sig', 'cp949'):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(encoding)))), encoding
        except UnicodeDecodeError:
            pass
    raise ValueError(f'Unsupported source encoding: {path.name}')


def point(lat, lon):
    try:
        a, b = float(lat), float(lon)
        return {'latitude': a, 'longitude': b} if 33.05 <= a <= 33.65 and 126 <= b <= 127 else None
    except (ValueError, TypeError):
        return None


def number(value):
    return float(value.replace(',', '')) if value.strip() else None


def build(root):
    root = Path(root)
    raw = root / 'data_raw' / 'hub_v18'
    receipt = json.loads((raw / 'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
    sources = receipt['sources']
    for source in sources:
        path = root / source['local_path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('원자료 해시가 명세와 다릅니다: ' + source['id'])
    by_id = {s['id']: s for s in sources}
    items = []

    def add(source_id, index, name, kind, known, row, unknown, coords=None):
        source = by_id[source_id]
        original_name = name.strip()
        display_name = original_name or '명칭 미기재 · ' + str(known.get('시설유형') or '원자료 기록')
        item = {
            'id': f'{source_id}:{index}', 'name': display_name, 'kind': kind,
            'source_id': source_id, 'source_url': source['url'], 'source_date': source['source_date'],
            'source_status': 'historical_partial_reference' if source['partial'] else 'dated_source_reference',
            'known': {k: v for k, v in known.items() if v is not None and v != ''},
            'evidence': ' · '.join(f'{k}={v}' for k, v in row.items() if v != ''),
            'unknown': unknown, 'route_eligible': False, 'automatic_eligible': False,
            'current_opening_verified': False,
        }
        if not original_name:
            item['original_name'] = ''
            item['name_missing'] = True
            item['unknown'].append('원자료 시설명 미기재. 표시 문구는 시설 이름이 아님')
        if coords:
            item['coordinates'] = coords
            item['location_basis'] = 'source_representative_coordinate_not_verified_entrance'
        if kind == 'walk' and '예상 최대 소요(분)' in item['known']:
            item['max_minutes'] = item['known']['예상 최대 소요(분)']
        items.append(item)

    # 871 is an explicitly partial official preview, not a downloaded complete API response.
    rows, encoding = read_csv(raw / 'hub_871_preview_2532.csv')
    by_id['hub871']['encoding'] = encoding
    for index, row in enumerate(rows):
        time = row['예상 소요 시간'].strip()
        hours = [float(v) for v in re.findall(r'\d+(?:\.\d+)?', time)]
        if not hours:
            raise ValueError('Unrecognized official course time')
        known = {'코스번호': row['올레길 코스 번호'], '거리(km)': number(row['총 길이(KM)']),
                 '제공 소요시간': time + '시간', '예상 최대 소요(분)': max(hours) * 60,
                 '시작점': row['시작점'], '종점': row['종점'],
                 '휠체어 구간 표기': '일부 구간 있음(전체 통행 보장 아님)' if row['휠체어 구간 유무'] == 'TRUE' else '제공자료에 구간 없음으로 표기'}
        add('hub871', index, row['올레길 코스 번호'] + ' ' + row['올레길 코스 이름'], 'walk', known, row,
            ['현재 통제·노면·운영 상태 미확인', '전체 경로선과 출입구 미검증', '소요시간은 자료의 코스 구간 기준이며 출발지 이동·복귀·배편을 포함하지 않음'],
            point(row['시작점 위도'], row['시작점 경도']))

    rows, encoding = read_csv(raw / 'public_3082951.csv')
    by_id['hub497_origin']['encoding'] = encoding
    for index, row in enumerate(rows):
        known = {'구간': row['구간'], '거리(km)': number(row['연장(Km)']), '조성완료년도': row['조성완료년도']}
        add('hub497_origin', index, row['명칭'], 'walk', known, row,
            ['소요시간·난이도·좌표 미제공', '현재 통제·노면·접근성 미확인'])

    rows, encoding = read_csv(raw / 'hub_858_2461.csv')
    by_id['hub858']['encoding'] = encoding
    seen = set()
    for index, row in enumerate(rows):
        key = tuple(row.items())
        if key in seen:
            continue
        seen.add(key)
        add('hub858', index, row['장소명'], 'accessible',
            {'주소': row['주소'], '명부': '2021년 무장애 여행지 명부 수록(현재 접근성 미확인)'}, row,
            ['휠체어·유모차 통행 가능 여부 미확인', '경사·출입구·화장실·시설 상태 미제공', '동명 장소와 여러 참고 좌표는 별도 기록으로 보존'],
            point(row['위도'], row['경도']))
    accessible_duplicates_removed = len(rows)-len(seen)

    rows, encoding = read_csv(root / 'data_raw' / 'hub' / 'hub_784_5803.csv')
    by_id['hub784']['encoding'] = encoding
    latest = {}
    for row in rows:
        key = (row['행정시'], row['해변명'])
        if key not in latest or int(row['기준일(년)']) > int(latest[key]['기준일(년)']):
            latest[key] = row
    for index, row in enumerate(latest.values()):
        known = {'행정시': row['행정시'], '시설기준연도': int(row['기준일(년)']),
                 '백사장면적(㎡)': number(row['백사장면적(㎡)']), '화장실(동)': number(row['화장실(동)']),
                 '샤워장': number(row['샤워장']), '식수대': number(row['식수대']), '주차규모(대)': number(row['주차장(대)'])}
        # Annual visitor totals do not provide current crowding or facility availability.
        add('hub784', index, row['해변명'], 'beach', known, row,
            ['현재 시설 운영·청결·이용 가능 여부 미확인', '좌표·실시간 잔여 주차면·수영 가능 여부 미제공'])

    rows, encoding = read_csv(raw / 'public_15109369.csv')
    by_id['public15109369']['encoding'] = encoding
    seen = set()
    removed = Counter()
    for index, row in enumerate(rows):
        if row.get('상세영업상태명', '').strip() not in {'', '영업중', '사용중'}:
            removed['source_closed_or_inactive'] += 1
            continue
        key = (row['편의시설명'], row['소재지도로명주소'], row['소재지지번주소'], row['위도'], row['경도'])
        if key in seen:
            removed['exact_duplicate'] += 1
            continue
        seen.add(key)
        known = {'시설유형': row['편의시설유형'].strip(), '주소': row['소재지도로명주소'] or row['소재지지번주소'], '마을': row['마을명']}
        # Original dated hours/status stay in raw evidence, never promoted to live opening facts.
        add('public15109369', index, row['편의시설명'], 'amenity', known, row,
            ['2022년 기록으로 현재 운영·충전 가능·주차 가능 여부 미확인', '운영시간·영업상태는 당시 원문이며 현재 상태를 보장하지 않음'],
            point(row['위도'], row['경도']))

    frequencies = Counter()
    for item in items:
        text = item.get('original_name', item['name']) + ' ' + ' '.join(str(v) for v in item['known'].values())
        item['search_text'] = text
        frequencies.update(set(grams(text)))
    model = {'algorithm': 'character_ngram_tfidf_cosine', 'training_documents': len(items),
             'training_scope': 'actual_source_records', 'runtime_llm': False,
             'relevance_accuracy_evaluated': False,
             'idf': {term: math.log((1 + len(items)) / (1 + count)) + 1 for term, count in sorted(frequencies.items())}}
    data = {'schema_version': 1, 'built_at': datetime.now(timezone.utc).isoformat(),
            'sources': sources, 'items': items, 'search_model': model,
            'available_counts': dict(Counter(item['kind'] for item in items)),
            'filters': {'amenity_removed': dict(removed), 'accessible_exact_duplicates_removed': accessible_duplicates_removed}}
    output = root / 'data_reference' / 'travel_context_v18.json'
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'record_counts': data['available_counts'],
              'training_documents': len(items), 'vocabulary': len(model['idf']), 'source_raw_hashes': {s['id']: s['sha256'] for s in sources},
              'relevance_accuracy_evaluated': False, 'route_eligible_records': 0, 'filters': data['filters']}
    (raw / 'BUILD_RECEIPT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(build(ROOT), ensure_ascii=False, indent=2))
