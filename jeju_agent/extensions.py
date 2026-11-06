"""Presentation adapters for source-backed v18 models and travel information."""
import datetime as dt
import re
from pathlib import Path


_KST = dt.timezone(dt.timedelta(hours=9))


def _period(value):
    if isinstance(value, dict):
        return ' ~ '.join(str(value[key]) for key in ('start', 'end') if value.get(key))
    return str(value or '')


def _sources(data):
    sources = data.get('sources') or data.get('source') or []
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, list):
        return []
    return [dict(source, name=source.get('name') or source.get('title') or '제주 공공자료',
                 url=source.get('url') or source.get('source_url')) for source in sources if isinstance(source, dict)]


def _number(value, unit='', digits=1):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'{value:,.{digits}f}{unit}'
    return '확인 자료 없음'


def _notes(data):
    notes = []
    for key in ('scope', 'limitations', 'notes'):
        value = data.get(key)
        if isinstance(value, str) and value:
            notes.append(value)
        elif isinstance(value, list):
            notes.extend(item for item in value if isinstance(item, str))
    period = _period(data.get('observation_period'))
    if period:
        notes.insert(0, '학습 원자료 관측 기간 ' + period)
    return list(dict.fromkeys(notes))


def _integer(value, minimum, maximum, label, default=None):
    if value in (None, '') and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r'\d+', str(value)):
        raise ValueError(label + '을 숫자로 입력해 주세요.')
    value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f'{label}은 {minimum}~{maximum} 범위로 입력해 주세요.')
    return value


def data_guide(root, params, *, learned_search=True):
    """Return the same reviewable table to the UI and to assistant tool calls."""
    root = Path(root)
    kind = params.get('kind', 'route')
    query = params.get('query', '')
    if not isinstance(query, str) or len(query) > 80:
        raise ValueError('검색어는 80자 이내로 입력해 주세요.')
    query = query.strip()
    if kind == 'route':
        from .model_runtime_v20 import active_route_demand as get_route_demand
        date = params.get('date') or dt.datetime.now(_KST).date().isoformat()
        if not isinstance(date, str):
            raise ValueError('날짜 형식을 확인해 주세요.')
        dt.date.fromisoformat(date)
        data = get_route_demand(root, route=query or None, date=date, limit=12)
        rows = [[item.get('route_id'), _number(item.get('prediction'), '명/일'),
                 _number(item.get('test_mae'), '명/일'), item.get('history_last_date')]
                for item in data.get('items', [])]
        notes = _notes(data)
        evaluation = _period(data.get('metrics', {}).get('evaluation_period'))
        if evaluation:
            notes.append('오차 평가 기간 ' + evaluation)
        if data.get('message'):
            notes.append(data['message'])
        metrics = data.get('metrics', {})
        if metrics.get('evaluated_cell_coverage_percent') is not None:
            notes.append(f"평가는 {metrics.get('evaluation_route_count')}개 통계 코드로 당시 전체 관측 셀의 {_number(metrics['evaluated_cell_coverage_percent'], '%')}를 포함합니다. 운영 모델은 최근 관측이 충분한 {metrics.get('serving_route_count')}개 코드를 제공합니다.")
        return {'status': data.get('status', 'ok'), 'title': '노선번호별 하루 승차 이용 경향',
                'summary': f'{date}의 요일을 과거 학습 패턴에 적용한 참고치입니다.',
                'columns': ['원자료 통계 노선코드', '일반승차 추정', '이 코드의 평가 평균오차', '해당 기록 마지막 관측'],
                'rows': rows, 'metrics': _model_metrics(data, 'route'), 'notes': notes,
                'sources': _sources(data), 'model': data.get('model')}
    if kind == 'dining':
        from .dining_model import predict_dining
        month = _integer(params.get('month'), 1, 12, '월', dt.datetime.now(_KST).month)
        data = predict_dining(root, month=month, category=query or None, limit=20)
        rows = [[item.get('category'), item.get('parent_category'),
                 _number(item.get('predicted_share_percent'), '%'),
                 _number(item.get('test_mae_percentage_points'), 'pp', 3),
                 _number(item.get('historical_amount_per_transaction_krw'), '원', 0)] for item in data.get('items', [])]
        notes = _notes(data)
        evaluation = _period(data.get('metrics', {}).get('evaluation_period'))
        if evaluation:
            notes.append('오차 평가 기간 ' + evaluation)
        items = data.get('items') or []
        if items:
            notes.append('결제 건당 금액의 관측 참고 기간 ' + _period(items[0].get('reference_period')))
        notes.append('표시한 일부 업종의 비중 합계는 100%보다 작을 수 있습니다. 소규모 업종이 많아 전체 오차와 상위 업종 오차를 함께 확인해 주세요.')
        notes.append('1퍼센트포인트(pp)는 비중 30%와 31%의 차이입니다. 결제 금액은 관측 참고값이며 구성비 모델의 예측 오차로 평가한 항목이 아닙니다.')
        baseline = data.get('metrics', {}).get('improvement_vs_same_fit_mean_percent')
        if baseline is not None:
            notes.append(f'동일 학습기간 전체 평균 대비 구성비 오차 감소 {_number(baseline, "%")}입니다. 최근 가중 평균과의 차이도 별도 지표로 함께 비교합니다.')
        return {'status': data.get('status', 'ok'), 'title': f'{month}월 세부 외식업종 이용건수 구성',
                'summary': '구성비의 분모는 전체 학습 대상 업종입니다. 검색으로 좁혀도 분모를 바꾸지 않습니다.',
                'columns': ['세부 업종', '중분류', '추정 구성비', '이 업종의 평가 평균오차', '과거 결제 건당 금액'],
                'rows': rows, 'metrics': _model_metrics(data, 'dining'), 'notes': notes,
                'sources': _sources(data), 'model': data.get('model')}
    if kind not in {'walk', 'beach', 'accessible', 'amenity'}:
        raise ValueError('지원하는 자료 유형을 선택해 주세요.')
    from .travel_context import search_travel_context
    raw = params.get('max_minutes')
    minutes = _integer(raw, 1, 1440, '걷기 시간 한도') if raw not in (None, '') else None
    if minutes is not None and kind != 'walk':
        raise ValueError('시간 한도는 걷기 코스에 적용해 주세요.')
    data = search_travel_context(root, kind=kind, query=query, max_minutes=minutes, limit=12, learned=learned_search)
    titles = {'walk': '시간과 거리에 맞는 걷기 코스', 'beach': '해변 편의시설 비교',
              'accessible': '접근성 자료에 기록된 여행지', 'amenity': '마을 편의시설 참고'}
    rows = [[item.get('name'), _known(item.get('known', {})), item.get('source_date'),
             _evidence(item)] for item in data.get('items', [])]
    notes = _notes(data)
    if data.get('message'):
        notes.append(data['message'])
    if learned_search and data.get('model'):
        notes.append('검색 관련도는 실제 자료의 문자 TF-IDF로 계산합니다. 검색 정확도와 현장 이용 만족도는 아직 평가하지 않았습니다.')
    return {'status': data.get('status', 'ok'), 'title': titles[kind],
            'columns': ['코스·시설', '기록된 항목', '자료 기준일', '설명과 확인할 내용'],
            'rows': rows, 'metrics': [], 'notes': notes, 'sources': _sources(data), 'model': data.get('model'),
            'empty_message': data.get('message')}


def _known(known):
    if not isinstance(known, dict):
        return str(known or '')
    labels = {'distance_km': '길이(km)', 'length_km': '길이(km)', 'duration_minutes': '제공 소요시간(분)',
              'duration_min_minutes': '제공 최소시간(분)', 'duration_max_minutes': '제공 최대시간(분)',
              'estimated_minutes': '제공 소요시간(분)', 'toilets': '화장실', 'showers': '샤워장',
              'parking_capacity': '주차 규모', 'drinking_water': '식수대', 'address': '주소',
              'category': '종류', 'course_number': '코스번호', 'section': '구간'}
    values = []
    for key, value in known.items():
        if value is None or value == '':
            continue
        if isinstance(value, list):
            value = ', '.join(str(item) for item in value)
        values.append(f'{labels.get(key, key)} · {value}')
    return '\n'.join(values)


def _evidence(item):
    evidence = item.get('evidence') or ''
    if isinstance(evidence, list):
        evidence = '\n'.join(str(value) for value in evidence)
    unknown = item.get('unknown') or []
    if isinstance(unknown, list) and unknown:
        evidence += '\n확인 필요 · ' + ', '.join(str(value) for value in unknown)
    return evidence


def _model_metrics(data, kind):
    metrics = data.get('metrics') or {}
    if kind == 'dining':
        result = [{'label': '평균 구성비 오차', 'value': _number(metrics.get('mae_percentage_points'), '퍼센트포인트', 3)}]
        tolerance = metrics.get('within_tolerance', {}).get('0.25', {})
        if tolerance:
            result.append({'label': f"±0.25퍼센트포인트 이내 · {tolerance.get('within')}/{tolerance.get('total')}건", 'value': _number(tolerance.get('percent'), '%')})
        if metrics.get('top10_observed_share_categories_mae_percentage_points') is not None:
            result.append({'label': '관측 비중 상위 10개 업종 평균오차', 'value': _number(metrics['top10_observed_share_categories_mae_percentage_points'], '퍼센트포인트', 3)})
        if metrics.get('improvement_vs_same_config_recent_mean_percent') is not None:
            result.append({'label': '최근 가중 평균 대비 추가 오차 감소', 'value': _number(metrics['improvement_vs_same_config_recent_mean_percent'], '%')})
        return result
    if kind == 'route':
        result = [{'label': '전체 평가 평균오차 · 코드별 하루 승차', 'value': _number(metrics.get('mae'), '명/일')},
                  {'label': '이용량을 고려한 상대오차(WAPE)', 'value': _number(metrics.get('wape_percent'), '%')}]
        tolerance = metrics.get('within_20_percent') or {}
        if tolerance:
            result.append({'label': f"관측값 ±20% 이내 · {tolerance.get('hits')}/{tolerance.get('denominator')}건", 'value': _number(tolerance.get('percent'), '%')})
        if metrics.get('mae_reduction_percent') is not None:
            result.append({'label': '같은 학습기간 기준모델 대비 오차 감소', 'value': _number(metrics['mae_reduction_percent'], '%')})
        return result
    return []


def assistant_extension(root, text):
    """Recognize explicit data-tool requests without replacing trip interpretation."""
    if not isinstance(text, str) or len(text) > 240:
        return None
    if re.search(r'실시간|도착|만차|시간표|예약|운행\s*중|지금\s*영업', text):
        return None
    extension_request = re.search(r'(세부|소분류|상세).*(외식|업종)|(외식|업종).*(세부|소분류|상세)|노선.*(수요|이용|승차)|(수요|이용|승차).*노선|(해변|해수욕장).*(시설|비교)', text)
    if extension_request and re.search(r'말고|제외|아닌|아니라|않|빼|없|말아|하지|짜\s*줘|계획|여행\s*일정|코스', text):
        return {'status': 'needs_input', 'message': '자료 비교와 일정·제외 조건은 나누어 요청해 주세요. 세부 조건은 탐색 화면의 자료 비교에서 직접 입력할 수 있습니다.'}
    params = None
    if re.search(r'(세부|소분류|상세).*(외식|업종)|(외식|업종).*(세부|소분류|상세)', text):
        match = re.fullmatch(r'\s*(?P<month>\d{1,2})\s*월\s*(?P<category>[가-힣/· ]{0,30}?)\s*(?:세부|상세|소분류)\s*(?:외식\s*)?업종\s*(?:이용건수\s*)?(?:(?:비중|구성비)\s*)?(?:분석|비교)?\s*(?:해\s*줘|보여\s*줘|알려\s*줘)?[.!?]?\s*', text)
        if not match:
            return {'status': 'needs_input', 'message': '월 하나와 업종을 입력해 주세요. 예를 들어 “6월 세부 외식업종 비교” 또는 “6월 한식 세부 외식업종 비교”로 요청할 수 있습니다. 특정 연도의 결과는 지원하지 않습니다.'}
        params = {'kind': 'dining', 'month': match.group('month'), 'query': match.group('category').strip()}
    elif re.search(r'노선.*(수요|이용|승차)|(수요|이용|승차).*노선', text):
        if len(re.findall(r'[월화수목금토일]요일', text)) > 1 or re.search(r'\d\s*월|\d\s*년|월별|시간대|오전|오후|저녁', text):
            return {'status': 'needs_input', 'message': '노선 수요는 날짜 또는 요일 하나를 기준으로 비교합니다. 탐색 화면에서 날짜와 원자료 노선코드를 지정해 주세요.'}
        date = re.search(r'\d{4}-\d{2}-\d{2}', text)
        # Date digits must never be interpreted as a source route code.
        without_date = re.sub(r'\d{4}-\d{2}-\d{2}', '', text)
        code = re.search(r'(?<![\d-])(\d{1,4}(?:-\d{1,3})?)(?:번)?', without_date)
        codes = re.findall(r'(?<![\d-])\d{1,4}(?:-\d{1,3})?(?:번)?', without_date)
        rest = re.sub(r'\d{4}-\d{2}-\d{2}|[월화수목금토일]요일|\d{1,4}(?:-\d{1,3})?번?', '', text)
        rest = re.sub(r'노선별|노선|버스|하루|승차|수요|이용|비교|분석|알려\s*줘|보여\s*줘|해\s*줘|내일|모레|오늘|[\s.!?]', '', rest)
        if len(codes) > 1 or rest or len(re.findall(r'\d{4}-\d{2}-\d{2}', text)) > 1 or (date and re.search(r'[월화수목금토일]요일|내일|모레|오늘', text)):
            return {'status': 'needs_input', 'message': '날짜·요일 하나와 원자료 노선코드 하나로 요청해 주세요. 예를 들어 “토요일 202-14 노선 수요 비교” 또는 “노선별 하루 승차 수요 비교”로 입력할 수 있습니다.'}
        params = {'kind': 'route', 'query': code.group(1) if code else '', 'date': date.group(0) if date else ''}
        today = dt.datetime.now(_KST).date()
        if not date:
            weekday = re.search(r'([월화수목금토일])요일', text)
            offset = 2 if '모레' in text else 1 if '내일' in text else 0
            target = today + dt.timedelta(days=offset)
            if weekday:
                target = today + dt.timedelta(days=('월화수목금토일'.index(weekday.group(1)) - today.weekday()) % 7)
            params['date'] = target.isoformat()
    elif re.search(r'(해변|해수욕장).*(시설|비교)|(시설|비교).*(해변|해수욕장)', text):
        if not re.fullmatch(r'\s*(?:해변|해수욕장)\s*(?:편의)?시설\s*(?:비교(?:해\s*줘)?|알려\s*줘|보여\s*줘)?[.!?]?\s*', text):
            return {'status': 'needs_input', 'message': '해변별 시설 검색은 탐색 화면의 ‘해변 편의시설’에서 이름을 입력해 주세요. 전체 비교는 “해수욕장 편의시설 비교”로 요청할 수 있습니다.'}
        params = {'kind': 'beach'}
    if params is None:
        return None
    unsupported = re.search(r'도민|관광객|내국인|외국인|동쪽|서쪽|서귀포|제주시|오전|오후|저녁', text)
    if unsupported:
        return {'status': 'needs_input', 'message': '이 자료는 집단·지역·시간대 조건으로 나눌 수 없습니다. 탐색 화면의 자료 비교에서 지원 범위를 확인해 주세요.'}
    data = data_guide(root, params)
    data['notes'] += [entry['label'] + ' · ' + entry['value'] for entry in data.get('metrics', [])]
    return {'status': 'ok', 'message': '제주 원자료에서 요청한 항목을 비교했습니다.',
            'analysis': {key: data[key] for key in ('title', 'columns', 'rows', 'notes', 'sources')}}
