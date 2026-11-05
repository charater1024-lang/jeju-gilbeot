"""Bounded, source-grounded orchestration for real Jeju sightseeing drafts.

This module selects only locally approved, policy-eligible public places. It
does not infer popularity, current opening, real-time traffic or private data.
"""
from __future__ import annotations

import math
from pathlib import Path
import time

from .engine import _travel, _validate_request
from .discovery import _normalized
from .reference import plan_destinations
from .model_runtime_v20 import active_tourism_search as search_tourism
from .planning_input import validate_confirmed_origin

REGIONS = {'all', 'east', 'west', 'south', 'north'}
MAX_CANDIDATES = 24
BEAM_WIDTH = 64
REQUEST_FIELDS = {'date', 'transport', 'start_lat', 'start_lon', 'end_lat',
                  'end_lon', 'start_minute', 'end_minute', 'budget_krw', 'max_stops'}
# These are explicitly supported request endings, not an open-ended language parser.
NAME_REQUEST_ENDINGS = ('추천', '추천해줘', '추천해주세요', '추천해요',
                        '보여줘', '보여주세요', '가고싶어', '가고싶어요',
                        '에가고싶어', '에가고싶어요', '을추천해줘',
                        '를추천해줘', '을추천해주세요', '를추천해주세요')


def _named_query_match(query, item):
    """Accept a name or an exact known name plus a small request vocabulary."""
    key = _normalized(query)
    if not key:
        return False
    names = {_normalized(item.get(field, '')) for field in ['name', 'map_name']}
    names.discard('')
    return any(key in name or any(key == name + ending for ending in NAME_REQUEST_ENDINGS)
               for name in names)


def _request(body):
    origin = validate_confirmed_origin(body)
    req = _validate_request({key: body[key] for key in REQUEST_FIELDS if key in body})
    query, region = body.get('query', ''), body.get('region', 'all')
    if not isinstance(query, str) or len(query) > 100:
        raise ValueError('관심 검색어는 100자 이내 문자열이어야 합니다.')
    if not isinstance(region, str) or region not in REGIONS:
        raise ValueError('관심 지역을 확인하세요.')
    excluded = body.get('excluded_ids', [])
    if not isinstance(excluded, list) or len(excluded) > 68 or any(
            not isinstance(value, str) or not 1 <= len(value) <= 120 for value in excluded):
        raise ValueError('제외 장소는 공개 ID 최대 68개의 목록이어야 합니다.')
    include_geometry = body.get('include_geometry', True)
    if not isinstance(include_geometry, bool):
        raise ValueError('include_geometry는 true 또는 false여야 합니다.')
    req.update(origin)
    req.update(query=query.strip(), region=region, excluded_ids=sorted(set(excluded)),
               include_geometry=include_geometry)
    return req


def _assumptions(mode):
    if mode == 'bus':
        return [{'item': '이동수단', 'basis': '운행일·환승·막차 근거가 없어 버스 코스는 계산하지 않음'}]
    return [
        {'item': '이동시간', 'basis': '직선거리 보정과 가정 속도',
         'distance_factor': 1.35 if mode == 'car' else 1.2,
         'speed_kmh': 35 if mode == 'car' else 4,
         'verified_road_travel_time': False},
        {'item': '체류시간', 'basis': '장소의 계획용 값 또는 기본 90분',
         'observed_visit_duration': False},
        {'item': '비용', 'basis': '자동차는 보정거리 1km당 250원, 도보는 0원인 이동비 가정',
         'includes_admission_food_parking_rental': False},
        {'item': '방문 가능 조건', 'basis': '알려진 접근 제한은 제외하되 현재 개방·운영은 미확인',
         'current_operation_verified': False},
    ]


def _base(req):
    return {'status': 'infeasible', 'data_mode': 'reference', 'selection_mode': 'automatic',
            'message': '조건을 만족하는 실제 장소 코스를 찾지 못했습니다.',
            'request': req, 'stops': [], 'totals': {}, 'trace': [], 'warnings': [],
            'selected_place_evidence': [], 'exclusions': [],
            'planning_assumptions': _assumptions(req['transport']),
            'suggestions': [], 'route_geometry': None,
            'orchestrator': {'id': 'jeju_evidence_route_agent_v16', 'version': 16,
                             'mode': 'bounded_tool_orchestration', 'runtime_llm': False,
                             'tools': ['tourism_tfidf', 'place_trust', 'constraint_planner', 'offline_road_reference'],
                             'popularity_or_personal_preference_model_used': False},
            'privacy': {'precise_location_persisted': False, 'trace_contains_precise_location': False,
                        'export_origin_coordinates': False},
            'model': {'algorithm': 'trusted_real_place_bounded_constraint_search',
                      'forecast_scope': 'no_popularity_or_demand_forecast'}}


def _bounded_select(candidates, req):
    """Use a small deterministic beam; never claim a global optimum."""
    start = (req['start_lat'], req['start_lon'])
    end = (req['end_lat'], req['end_lon'])
    points = [start] + [(p['latitude'], p['longitude']) for p in candidates] + [end]
    terminal = len(points) - 1
    legs = {(a, b): _travel(points[a], points[b], req['transport'])
            for a in range(terminal) for b in range(1, terminal+1) if a != b}
    stays = {i: int(p.get('planning_stay_minutes', 90)) for i, p in enumerate(candidates, 1)}
    if any(not 1 <= stay <= 1440 for stay in stays.values()):
        raise ValueError('장소의 계획용 체류시간이 올바르지 않습니다.')
    # State = (ordered candidate indexes, travelled minutes, stay minutes, cost).
    beam = [((), 0, 0, 0)]
    best = None
    considered = 0
    available = req['end_minute'] - req['start_minute']

    def key(state):
        route, travel, visit, cost = state
        back = legs[route[-1], terminal]
        return (travel+back[0], cost+back[1], route)

    for _depth in range(min(req['max_stops'], len(candidates))):
        expanded = []
        seen_sets = {}
        for route, travel, visit, cost in beam:
            last = route[-1] if route else 0
            for index in range(1, len(candidates)+1):
                if index in route:
                    continue
                considered += 1
                leg, back = legs[last, index], legs[index, terminal]
                new = (route+(index,), travel+leg[0], visit+stays[index], cost+leg[1])
                if new[1]+new[2]+back[0] > available or new[3]+back[1] > req['budget_krw']:
                    continue
                # Retain the best route for each set and last point before pruning.
                identity = (frozenset(new[0]), index)
                previous = seen_sets.get(identity)
                if previous is None or key(new) < key(previous):
                    seen_sets[identity] = new
        expanded = sorted(seen_sets.values(), key=key)[:BEAM_WIDTH]
        if not expanded:
            break
        beam = expanded
        best = beam[0]
    return ([candidates[index-1]['id'] for index in best[0]] if best else []), considered


def run_agent(root, body):
    """Validate -> retrieve -> trust -> select -> schedule -> route -> explain."""
    root = Path(root)
    started = time.perf_counter()
    req = _request(body)
    response = _base(req)

    def trace(name, stage_started, detail, status='completed'):
        response['trace'].append({'agent': name, 'status': status, 'detail': detail,
                                  'duration_ms': round((time.perf_counter()-stage_started)*1000, 3)})

    trace('요청과 출발 기준 확인', started,
          '사용자가 확인한 출발·복귀 위치와 시간·수단·이동비 조건을 검사했습니다.')
    if any(term in _normalized(req['query']) for term in (
            '빼고', '빼줘', '빼주', '제외', '말고', '싫', '아닌', '아니고',
            '안가', '안갈', '가지않', '원하지', '불포함', '비선호', '피하고', '피해서')):
        response.update(status='needs_clarification',
                        message='제외 조건이 포함된 문장은 현재 관심 검색어로 해석할 수 없습니다.',
                        suggestions=['관심 검색어에는 방문하고 싶은 장소명 또는 테마만 입력해 주세요.',
                                     '방문하지 않을 장소는 추천 결과의 장소 제외 기능으로 지정한 뒤 다시 추천해 주세요.'])
        trace('검색 조건 확인', time.perf_counter(),
              '제외 표현을 긍정 검색으로 처리하지 않고 지원하는 입력 방법을 안내했습니다.',
              'needs_clarification')
        return response
    if req['transport'] == 'bus':
        response.update(status='unsupported', message='버스 운행일·환승·막차 시간표가 연결되지 않아 자동 코스를 구성하지 않습니다.',
                        suggestions=['자동차 또는 도보 조건을 선택해 주세요.'])
        trace('지원 범위 확인', time.perf_counter(), '운행 근거가 부족한 이동수단의 계산을 중단했습니다.', 'unsupported')
        return response

    step = time.perf_counter()
    result = search_tourism(root, {'query': req['query'], 'region': req['region'],
                                  'kind': 'attraction', 'limit': 100,
                                  'location': {'latitude': req['start_lat'], 'longitude': req['start_lon']},
                                  'radius_km': 100})
    trace('실제 관광 후보 검색', step, f"교차확인 관광 색인에서 조건에 맞는 {len(result['items'])}개 후보를 조회했습니다.")
    step = time.perf_counter()
    from .place_trust import place_trust
    exclusions, eligible, evidence, seen = [], [], {}, set()
    user_exclusions = set(req['excluded_ids'])
    for item in result['items']:
        ident = item.get('id')
        if not isinstance(ident, str) or ident in seen:
            continue
        seen.add(ident)
        if ident in user_exclusions:
            exclusions.append({'id': ident, 'name': item.get('name', ''),
                               'reasons': [{'code': 'user_excluded', 'message': '이용자가 이번 코스에서 제외한 장소입니다.'}]})
            continue
        # Character n-gram overlap alone must not manufacture a theme match.
        query_key = _normalized(req['query'])
        named_match = _named_query_match(req['query'], item)
        if query_key and not named_match and item.get('theme_classification_match') is not True:
            exclusions.append({'id': ident, 'name': item.get('name', ''), 'reasons': [
                {'code': 'query_not_grounded', 'message': '문자 일부만 겹치며 장소명 또는 관측 분류에서 요청 테마를 확인하지 못했습니다.'}]})
            continue
        trust = place_trust(root, item, purpose='automatic')
        if trust.get('eligible') is not True or trust.get('automatic_eligible') is not True:
            exclusions.append({'id': ident, 'name': item.get('name', ''),
                               'reasons': trust.get('reasons', []), 'trust': trust})
            continue
        if item.get('requires_ferry') or item.get('requires_access_point'):
            exclusions.append({'id': ident, 'name': item.get('name', ''), 'reasons': [
                {'code': 'unsupported_access', 'message': '배편·탐방 입구 확인이 필요한 장소입니다.'}]})
            continue
        point = (item.get('latitude'), item.get('longitude'))
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
            continue
        if not 32.9 <= point[0] <= 33.8 or not 126 <= point[1] <= 127.05:
            continue
        eligible.append(item)
        evidence[ident] = trust
    response['exclusions'] = exclusions
    trace('출처와 방문 조건 검사', step,
          f"공식 소개·교차확인·정책 검사를 통과한 {len(eligible)}개 후보를 남기고 확인 근거가 부족한 후보를 제외했습니다.")
    # Tourism retrieval orders related tiers then distance. Keep the bound explicit.
    candidates = eligible[:MAX_CANDIDATES]
    response['selection_statistics'] = {'matched_candidates': len(result['items']), 'policy_eligible': len(eligible),
                                         'searched_candidates': len(candidates), 'candidate_limit': MAX_CANDIDATES,
                                         'excluded_candidates': len(exclusions), 'beam_width': BEAM_WIDTH,
                                         'objective': '방문 가능한 장소 수를 우선하고, 같은 수에서는 복귀 포함 추정 이동시간과 이동비가 작은 조합을 비교',
                                         'personalization_or_diversity_optimized': False}
    if not candidates:
        response.update(message='검색 조건과 신뢰성 기준을 함께 충족하는 자동 추천 장소가 없습니다.',
                        suggestions=['짧은 장소명 또는 해변·박물관·정원 같은 확인 가능한 테마와 지역을 선택해 주세요.', '장소를 직접 검색해 공식 원문과 접근 조건을 확인할 수 있습니다.'])
        trace('근거와 조건 조정 안내', time.perf_counter(), '검색어나 신뢰성 기준을 완화해 임의 장소를 채우지 않고, 후보가 없는 이유와 변경 가능한 조건을 안내했습니다.', 'infeasible')
        return response
    step = time.perf_counter()
    selected, considered = _bounded_select(candidates, req)
    response['selection_statistics']['considered_extensions'] = considered
    trace('장소 선택과 코스 탐색', step,
          f"실제 {len(candidates)}개 후보에서 복귀 시간·계획용 체류·추정 이동비를 검사해 {len(selected)}곳을 선택했습니다.")
    if not selected:
        response.update(message='신뢰성 기준을 통과한 장소를 방문하고 복귀하기에는 시간 또는 추정 이동비 조건이 부족합니다.',
                        suggestions=['이용 시간을 늘리거나 출발·복귀 지점을 조정해 주세요.', '도보라면 가까운 지역으로 범위를 좁혀 주세요.'])
        trace('근거와 조건 조정 안내', time.perf_counter(), '시간·이동비를 초과한 코스를 성공으로 표시하지 않고 조건 조정안을 제공합니다.', 'infeasible')
        return response

    step = time.perf_counter()
    planned = plan_destinations(root, dict(req, destination_ids=selected))
    # Existing planner performs a complete permutation check for only this small set.
    response.update(status=planned['status'], message=planned['message'],
                    stops=planned['stops'], totals=planned['totals'],
                    request=dict(req, destination_ids=selected), warnings=planned['warnings'])
    trace('일정과 복귀 재검사', step, '선택된 장소의 순서를 비교하고 시간·이동비·복귀 조건을 다시 검사했습니다.',
          'completed' if planned['status'] == 'ok' else planned['status'])
    if planned['status'] != 'ok':
        response['suggestions'] = ['장소 수 또는 이용 시간을 조정하고 다시 요청해 주세요.']
        return response
    indexed = {item['id']: item for item in candidates}
    for stop in response['stops']:
        item = indexed[stop['poi_id']]
        trust = evidence[item['id']]
        reason = '명부·지도 교차확인과 공식 소개 근거를 통과했고, 요청한 지역·검색어와 시간·거리 조건으로 선택했습니다.'
        stop.update(trust=trust, selection_reason=reason,
                    source_overlap_verified=True, cross_source=item.get('cross_source'),
                    tourism_guide_available=item.get('tourism_guide_available', False),
                    tourism_guide=item.get('tourism_guide'), map_name=item.get('map_name'))
        response['selected_place_evidence'].append(dict(trust, id=item['id'], name=item['name'], selection_reason=reason))
    response['message'] = f"출처와 접근 조건을 검사한 실제 장소 {len(response['stops'])}곳의 추천 순서 초안입니다."
    response['warnings'] = list(dict.fromkeys(response['warnings'] + [
        '현재 영업·개방·요금·예약·실제 입구는 원문 또는 운영기관에서 방문 전에 확인해야 합니다.',
        '후보 수와 탐색량을 제한해 구성한 초안이며 모든 조합의 전역 최적 코스를 보장하지 않습니다.',
        '소비·승차 전체집계는 장소별 인기나 개인 선호 점수로 사용하지 않았습니다.',
    ]))
    if len(eligible) > len(candidates):
        response['warnings'].append(f'검색 관련도와 거리순의 상위 {MAX_CANDIDATES}개 후보 안에서 코스를 탐색했습니다.')
    step = time.perf_counter()
    if req['include_geometry']:
        from .roads import route_geometry
        try:
            geometry = route_geometry(root, {'destination_ids': [p['poi_id'] for p in response['stops']],
                'transport': req['transport'],
                'origin': {'latitude': req['start_lat'], 'longitude': req['start_lon']},
                'destination': {'latitude': req['end_lat'], 'longitude': req['end_lon']}})
            response['route_geometry'] = geometry
            trace('로컬 지도 연결', step, '공개 OSM 도로의 연결 참고 경로 또는 방문 순서 직선을 준비했습니다. 실제 통행·실시간 소요시간은 미확인입니다.')
        except (ValueError, FileNotFoundError, OSError):
            response['warnings'].append('로컬 도로 연결을 확인하지 못해 일정의 방문 순서만 제공합니다.')
            trace('로컬 지도 연결', step, '도로 연결 자료가 없거나 조건에 맞지 않아 지도 연결 참고 경로를 생략했습니다.', 'unavailable')
    else:
        trace('로컬 지도 연결', step, '요청에서 지도 연결 참고 경로를 생략했습니다.', 'not_requested')
    trace('근거와 확인사항 제공', time.perf_counter(), '장소별 선택 근거·원문·확인일과 계획용 가정·미확인 운영정보를 함께 제공합니다.')
    response['elapsed_ms'] = round((time.perf_counter()-started)*1000, 3)
    return response


plan_auto = run_agent
