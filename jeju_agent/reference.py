"""Real place reference catalogue, kept separate from synthetic ML observations."""
from pathlib import Path
from itertools import permutations
import json
import time
from .engine import _validate_request, _travel
from .itinerary_travel import ROAD_BASIS, constraint_check, estimate_itinerary, estimate_note, itinerary_totals, road_search_legs
from .planning_input import MAX_MANUAL_STOPS, validate_confirmed_origin


EXACT_SEARCH_STOPS = 8
EXACT_ROAD_RETRY_STOPS = 9
ROAD_RETRY_BEAM = 64


def read_json(path, default):
    path=Path(path)
    # Small configuration files can change within one filesystem clock tick.
    # Read fresh access restrictions instead of caching only their timestamp.
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def catalogue(root):
    from .tourism_access import approved_places
    data=read_json(Path(root)/'data_reference'/'destinations.json',{'items':[],'sources':[]})
    approved={p['id']:p for p in approved_places(root)}
    items=[]
    for raw in data.get('items',[]):
        point=approved.get(raw.get('id'))
        if not point:continue
        point=dict(point)
        for field in ['requires_ferry','requires_access_point']:point[field]=bool(point.get(field) or raw.get(field))
        items.append(point)
    return dict(data,items=items,source_overlap_required=True,note='빅데이터 여행장소와 지도에서 이름·위치를 교차 확인한 대표 관광지입니다.')


def restaurants(root, query='', region='all', limit=6):
    if (Path(root)/'data_reference'/'catalog.sqlite').is_file():
        from .catalog_store import food_search
        return food_search(root,query,region,limit)
    if region not in {'all','east','west','south','north'}:
        raise ValueError('지원하지 않는 지역입니다.')
    try: limit=int(limit)
    except (ValueError,TypeError): raise ValueError('limit는 정수여야 합니다.')
    if not 1<=limit<=50: raise ValueError('limit는 1~50이어야 합니다.')
    dataset=read_json(Path(root)/'data_reference'/'restaurants.json',{'items':[]})
    needle=query.strip().casefold()[:100]
    matching=[p for p in dataset['items'] if (region=='all' or p['region']==region) and
              (not needle or needle in (p['name']+' '+p['address']+' '+p['category']).casefold())]
    return {'items':matching[:limit],'total':len(matching),'source_date':dataset.get('source_date'),
            'note':dataset.get('note','과거 인허가 자료이며 현재 영업 여부는 별도 확인이 필요합니다.'),
            'sort':'alphabetical_not_popularity'}


def _visit_orders(legs, stop_count, destination_index):
    stops = tuple(range(1, stop_count + 1))
    if stop_count <= EXACT_SEARCH_STOPS:
        return permutations(stops)

    # Insert the next stop where it adds the least travel, keeping both endpoints fixed.
    path = [0, destination_index]
    remaining = set(stops)

    def added_travel(stop, position):
        before, after = path[position - 1], path[position]
        incoming, outgoing, bypass = legs[before, stop], legs[stop, after], legs[before, after]
        minutes = incoming[0] + outgoing[0] - bypass[0]
        cost = incoming[1] + outgoing[1] - bypass[1]
        return minutes, cost, stop, position

    while remaining:
        _, _, stop, position = min(
            added_travel(stop, position)
            for stop in remaining for position in range(1, len(path))
        )
        path.insert(position, stop)
        remaining.remove(stop)

    inserted = tuple(path[1:-1])
    return inserted, inserted[::-1], stops


def _feasible_order(orders, legs, terminal, minutes, budget):
    best = None
    for order in orders:
        path = (0,) + order + (terminal,)
        route_legs = [legs.get((a, b)) for a, b in zip(path, path[1:])]
        if None in route_legs:
            continue
        travel = sum(leg[0] for leg in route_legs)
        cost = sum(leg[1] for leg in route_legs)
        candidate = (travel, cost, order)
        if travel <= minutes and cost <= budget and (best is None or candidate < best):
            best = candidate
    return best[2] if best else None


def _road_orders(legs, terminal, minutes, budget):
    stops = range(1, terminal)
    if len(stops) <= EXACT_ROAD_RETRY_STOPS:
        return permutations(stops)

    # Search only the best partial orders for larger saved sets.
    states = [(0, 0, ())]
    for _ in stops:
        expanded = []
        for travel, cost, order in states:
            last = order[-1] if order else 0
            for stop in stops:
                if stop in order:
                    continue
                leg, back = legs.get((last, stop)), legs.get((stop, terminal))
                if leg is None or back is None:
                    continue
                next_travel, next_cost = travel + leg[0], cost + leg[1]
                if next_travel + back[0] <= minutes and next_cost + back[1] <= budget:
                    expanded.append((next_travel, next_cost, order + (stop,)))
        if not expanded:
            return ()
        def projected_return(state):
            travel, cost, order = state
            back = legs[order[-1], terminal]
            return travel + back[0], cost + back[1], order

        states = sorted(expanded, key=projected_return)[:ROAD_RETRY_BEAM]
    return [order for _, _, order in states]


def plan_destinations(root, request):
    started=time.perf_counter()
    origin=validate_confirmed_origin(request)
    all_saved = request.get('max_stops') == 'all'
    req = _validate_request(dict(request, max_stops=EXACT_SEARCH_STOPS) if all_saved else request)
    req.update(origin)
    if all_saved:
        req['max_stops'] = 'all'
    include_geometry=req.get('include_geometry',True)
    if not isinstance(include_geometry,bool):raise ValueError('include_geometry는 true 또는 false여야 합니다.')
    selected=request.get('destination_ids',[])
    selection_limit = MAX_MANUAL_STOPS if all_saved else EXACT_SEARCH_STOPS
    if not isinstance(selected, list) or not selected or any(not isinstance(ident, str) for ident in selected):
        raise ValueError('일정에 담은 장소를 1곳 이상 선택해 주세요.')
    if len(selected) > selection_limit:
        if not all_saved:
            raise ValueError('8곳을 넘으면 방문 수에서 담아둔 장소 모두를 선택해 주세요.')
        raise ValueError(f'담아둔 장소는 한 번에 최대 {MAX_MANUAL_STOPS}곳까지 계산할 수 있어요.')
    if len(set(selected))!=len(selected): raise ValueError('같은 관광지를 중복 선택할 수 없습니다.')
    if not all_saved and len(selected) > req['max_stops']:
        raise ValueError('담은 장소가 최대 방문 수보다 많습니다. 방문 수를 늘리거나 담아둔 장소 모두를 선택해 주세요.')
    by_id={p['id']:p for p in catalogue(root)['items']}
    from .tourism_access import resolve_trip_place
    for ident in selected:
        if ident not in by_id:
            found=resolve_trip_place(root,ident)
            if found:by_id[ident]=found
    if any(i not in by_id for i in selected): raise ValueError('목록에 없는 관광지가 있습니다.')
    places = [by_id[ident] for ident in selected]
    if len({p['id'] for p in places})!=len(places):raise ValueError('같은 실제 장소를 중복 선택할 수 없습니다.')
    warnings=['교차 확인 관광지 또는 음식점 위치로 만든 방문 순서 초안입니다. 운영시간·예약·휴무와 실제 입구는 방문 전에 확인해 주세요.',
              '체류시간은 계획용 가정입니다. 비용에는 추정 이동비만 포함되며 입장·식사·주차·대여료는 별도입니다.']
    response={'status':'ok','data_mode':'reference','message':'선택한 실제 장소의 방문 순서 초안입니다.',
              'request':dict(req,destination_ids=selected),'stops':[],'totals':{},'warnings':warnings,'trace':[],
              'selection_mode':'manual','selected_place_evidence':[],'exclusions':[],'suggestions':[],'route_geometry':None,
              'model':{'algorithm':'constraint_search_no_demand_model','trained_through':None,'forecast_date':req['date'],'forecast_scope':'no_demand_forecast'}}
    def trace(agent,detail,status='completed'):
        response['trace'].append({'agent':agent,'detail':detail,'status':status,'duration_ms':round((time.perf_counter()-started)*1000,3)})
    trace('요청 해석','선택한 관광지와 시간·이동 조건을 확인했습니다.')
    trace('관광지 확인',f'교차 확인 관광지 또는 음식점 검색에서 선택한 위치 {len(places)}개를 확인했습니다. 실제 입구·운영은 별도 확인이 필요합니다.')
    from .place_trust import place_trust
    trust_by_id={}
    food_ids=[]
    for place in places:
        if place.get('kind')=='food':
            food_ids.append(place['id'])
            response['selected_place_evidence'].append({
                'id':place['id'],'name':place['name'],'kind':'food',
                'trust_scope':'food_reference_not_tourism_policy','tourism_policy_applied':False,
                'status':'reference_only','current_operation_verified':False,
                'sources':[{'kind':'food_reference','name':place.get('source_name') or '음식점 출처 기록',
                            'url':place['source_url'],'checked_at':place.get('source_date'),
                            'snapshot_at':place.get('snapshot_at'),'date_kind':'source_record'}],
                'warnings':['음식점은 별도 검색에서 선택한 위치 참조이며 관광지 신뢰정책 검사 대상이 아닙니다. 현재 영업·메뉴·요금은 확인하지 않았습니다.']})
            continue
        # A manual choice must not conceal a known source or access limitation.
        # Policy errors intentionally propagate so the server fails closed.
        trust=place_trust(root,place,purpose='manual')
        trust_by_id[place['id']]=trust
        response['selected_place_evidence'].append(dict(trust,id=place['id'],name=place['name'],kind='attraction'))
        if trust.get('eligible') is not True or trust.get('automatic_eligible') is not True:
            response['exclusions'].append({'id':place['id'],'name':place['name'],
                                           'reasons':trust.get('reasons',[]),'trust':trust})
    if food_ids:
        response['warnings'].append('선택한 음식점은 출처 위치를 참조하며 관광지 신뢰정책 검사 대상이 아닙니다. 현재 영업·메뉴·요금은 별도 확인해야 합니다.')
    if response['exclusions']:
        blocked_names=', '.join(item['name'] for item in response['exclusions'])
        response.update(
            status='needs_review',
            message=f'{blocked_names}의 출처·방문 조건을 먼저 확인해 주세요. 아래 사유를 확인한 뒤 해당 장소를 이번 일정에서 제외하면 나머지 장소로 다시 계산할 수 있어요.',
            suggestions=['아래 장소별 확인 사유와 출처를 확인해 주세요.'],
        )
        trace('출처와 방문 조건 검사',f"선택한 관광지 중 {len(response['exclusions'])}곳의 확인 근거가 부족하여 전체 일정 생성을 중단했습니다.",'needs_review')
        return response
    trace('출처와 방문 조건 검사','선택한 관광지의 보존된 출처·방문 제약을 검사했습니다. 음식점은 별도 위치 참조이며 현재 운영 확인은 포함하지 않습니다.')
    if req['transport']=='bus' or any(p.get('requires_ferry') for p in places):
        response.update(status='unsupported',message='버스 또는 섬 이동의 운행 시간표가 연결되지 않았습니다. 육상 관광지와 자동차·도보를 선택해 주세요.')
        trace('이동 검토','운행 근거가 부족해 순서 계산을 중단했습니다.','unsupported')
        return response
    if any(p.get('requires_access_point') for p in places):
        response.update(status='unsupported',message='산 정상·자연 장소의 대표 좌표는 차량 도착지가 아닐 수 있습니다. 탐방로 입구·소요시간·예약을 확인해야 하므로 이 초안에서는 해당 장소를 제외해 주세요.')
        trace('접근 지점 검토','관광지 대표 좌표와 실제 접근 지점이 달라 계산을 중단했습니다.','unsupported')
        return response
    places.sort(key=lambda place: place['id'])  # Stable tie-breaking independent of save order.
    origin=(req['start_lat'],req['start_lon']);end=(req['end_lat'],req['end_lon'])
    points=[origin]+[(p['latitude'],p['longitude']) for p in places]+[end]
    stays = {i: int(p.get('planning_stay_minutes', 90)) for i, p in enumerate(places, 1)}
    total_stay = sum(stays.values())
    travel_limit = req['end_minute'] - req['start_minute'] - total_stay
    budget = req['budget_krw']
    terminal = len(points) - 1
    car = req['transport'] == 'car'

    def estimate_order(order):
        ordered_ids = [places[index - 1]['id'] for index in order]
        ordered_points = [origin] + [points[index] for index in order] + [end]
        route_legs, estimate, geometry = estimate_itinerary(root, req, ordered_ids, ordered_points)
        return route_legs, estimate, geometry, constraint_check(req, route_legs, total_stay)

    def fits(checked):
        return checked is not None and checked[3]['within_deadline'] and checked[3]['within_budget']

    order = None
    checked = None
    used_road_search = False
    if travel_limit >= 0:
        if car and len(places) == 1:
            # The only order can be measured directly, even if the approximate leg would fail.
            order = (1,)
        else:
            legs = {(i, j): _travel(a, b, req['transport'])
                    for i, a in enumerate(points[:-1]) for j, b in enumerate(points[1:], 1) if i != j}
            order = _feasible_order(_visit_orders(legs, len(places), terminal), legs, terminal, travel_limit, budget)
        if order is not None:
            checked = estimate_order(order)
        if car and len(places) > 1 and not fits(checked):
            road_legs = road_search_legs(root, req, points, total_stay)
            if road_legs:
                road_orders = _road_orders(road_legs, terminal, travel_limit, budget)
                alternative = _feasible_order(road_orders, road_legs, terminal, travel_limit, budget)
                if alternative is not None and alternative != order:
                    alternative_checked = estimate_order(alternative)
                    if fits(alternative_checked) or checked is None:
                        order, checked = alternative, alternative_checked
                        used_road_search = True

    if checked is None:
        response.update(status='infeasible',
                        message=f'{len(places)}곳을 모두 방문하면서 시간과 이동비 한도를 충족하는 순서를 찾지 못했어요. 장소를 줄이거나 시간·이동비 한도를 조정해 주세요.')
        trace('순서 탐색','전체 선택 장소를 만족하는 초안을 찾지 못했습니다.','infeasible')
        return response
    ordered_places = [places[index - 1] for index in order]
    route_legs, estimate, geometry, check = checked
    response.update(travel_estimate=estimate,constraint_check=check)
    note=estimate_note(estimate)
    response['warnings'].append(note)
    trace('이동시간 계산',note)
    if not (check['within_deadline'] and check['within_budget']):
        basis = '자동차 도로 거리' if estimate['basis'] == ROAD_BASIS else '보정 직선거리'
        response.update(status='infeasible',
                        message=f'{basis}로 계산한 방문 순서가 도착 마감 또는 이동비 한도를 넘습니다.',
                        suggestions=['방문 장소를 줄이거나 출발·도착 시각과 이동비 한도를 확인해 주세요.'])
        trace('순서 탐색', f'{basis}로 검사한 방문 순서는 시간과 이동비 조건을 함께 충족하지 못했습니다.', 'infeasible')
        return response

    clock=req['start_minute']
    for idx,p,(minutes,cost,km) in zip(order,ordered_places,route_legs):
        arrival=clock+minutes;departure=arrival+stays[idx]
        stop={'poi_id':p['id'],'name':p['name'],'category':p['category'],'latitude':p['latitude'],'longitude':p['longitude'],
          'arrival_minute':arrival,'departure_minute':departure,'stay_minutes':stays[idx],'cost_krw':0,'cost_unknown':True,
          'travel_minutes':minutes,'travel_cost_krw':cost,'travel_km':round(km,3),'travel_basis':estimate['basis'],'source_id':p.get('source_name','visitjeju'),
          'source_url':p['source_url'],'image':p.get('image'),'predicted_visits':None,'learned_score':None,'preference_score':None,'score':None,'demand_source_ids':[],
          'kind':p.get('kind','attraction'),'source_overlap_verified':p.get('source_overlap_verified') is True}
        if p['id'] in trust_by_id:
            stop.update(trust=trust_by_id[p['id']],cross_source=p.get('cross_source'),
                        tourism_guide_available=p.get('tourism_guide_available',False),
                        tourism_guide=p.get('tourism_guide'),map_name=p.get('map_name'),
                        trust_scope='tourism_source_and_access_policy')
        else:
            stop.update(trust_scope='food_reference_not_tourism_policy',tourism_policy_applied=False,
                        source_scope_note='음식점 출처 위치 참조이며 관광지 신뢰정책 검사 대상이 아닙니다. 현재 영업·메뉴·요금은 미확인입니다.')
        response['stops'].append(stop)
        clock=departure
    response['totals']=itinerary_totals(req,route_legs,estimate,check,len(places))
    if include_geometry:response['route_geometry']=geometry
    search_note = ('이동시간이 덜 늘어나는 위치에 장소를 차례로 넣어 전체 방문 순서의 후보를 만들었습니다.'
                   if len(places) > EXACT_SEARCH_STOPS else
                   '선택한 장소를 모두 포함한 방문 순서를 비교했습니다.')
    if used_road_search:
        search_note = '도로 거리로 확인한 이동시간·비용을 사용해 다른 방문 순서를 탐색했습니다.'
    trace('순서 탐색', search_note + ' 선택한 순서의 이동시간·비용과 마감을 검사했습니다.')
    trace('근거 안내','입장료·영업·예약은 미확인으로 표시하고 이동비만 계산했습니다.')
    return response
