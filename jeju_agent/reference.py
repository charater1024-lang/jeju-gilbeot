"""Real place reference catalogue, kept separate from synthetic ML observations."""
from pathlib import Path
from itertools import permutations
import json
import time
from .engine import _validate_request, _travel
from .planning_input import validate_confirmed_origin


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


def plan_destinations(root, request):
    started=time.perf_counter()
    origin=validate_confirmed_origin(request)
    req=_validate_request(request)
    req.update(origin)
    selected=request.get('destination_ids',[])
    if not isinstance(selected,list) or not 1<=len(selected)<=8 or any(not isinstance(i,str) for i in selected):
        raise ValueError('관광지 1~8개를 선택하세요.')
    if len(set(selected))!=len(selected): raise ValueError('같은 관광지를 중복 선택할 수 없습니다.')
    if len(selected)>req['max_stops']:
        raise ValueError('저장한 관광지가 최대 방문 수보다 많습니다. 방문 수를 늘리거나 저장한 장소를 줄여주세요.')
    by_id={p['id']:p for p in catalogue(root)['items']}
    from .tourism_access import resolve_trip_place
    for ident in selected:
        if ident not in by_id:
            found=resolve_trip_place(root,ident)
            if found:by_id[ident]=found
    if any(i not in by_id for i in selected): raise ValueError('목록에 없는 관광지가 있습니다.')
    places=[by_id[i] for i in selected]
    if len({p['id'] for p in places})!=len(places):raise ValueError('같은 실제 장소를 중복 선택할 수 없습니다.')
    warnings=['교차 확인 관광지 또는 음식점 위치로 만든 방문 순서 초안입니다. 관광객 인기도 예측이나 도로 길찾기가 아닙니다.',
              '이동시간은 직선거리 보정 추정이며 도로·보행 제한·운영시간·예약·휴무는 확인하지 않았습니다.',
              '체류시간은 계획용 가정입니다. 비용에는 추정 이동비만 포함되며 입장·식사·주차·대여료는 별도입니다.']
    response={'status':'ok','data_mode':'reference','message':'선택한 실제 장소의 방문 순서 초안입니다.',
              'request':dict(req,destination_ids=selected),'stops':[],'totals':{},'warnings':warnings,'trace':[],
              'selection_mode':'manual','selected_place_evidence':[],'exclusions':[],'suggestions':[],
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
        response.update(status='needs_review',message=f'{blocked_names}: 출처·방문 조건을 먼저 확인해야 하므로 일정 생성을 중단했습니다. 확인 사유를 검토하고 해당 장소를 직접 제외한 뒤 다시 요청해 주세요.',
                        suggestions=['장소별 출처·확인일·검토 사유를 확인해 주세요.',
                                     '방문 조건이 확인되지 않은 장소를 선택 목록에서 직접 제외하거나 운영기관에 확인해 주세요.',
                                     '선택한 장소를 알리지 않고 빼거나 다른 장소로 대체하지 않았습니다.'])
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
    origin=(req['start_lat'],req['start_lon']);end=(req['end_lat'],req['end_lon'])
    points=[origin]+[(p['latitude'],p['longitude']) for p in places]+[end]
    legs={(i,j):_travel(a,b,req['transport']) for i,a in enumerate(points[:-1]) for j,b in enumerate(points[1:],1) if i!=j}
    stays={i:int(p.get('planning_stay_minutes',90)) for i,p in enumerate(places,1)}
    best=None
    for order in permutations(range(1,len(places)+1)):
        path=(0,)+order+(len(points)-1,)
        travel=sum(legs[a,b][0] for a,b in zip(path,path[1:]))
        cost=sum(legs[a,b][1] for a,b in zip(path,path[1:]))
        duration=travel+sum(stays.values())
        if req['start_minute']+duration>req['end_minute'] or cost>req['budget_krw']: continue
        if best is None or (travel,cost,order)<(best[0],best[1],best[2]): best=(travel,cost,order)
    if best is None:
        response.update(status='infeasible',message='선택한 관광지를 모두 방문하고 복귀하기에는 시간이 부족하거나 추정 이동비가 예산을 넘습니다. 장소 수를 줄이거나 시간을 조정해 주세요.')
        trace('순서 탐색','전체 선택 장소를 만족하는 초안을 찾지 못했습니다.','infeasible')
        return response
    total_travel,total_cost,order=best
    clock=req['start_minute'];prev=0
    for idx in order:
        p=places[idx-1];minutes,cost,km=legs[prev,idx]
        arrival=clock+minutes;departure=arrival+stays[idx]
        stop={'poi_id':p['id'],'name':p['name'],'category':p['category'],'latitude':p['latitude'],'longitude':p['longitude'],
          'arrival_minute':arrival,'departure_minute':departure,'stay_minutes':stays[idx],'cost_krw':0,'cost_unknown':True,
          'travel_minutes':minutes,'travel_cost_krw':cost,'travel_km':round(km,2),'source_id':p.get('source_name','visitjeju'),
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
        prev=idx;clock=departure
    back_minutes,back_cost,back_km=legs[prev,len(points)-1]
    response['totals']={'stops':len(places),'duration_minutes':clock+back_minutes-req['start_minute'],
       'end_arrival_minute':clock+back_minutes,'travel_minutes':total_travel,'visit_cost_krw':None,'travel_cost_krw':total_cost,
       'cost_krw':total_cost,'return_travel_minutes':back_minutes,'return_travel_cost_krw':back_cost,
       'return_travel_km':round(back_km,2),'budget_verified':False,'price_unknown_count':len(places)}
    trace('이동시간 계산','장소 사이의 보정거리로 추정했습니다. 실제 도로망은 사용하지 않습니다.')
    trace('순서 탐색','선택한 장소를 모두 포함한 순서를 비교하고 마감과 복귀를 검사했습니다.')
    trace('근거 안내','입장료·영업·예약은 미확인으로 표시하고 이동비만 계산했습니다.')
    return response
