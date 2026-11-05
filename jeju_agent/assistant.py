"""Offline assistant: interpret a request, confirm conditions, and call local tools."""
import base64
import datetime as dt
import hashlib
import hmac
import json
from pathlib import Path
import secrets

from .assistant_intent import parse_request
from .assistant_search import search_assistant
from .audience_model import predict_audience
from .discovery import _normalized
from .insights import mobility_insight
from .orchestrator import run_agent
from .planning_input import validate_confirmed_origin
from .tourism_access import approved_places


_KEY = secrets.token_bytes(32)
_KST = dt.timezone(dt.timedelta(hours=9))
_AIRPORT = '제주공항'
_AIRPORT_POINT = (33.506, 126.492)  # Same public reference point as the planner.
_AIRPORT_NAMES = {'제주공항', '제주국제공항', '공항'}
_PLAN_FIELDS = {'date', 'start_name', 'start_minute', 'end_minute', 'transport',
                'max_stops', 'budget_krw', 'region', 'query', 'exclude_names'}
_REGION_LABELS = {'all': '제주 전체', 'north': '북부', 'south': '남부', 'east': '동부', 'west': '서부'}
_MODE_LABELS = {'car': '자동차', 'walk': '도보', 'bus': '버스'}
_GROUP_LABELS = {'resident': '제주도민', 'tourist': '내국인 참고 집단'}
_PERIOD_LABELS = {'morning': '오전', 'afternoon': '오후', 'evening': '저녁', 'daytime': '낮', 'all': '전체'}
_WEEKDAYS = ('월', '화', '수', '목', '금', '토', '일')


def _today():
    return dt.datetime.now(_KST).date()


def _mac(raw):
    return hmac.new(_KEY, raw, hashlib.sha256).hexdigest()


def _encode(session):
    payload = base64.urlsafe_b64encode(json.dumps(session, ensure_ascii=False,
                                                    separators=(',', ':')).encode()).decode()
    return payload + '.' + _mac(payload.encode())


def _decode(token):
    if token is None:
        return {}
    if not isinstance(token, str) or len(token) > 6000:
        raise ValueError('대화 상태를 읽을 수 없습니다. 새 대화를 시작해 주세요.')
    payload, sep, signature = token.partition('.')
    if not sep or not hmac.compare_digest(signature.encode(), _mac(payload.encode()).encode()):
        raise ValueError('대화 상태가 만료되었거나 바뀌었습니다. 새 대화를 시작해 주세요.')
    return json.loads(base64.urlsafe_b64decode(payload))


def _reply(status, message, session, **data):
    return {'status': status, 'message': message,
            'state': _encode(session) if session else None, **data}


def _clock(minute):
    return f'{minute // 60:02d}:{minute % 60:02d}'


def _conditions(draft):
    values = {'여행일': draft['date'],
              '출발과 복귀': draft.get('start_name') or '직접 확인한 일정 출발지',
              '이동수단': _MODE_LABELS.get(draft.get('transport'), '확인 필요'),
              '방문 수': f"최대 {draft['max_stops']}곳",
              '지역': _REGION_LABELS.get(draft['region'], '확인 필요'),
              '추정 이동비 한도': f"{draft['budget_krw']:,}원"}
    if 'start_minute' in draft and 'end_minute' in draft:
        values['여행 시간'] = f"{_clock(draft['start_minute'])} 출발 · {_clock(draft['end_minute'])}까지 복귀"
    elif 'start_minute' in draft:
        values['출발 시간'] = _clock(draft['start_minute'])
    if draft['query']:
        values['관심 장소'] = draft['query']
    if draft['exclude_names']:
        values['제외할 장소'] = ', '.join(draft['exclude_names'])
    return values


def _named_exclusions(root, names):
    if not names:
        return [], []
    matches = {}
    for place in approved_places(root):
        for name in {place['name'], place.get('map_name', '')}:
            if name:
                matches.setdefault(_normalized(name), {})[place['id']] = place['name']
    ids, canonical = [], []
    for name in names:
        hits = matches.get(_normalized(name), {})
        if len(hits) != 1:
            raise ValueError(f'“{name}”의 정확한 관광지 이름을 확인해 주세요. 여러 장소라면 이름을 따로 입력해 주세요.')
        ident, label = next(iter(hits.items()))
        if ident not in ids:
            ids.append(ident)
            canonical.append(label)
    return ids, canonical


def _draft_update(root, parsed, session, day):
    previous = session.get('draft', {})
    fields = parsed['fields']
    draft = {'date': day.isoformat(), 'max_stops': 3, 'budget_krw': 100000,
             'region': 'all', 'query': '', 'exclude_names': [], **previous}
    if fields.get('return_to_origin') is False or (
            fields.get('end_name') and _normalized(fields['end_name']) !=
            _normalized(fields.get('start_name') or draft.get('start_name') or '')):
        raise ValueError('대화 일정은 같은 출발지로 돌아오는 코스를 지원합니다. 다른 도착지는 직접 일정에서 지정해 주세요.')
    draft.update({key: value for key, value in fields.items() if key in _PLAN_FIELDS and key != 'exclude_names'})
    if _normalized(draft.get('start_name', '')) in _AIRPORT_NAMES:
        draft['start_name'] = _AIRPORT
    names = list(dict.fromkeys(previous.get('exclude_names', []) + fields.get('exclude_names', [])))
    if len(names) > 12:
        raise ValueError('대화로 제외할 장소는 12곳까지 입력할 수 있습니다.')
    _, draft['exclude_names'] = _named_exclusions(root, names)

    duration = fields.get('duration_minutes', session.get('duration_limit'))
    if 'end_minute' in fields and 'duration_minutes' not in fields:
        duration = None
    if duration is not None and 'start_minute' in draft:
        deadline = draft['start_minute'] + duration
        if 'end_minute' in fields and fields['end_minute'] != deadline:
            raise ValueError('여행 시간과 복귀 시각이 서로 다릅니다. 한 가지 기준으로 정해 주세요.')
        draft['end_minute'] = deadline
    for key, low, high, label in [('max_stops', 1, 8, '방문 수'), ('budget_krw', 0, 10000000, '이동비 한도'),
                                  ('start_minute', 0, 1439, '출발 시각'), ('end_minute', 1, 1440, '복귀 시각')]:
        if key in draft and (type(draft[key]) is not int or not low <= draft[key] <= high):
            raise ValueError(f'{label}을 같은 날 일정에 맞게 다시 입력해 주세요.')
    if draft.get('start_minute', -1) >= draft.get('end_minute', 1441):
        raise ValueError('복귀 시각은 출발 시각보다 늦게 정해 주세요.')

    reduction = fields.get('reduce_stops')
    if reduction:
        if not session.get('stop_count'):
            raise ValueError('방문 수를 줄이려면 먼저 코스를 계산해 주세요. 최대 방문 수를 직접 말씀하셔도 됩니다.')
        draft['max_stops'] = session['stop_count'] - reduction
        if draft['max_stops'] < 1:
            raise ValueError('일정에는 한 곳 이상이 필요합니다. 원하는 방문 수를 정해 주세요.')
    if fields.get('shorter_travel') and 'max_stops' not in fields and not reduction:
        if session.get('stop_count', 0) <= 1:
            raise ValueError('현재 조건의 이동시간을 비교하려면 먼저 두 곳 이상의 코스를 계산해 주세요.')
        draft['max_stops'] = session['stop_count'] - 1
    return draft, duration


def _public_origin(root, draft):
    name = draft.get('start_name')
    if name == _AIRPORT:
        return _AIRPORT, *_AIRPORT_POINT
    if not name:
        return None
    matches = [p for p in approved_places(root)
               if _normalized(name) in {_normalized(p['name']), _normalized(p.get('map_name', ''))}]
    if len(matches) != 1:
        return None
    from .place_trust import place_trust
    place = matches[0]
    if not place_trust(root, place, purpose='automatic')['automatic_eligible']:
        return None
    return place['name'], place['latitude'], place['longitude']


def _candidate(root, draft):
    point = _public_origin(root, draft)
    return {'label': point[0]} if point else None


def _ready(root, session, model=None):
    draft = session['draft']
    missing = [label for key, label in [('start_minute', '출발 시각'), ('end_minute', '복귀 시각 또는 이용 시간'),
                                        ('transport', '이동수단')] if key not in draft]
    info = {'conditions': _conditions(draft), 'origin_candidate': _candidate(root, draft), 'model': model}
    if draft.get('transport') == 'bus':
        return _reply('unsupported', '운행일과 환승 시간표가 없어 버스 코스는 계산할 수 없습니다.',
                      session, suggestions=['자동차 또는 도보로 조건을 바꿔 주세요.'], **info)
    if missing:
        return _reply('needs_input', ' · '.join(missing) + '을 알려주세요.', session, **info)
    return _reply('needs_confirmation', '일정 조건을 확인하고 출발지를 선택해 주세요.', session, **info)


def _origin(root, body, draft):
    choice = body.get('origin_choice')
    if choice == 'candidate':
        point = _public_origin(root, draft)
        if point:
            label, lat, lon = point
            return {'origin_confirmed': True, 'origin_source': 'landmark', 'origin_label': label,
                    'start_lat': lat, 'start_lon': lon, 'end_lat': lat, 'end_lon': lon}
    if choice == 'planner':
        supplied = body.get('origin')
        if not isinstance(supplied, dict):
            raise ValueError('직접 일정 화면에서 출발지를 먼저 확인해 주세요.')
        origin = validate_confirmed_origin(dict(supplied, end_lat=supplied.get('start_lat'), end_lon=supplied.get('start_lon')))
        if draft.get('start_name') and _normalized(origin['origin_label']) != _normalized(draft['start_name']):
            raise ValueError('요청한 출발지와 직접 일정의 출발지가 다릅니다. 같은 기준 장소를 확인해 주세요.')
        return origin
    raise ValueError('화면에 표시된 공개 기준점 또는 직접 일정에서 확인한 출발지를 선택해 주세요.')


def _route(root, draft, origin):
    ids, _ = _named_exclusions(root, draft['exclude_names'])
    request = {key: value for key, value in draft.items() if key not in {'start_name', 'exclude_names'}}
    result = run_agent(root, {**request, **origin, 'excluded_ids': ids, 'include_geometry': False})
    return {key: result[key] for key in ('status', 'message', 'data_mode', 'selection_mode', 'stops', 'totals',
                                         'selected_place_evidence', 'warnings', 'planning_assumptions', 'suggestions')}


def _compare(root, draft, origin, base):
    variants = []
    count = len(base['stops'])
    if count > 1:
        variants.append(('한 곳 줄이기', f'최대 {count - 1}곳으로 변경', {'max_stops': count - 1}))
    if draft['start_minute'] >= 30:
        start = draft['start_minute'] - 30
        variants.append(('출발 앞당기기', f'{_clock(start)} 출발 · 복귀 시각 유지', {'start_minute': start}))
    if not count and draft['budget_krw'] <= 9990000:
        budget = draft['budget_krw'] + 10000
        variants.append(('이동비 한도 늘리기', f'추정 이동비 한도 {budget:,}원', {'budget_krw': budget}))
    return [{'label': label, 'condition_change': change, 'route': _route(root, {**draft, **edit}, origin)}
            for label, change, edit in variants[:2]]


def _food(root, fields):
    month, groups = fields.get('month'), fields.get('audiences')
    if not month or not groups:
        raise ValueError('비교할 월과 집단을 알려주세요. 예를 들어 “도민과 내국인 6월 외식 업종 비중을 비교해줘”라고 입력해 주세요.')
    if fields.get('region', 'all') != 'all':
        raise ValueError('소비 구성비는 제주 전체 자료입니다. 지역별 비중을 비교할 수 없습니다.')
    model = root/'models_audience/audience_model.json'
    results = [predict_audience(model, group, month) for group in groups]
    shares = [{row['name']: row['share'] for row in value['categories']} for value in results]
    period = results[0]['observation_period']
    return {'title': f'{month}월 식음료 업종 이용건수 구성비', 'columns': ['업종', *[_GROUP_LABELS[g] for g in groups]],
            'rows': [[name, *[f'{group[name] * 100:.1f}%' for group in shares]] for name in shares[0]],
            'sources': [{'name': '제주데이터허브 카드 이용 정보 1048', 'url': results[0]['source_url']}],
            'notes': [f"관측 기간 {period['start']}~{period['end']}",
                      '제주 전체 8개 식음료 업종의 과거 이용건수에서 추정한 구성비입니다.']}


def _mobility(root, fields, today):
    periods = fields.get('periods') or ['all']
    dates = [dt.date.fromisoformat(fields['date'])] if fields.get('date') else []
    for weekday in fields.get('weekdays', []):
        dates.append(today + dt.timedelta(days=(weekday - today.weekday()) % 7))
    dates = list(dict.fromkeys(dates))
    if not dates:
        raise ValueError('날짜나 요일을 알려주세요. 예를 들어 “토요일 오전과 오후 버스 승차를 비교해줘”라고 입력해 주세요.')
    if fields.get('region', 'all') != 'all':
        raise ValueError('버스 승차 자료는 제주 전체 집계입니다. 지역별로 비교할 수 없습니다.')
    rows = []
    for day in dates:
        result = mobility_insight(root, day.isoformat(), 'all')
        for period in periods:
            for slot in result['slots']:
                start = int(slot['label'].split('시', 1)[0])
                match = (period == 'all' or period == 'morning' and start in {7, 10}
                         or period == 'afternoon' and start in {13, 16}
                         or period == 'daytime' and start in {10, 13, 16}
                         or period == 'evening' and start in {19, 22})
                if match:
                    rows.append([f'{day.isoformat()} ({_WEEKDAYS[day.weekday()]})', _PERIOD_LABELS[period],
                                 slot['label'], f"{slot['predicted_users_per_hour']:,.1f}명/시간"])
    observed = result['observation_period']
    return {'title': '제주 전체 일반승차 시간대 비교', 'columns': ['기준 날짜', '구분', '시간대', '추정 승차'], 'rows': rows,
            'sources': [{'name': '제주데이터허브 일별 시간대별 버스 승차 512', 'url': 'https://www.jejudatahub.net/data/view/data/512'}],
            'notes': [f"관측 기간 {observed['start']}~{observed['end']}",
                      '제주 전체 일반승차의 과거 집계를 학습한 시간당 추정치입니다. 요일만 입력하면 가장 가까운 해당 요일을 기준으로 계산합니다.']}


def _confirm(root, body, session, action):
    draft = session.get('draft')
    if not draft:
        return _reply('needs_input', '여행 조건을 먼저 입력해 주세요.', session)
    readiness = _ready(root, session)
    if readiness['status'] != 'needs_confirmation':
        return readiness
    try:
        origin = _origin(root, body, draft)
        origin_key = _mac(json.dumps(origin, sort_keys=True).encode())
        if action == 'alternatives' and session.get('origin_key') != origin_key:
            raise ValueError('비교 전에 현재 출발지로 기본 코스를 다시 확인해 주세요.')
        route = _route(root, draft, origin)
    except ValueError as exc:
        from .place_trust import TrustPolicyError
        if isinstance(exc, TrustPolicyError):
            raise
        return _reply('needs_input', str(exc), session, conditions=_conditions(draft), origin_candidate=_candidate(root, draft))
    session = {**session, 'origin_key': origin_key, 'stop_count': len(route['stops'])}
    alternatives = _compare(root, draft, origin, route) if action == 'alternatives' or route['status'] == 'infeasible' else []
    conditions = {**_conditions(draft), '출발과 복귀': origin['origin_label']}
    return _reply(route['status'], route['message'], session, route=route, conditions=conditions,
                  alternatives=alternatives, can_compare=True, suggestions=route['suggestions'])


def run_assistant(root, body):
    """Dispatch structured local requests; only an explicit confirmation calculates a route."""
    root = Path(root)
    if not isinstance(body, dict):
        raise ValueError('요청은 JSON 객체여야 합니다.')
    session = _decode(body.get('state'))
    action = body.get('action', 'message')
    if action in ('confirm', 'alternatives'):
        return _confirm(root, body, session, action)
    if action != 'message':
        raise ValueError('지원하지 않는 대화 요청입니다.')
    day = _today()
    from .extensions import assistant_extension
    try:
        extension = assistant_extension(root, body.get('message'))
    except ValueError as exc:
        return _reply('needs_input', str(exc), session)
    if extension is not None:
        return _reply(extension.pop('status'), extension.pop('message'), session, **extension)
    parsed = parse_request(body.get('message'), today=day, pending=bool(session.get('draft')))
    intent, fields = parsed['intent'], parsed['fields']
    if parsed.get('clarification'):
        return _reply('needs_input', parsed['clarification'], session, model=parsed.get('model'))
    try:
        if intent in ('plan', 'revise'):
            if intent == 'revise' and not session.get('draft'):
                raise ValueError('수정할 일정이 없습니다. 출발지와 여행 시간부터 입력해 주세요.')
            if not fields:
                raise ValueError('바꿀 날짜, 시각, 장소 또는 방문 수를 알려주세요.')
            draft, duration = _draft_update(root, parsed, session, day)
            updated = {'draft': draft}
            if duration is not None:
                updated['duration_limit'] = duration
            return _ready(root, updated, parsed.get('model'))
        if intent == 'food':
            return _reply('ok', '제주 자료에서 요청한 소비 구성을 계산했습니다.', session, analysis=_food(root, fields))
        if intent == 'mobility':
            return _reply('ok', '제주 자료에서 요청한 승차 시간대를 비교했습니다.', session, analysis=_mobility(root, fields, day))
        if intent == 'search':
            places = search_assistant(root, fields['query'], kind=fields.get('kind', 'attraction'), region=fields.get('region', 'all'))
            return _reply('ok', f'출처가 연결된 장소 기록 {len(places)}건을 찾았습니다.' if places else '요청과 연결되는 장소 근거를 찾지 못했습니다.',
                          session, places=places, model=parsed.get('model'))
    except ValueError as exc:
        from .place_trust import TrustPolicyError
        if isinstance(exc, TrustPolicyError):
            raise
        return _reply('needs_input', str(exc), session, model=parsed.get('model'))
    return _reply('needs_input', '일정 조건, 관광지·음식점 검색, 소비·승차 비교 중 원하는 요청을 알려주세요.',
                  session, model=parsed.get('model'))
