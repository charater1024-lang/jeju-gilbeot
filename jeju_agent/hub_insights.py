"""Read-only, source-pinned historical Jeju Hub insights; stdlib CPU only.

Visitor counts are observations, not a deployed forecast. Regional neighbours
compare learned consumption composition, never geographic distance or routes.
"""
from collections import defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sqlite3

SCHEMA_VERSION = 1
VISITOR_VENUES = ('국립제주박물관', '비자림', '산방산', '성산일출봉', '이중섭미술관', '천지연폭포')
VISITOR_SOURCES = {
    'domestic': {'id': 189, 'path': 'data/hub_insights/visitor/raw_189_5788.csv',
                 'sha256': 'e454d271c49cbd55ed139d68c3b7311a4add6e7815b7e16de242b1f3466b1dbc'},
    'foreign': {'id': 190, 'path': 'data/hub_insights/visitor/raw_190_5787.csv',
                'sha256': '5dff2e453b523e0ad3597f1704e97c00366730623de85f64cf4a34dba4b2fddc'},
}
# The immutable byte hashes are frozen after the training agent exports assets.
REGIONAL_MODEL_PATH = 'models_hub_insights/regional_food_model.json'
REGIONAL_MODEL_SHA256 = '9f7c849219d249d02c49691d17be4e446afd5816eb3a393bde406f7c09918bf4'
REGIONAL_SOURCES = (
    (2002, '44f084781db9bed155d24e1cf8604379f6f17945c35ba9d56f4bea3cecd42733'),
    (2003, '378ce59a5a4dbce7eaef1813d346a3883eb1e0d5ef9413938326c7c05c2220ed'),
    (2004, '2003645fcc49655809ffff07330b3fcbafc57cc4afa3201601017c9576366b51'),
    (2005, '55153ce1d65a3e7cf25601d446aba3b4f087376965abc2b0cf3b0b323f00a9f1'),
)
FORECAST_REASON = '실제 관람객 홀드아웃에서 사전 채택 기준(5% 오차 개선·집단별 보호)을 충족하지 못해 ML 예측을 운영에 적용하지 않았습니다.'
VISITOR_LIMITATIONS = [
    '2009~2024년 관광지별 월별 입장객 관측입니다. 현재 혼잡·영업·입구·요금·관광 자격을 보장하지 않습니다.',
    '계절 달력은 2018~2024년 완전 관측 연도의 기술 통계입니다. 2020~2021년의 특수한 여행 환경도 포함합니다.',
    '같은 관광지 안의 과거 월별 경향이며 관광지 간 개인 선호 순위·이동 순서·인기 경로의 학습 결과가 아닙니다.',
    '관측된 0은 보존하고 누락 월을 0으로 채우지 않습니다. 자동 코스 편입은 기존 별도 검증을 거쳐야 합니다.',
    '허브189의 메타데이터 종료일은 2024-09-30이지만 내려받은 CSV는 2024-12까지 있습니다.',
]
REGIONAL_LIMITATIONS = [
    '2020-06~2021-05년 공통 6업종 이용자수 합계의 구성비입니다. 현재 인기도·개별 식당 품질·메뉴·고유 고객 수가 아닙니다.',
    '가까운 지역은 학습한 소비 구성의 유사성입니다. 실제 거리·이동 시간·추천 확률·개인 취향 적합률이 아닙니다.',
    '공통 6업종의 12개월이 모두 양수로 관측된 지역만 비교합니다. 누락 업종·월을 0으로 채우지 않습니다.',
    '이 결과만으로 관광지나 식당을 자동 코스에 넣지 않습니다. 총유동인구 열은 합산하지 않습니다.',
    '원래 6차원 소비 구성에서 고른 이웃과 2차원 투영 이웃의 상위 3개 겹침은 홀드아웃 평균 약 36.75%였습니다. 2차원 소비 패턴 참고로 해석하세요.',
]


class HubInsightDataError(RuntimeError):
    """An installed asset or its source evidence changed; respond fail-closed."""


class _AssetMissing(Exception):
    pass


def _number(value, *, positive=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def _read_verified(root, relative_path, expected_sha, max_bytes=5_000_000):
    base = Path(root).resolve()
    path = (base / relative_path).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise HubInsightDataError('허브 자료 경로가 프로젝트 밖을 가리킵니다.') from exc
    if not path.is_file():
        raise _AssetMissing(relative_path)
    if path.stat().st_size > max_bytes:
        raise HubInsightDataError('허브 자료 크기가 검증 범위를 넘었습니다.')
    content = path.read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha or '') or hashlib.sha256(content).hexdigest() != expected_sha:
        raise HubInsightDataError('허브 자료의 SHA-256이 검증된 원본과 다릅니다. 조회를 중단했습니다.')
    return content


def _unavailable(kind, reason):
    return {'schema_version': SCHEMA_VERSION, 'kind': kind, 'available': False,
            'ml_applied': False, 'reason': reason, 'items': [], 'places': [], 'areas': [],
            'selected': None, 'sources': [], 'limitations': []}


def _source(spec):
    return {'id': spec['id'], 'url': f'https://www.jejudatahub.net/data/view/data/{spec["id"]}',
            'sha256': spec['sha256'], 'kind': 'historical_observations'}


def _visitor_observations(root):
    result = {}
    for audience, spec in VISITOR_SOURCES.items():
        content = _read_verified(root, spec['path'], spec['sha256'])
        try:
            reader = csv.DictReader(io.StringIO(content.decode('cp949'), newline=''))
            if reader.fieldnames != ['날짜', '관광지명', '관광객수']:
                raise ValueError('header')
            data = defaultdict(dict)
            seen = set()
            for row in reader:
                name, month, count = row['관광지명'], row['날짜'], row['관광객수']
                if not re.fullmatch(r'\d{4}\.(0[1-9]|1[0-2])', month) or not re.fullmatch(r'\d+', count):
                    raise ValueError('month or count')
                key = (name, month)
                if key in seen:
                    raise ValueError('duplicate venue-month')
                seen.add(key)
                if name in VISITOR_VENUES:
                    data[name][month.replace('.', '-')] = int(count)
            expected = {f'{year}-{month:02d}' for year in range(2009, 2025) for month in range(1, 13)}
            if set(data) != set(VISITOR_VENUES) or any(set(data[name]) != expected for name in VISITOR_VENUES):
                raise ValueError('incomplete calendar')
            result[audience] = data
        except (UnicodeError, ValueError, KeyError, TypeError, csv.Error) as exc:
            raise HubInsightDataError('관광지 월별 관측의 형식·중복·완전성을 확인할 수 없습니다.') from exc
    return result


def _visitor_place_map(root):
    from .tourism_access import approved_places
    from .tourism_overlap import normalized_name
    try:
        grouped = defaultdict(list)
        for item in approved_places(root):
            grouped[normalized_name(item['name'])].append(item)
        mapped = {}
        for venue in VISITOR_VENUES:
            matches = grouped.get(normalized_name(venue), [])
            if len(matches) != 1:
                raise ValueError('exact name missing or ambiguous')
            item = matches[0]
            mapped[venue] = {'key': venue, 'name': item['name'], 'place_id': item['id']}
        return mapped
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        raise HubInsightDataError('기존 승인 관광지와의 정확한 이름 연결을 확인할 수 없습니다.') from exc


def _visitor_calendar(observations):
    # Every year contributes its own annual share; high-volume years cannot
    # silently dominate the annual denominator of another year.
    years = range(2018, 2025)
    totals = {year: sum(observations[f'{year}-{month:02d}'] for month in range(1, 13)) for year in years}
    result = []
    for month in range(1, 13):
        values = [observations[f'{year}-{month:02d}'] for year in years]
        fractions = [observations[f'{year}-{month:02d}'] / totals[year] for year in years if totals[year] > 0]
        result.append({'month': month, 'mean': round(sum(values) / len(values), 6),
                       'count_years': len(values), 'share': sum(fractions) / len(fractions) if fractions else None,
                       'share_count_years': len(fractions)})
    return result


def visitor_patterns(root, place='', audience='domestic'):
    """Return exact-source historical counts and a descriptive month calendar."""
    if not isinstance(place, str) or place not in ('', *VISITOR_VENUES):
        raise ValueError('제공된 관광지 key를 정확히 선택하세요.')
    if not isinstance(audience, str) or audience not in VISITOR_SOURCES:
        raise ValueError('audience는 domestic 또는 foreign만 가능합니다.')
    try:
        observed = _visitor_observations(root)
        mapped = _visitor_place_map(root)
    except _AssetMissing:
        return _unavailable('visitor', '검증된 관광지 월별 원본 자료가 설치되지 않았습니다.')
    key = place or VISITOR_VENUES[0]
    series = observed[audience][key]
    places = [dict(mapped[name]) for name in VISITOR_VENUES]
    selected = dict(mapped[key], audience=audience,
                    monthly_series=[{'month': month, 'count': count} for month, count in sorted(series.items())],
                    seasonality=_visitor_calendar(series),
                    seasonality_period={'start_month': '2018-01', 'end_month': '2024-12'},
                    forecast={'available': False, 'month': '2025-01', 'count': None,
                              'model': 'CatBoost GPU — 검증 후 운영 미적용', 'as_of_month': '2024-12',
                              'reason': FORECAST_REASON}, not_itinerary_place=True)
    evaluation = {'kind': 'time_ordered_retrospective', 'experiment_model': 'CatBoost GPU',
                  'candidate_count': 12, 'actual_gpu_fits': 13, 'adoption_gate_pass': False,
                  'baseline_name': 'last_month', 'validation_months': '2022-01~2022-12',
                  'test_months': '2023-01~2024-12', 'test_cells': 1444,
                  'test_scope': '학습 조건을 만족한 전체 관광지·내외국인 셀; 화면의 6곳만을 뜻하지 않음',
                  'baseline_wape': 0.3085949525721144, 'model_wape': 0.2940813279432222,
                  'baseline_rmsle': 0.9769011398341443, 'model_rmsle': 1.1953738277028774,
                  'reason': FORECAST_REASON}
    return {'schema_version': SCHEMA_VERSION, 'kind': 'visitor', 'available': True,
            'ml_applied': False, 'places': places, 'items': places, 'selected': selected, 'audience': audience,
            'period': {'start_month': '2009-01', 'end_month': '2024-12'},
            'model': {'name': '과거 월별 관람 통계 달력', 'method': 'descriptive_observed_calendar', 'ml_applied': False},
            'sources': [_source(spec) for spec in VISITOR_SOURCES.values()],
            'limitations': list(VISITOR_LIMITATIONS), 'evaluation': evaluation}


def _canonical_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _clr(counts):
    if not isinstance(counts, list) or len(counts) != 6 or not all(_number(x, positive=True) for x in counts):
        raise ValueError('6 positive observed categories required')
    logs = [math.log(x) for x in counts]
    mean = sum(logs) / 6
    return [x - mean for x in logs]


def _project(model, counts):
    vector = _clr(counts)
    return [sum((x - mean) * weight for x, mean, weight in zip(vector, model['pca']['mean'], component))
            for component in model['pca']['components']]


def _distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _regional_model(root):
    if not REGIONAL_MODEL_SHA256:
        raise _AssetMissing(REGIONAL_MODEL_PATH)
    raw = _read_verified(root, REGIONAL_MODEL_PATH, REGIONAL_MODEL_SHA256, 3_000_000)
    for attachment, digest in REGIONAL_SOURCES:
        _read_verified(root, f'data/hub_insights/regional/raw_758_{attachment}.csv', digest)
    try:
        model = json.loads(raw.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        payload = dict(model)
        supplied = payload.pop('snapshot_sha256', None)
        if supplied != _canonical_digest(payload):
            raise ValueError('snapshot')
        if model['schema_version'] != 1 or model['algorithm'] != 'clr_pca_kmeans_regional_food_v1':
            raise ValueError('algorithm')
        categories = model['categories']
        if not isinstance(categories, list) or len(categories) != 6 or len(set(categories)) != 6 or not all(isinstance(s, str) and s for s in categories):
            raise ValueError('categories')
        dimension = model['pca']['dimension']
        if type(dimension) is not int or not 1 <= dimension < 6:
            raise ValueError('dimension')
        mean, components, centers = model['pca']['mean'], model['pca']['components'], model['cluster_centers']
        if len(mean) != 6 or len(components) != dimension or not 2 <= len(centers) <= 12:
            raise ValueError('projection shape')
        vectors = [mean] + components + centers
        if any(not isinstance(v, list) or not all(not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x) for x in v) for v in vectors):
            raise ValueError('projection numbers')
        if any(len(v) != 6 for v in components) or any(len(v) != dimension for v in centers):
            raise ValueError('projection dimensions')
        expected_months = {f'2020-{m:02d}' for m in range(6, 13)} | {f'2021-{m:02d}' for m in range(1, 6)}
        seen = set()
        for profile in model['profiles']:
            ident = profile['id']
            if not isinstance(ident, str) or ident in seen or ident != profile['city'] + '|' + profile['dong']:
                raise ValueError('region key')
            seen.add(ident)
            counts = profile['category_user_count_sums']
            _clr(counts)
            if len(profile['shares']) != 6 or not all(_number(x) for x in profile['shares']):
                raise ValueError('shares')
            total = sum(counts)
            if any(abs(count / total - share) > 1e-9 for count, share in zip(counts, profile['shares'])):
                raise ValueError('denominator')
            if len(profile['months']) != 12 or set(profile['months']) != expected_months:
                raise ValueError('missing month')
            vector = _project(model, counts)
            assigned = min(range(len(centers)), key=lambda i: (_distance(vector, centers[i]), i))
            if type(profile['cluster_id']) is not int or profile['cluster_id'] != assigned:
                raise ValueError('cluster')
        if len(seen) != 39 or model['serving']['region_count'] != 39:
            raise ValueError('serving count')
        if model['source_dataset_id'] != 758 or model['serving']['missing_imputed'] is not False:
            raise ValueError('source or missing-value policy')
        source_hashes = {item['sha256'] for item in model['source_files']}
        if source_hashes != {digest for _, digest in REGIONAL_SOURCES}:
            raise ValueError('source provenance')
        return model
    except (UnicodeError, ValueError, KeyError, TypeError, OverflowError) as exc:
        raise HubInsightDataError('지역 소비 모델의 스냅샷·명칭·분모·관측 기간 검증에 실패했습니다.') from exc


def regional_patterns(root, region=''):
    """Return 6-category observed shares and 3 learned composition neighbours."""
    if not isinstance(region, str) or len(region) > 100 or (region and not re.fullmatch(r'[^|\s]+\|[^|\s]+', region)):
        raise ValueError('region은 제공된 시|읍면동 key를 정확히 선택하세요.')
    try:
        model = _regional_model(root)
    except _AssetMissing:
        return _unavailable('regional', '검증된 지역 소비 모델과 원본 자료가 설치되지 않았습니다.')
    indexed = {item['id']: item for item in model['profiles']}
    if region and region not in indexed:
        raise ValueError('12개월 완전 관측한 명부의 지역 key를 선택하세요.')
    key = region or sorted(indexed)[0]
    origin = indexed[key]
    categories = model['categories']

    def entry(profile):
        return {'key': profile['id'], 'city': profile['city'], 'name': profile['dong']}

    def shares(profile):
        return [{'name': name, 'share': value} for name, value in zip(categories, profile['shares'])]

    vector = _project(model, origin['category_user_count_sums'])
    ranked = sorted(((_distance(vector, _project(model, p['category_user_count_sums'])), p['id'], p)
                     for p in model['profiles'] if p['id'] != key), key=lambda item: (item[0], item[1]))
    neighbours = [dict(entry(p), distance=distance, shares=shares(p), cluster=p['cluster_id'],
                       distance_kind='projected_clr_distance_not_geographic_or_probability', not_itinerary_place=True)
                  for distance, _, p in ranked[:3]]
    selected = dict(entry(origin), shares=shares(origin), nearest=neighbours, cluster=origin['cluster_id'],
                    source_months=12, not_itinerary_place=True)
    areas = [entry(indexed[k]) for k in sorted(indexed)]
    return {'schema_version': SCHEMA_VERSION, 'kind': 'regional', 'available': True, 'ml_applied': True,
            'areas': areas, 'items': areas, 'selected': selected,
            'period': {'start_month': '2020-06', 'end_month': '2021-05'},
            'model': {'name': 'CLR → PCA → KMeans 지역 소비 유형', 'method': model['algorithm'],
                      'cluster_count': len(model['cluster_centers']), 'pca_dimension': model['pca']['dimension'],
                      'training_period': model['training'].get('observation_period'),
                      'region_count': 39, 'category_count': 6},
            'sources': [{'id': 758, 'url': 'https://www.jejudatahub.net/data/view/data/758',
                         'sha256': digest, 'kind': 'historical_observations'} for _, digest in REGIONAL_SOURCES],
            'limitations': list(REGIONAL_LIMITATIONS),
            'evaluation': {'kind': 'unsupervised_time_split', 'classification_accuracy': None,
                           'dev_silhouette': 0.3443174235398906, 'holdout_silhouette': 0.3026107128273446,
                           'holdout_share_reconstruction_mae_pp': 3.9224360750853147,
                           'mean_baseline_share_reconstruction_mae_pp': 4.606733443808044,
                           'holdout_cluster_ari': 0.5777071053669851,
                           'full_clr_top3_overlap': 0.36752136752136755,
                           'note': '군집·투영의 구조 검증이며 개인 추천 정답률이나 현재 수요 예측 성능이 아닙니다.'}}
