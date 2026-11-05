"""Serving boundary: only cross-source attractions, or separately labelled food."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3


def approved_places(root):
    from .tourism import _approved
    path=Path(root)/'data_reference/tourism.sqlite'
    if not path.is_file():return []
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        rows=db.execute("SELECT data_json FROM places WHERE kind='attraction'").fetchall()
    from .tourism_guides import enrich_tourism
    return [enrich_tourism(root,item) for row in rows if _approved(item:=json.loads(row[0]))]


def approved_place(root,ident):
    if not isinstance(ident,str):return None
    direct=next((p for p in approved_places(root) if p['id']==ident),None)
    if direct:return direct
    from .tourism import resolve_tourism_place
    item=resolve_tourism_place(root,ident)
    return item if item and item.get('source_overlap_verified') is True else None


def place_search(root,query='',region='all',limit=12):
    if region not in {'all','east','west','south','north'}:raise ValueError('지원하지 않는 지역입니다.')
    try:limit=int(limit)
    except (ValueError,TypeError):raise ValueError('limit는 정수여야 합니다.')
    if not 1<=limit<=50:raise ValueError('limit는 1~50이어야 합니다.')
    query=str(query).strip().casefold()[:100]
    if len(query)<2:return {'items':[],'total':0,'message':'이름·주소를 두 글자 이상 입력하세요.'}
    rows=[p for p in approved_places(root) if (region=='all' or p.get('region')==region) and query in (p['name']+' '+p.get('map_name','')+' '+p.get('address','')).casefold()]
    rows.sort(key=lambda p:(p['name'],p['id']))
    return {'items':rows[:limit],'total':len(rows),'note':'제주데이터허브 여행장소와 OSM 지도 기록을 교차 확인한 관광지입니다. 현재 운영·실제 입구는 별도 확인하세요.','source_overlap_required':True}


def resolve_trip_place(root,ident):
    item=approved_place(root,ident)
    if item:return item
    from .discovery import resolve_discovery_place
    food=resolve_discovery_place(root,ident)
    if food:return dict(food,kind='food',source_overlap_verified=False)
    # The two existing permit/full-address coordinate joins are food, never attractions.
    path=Path(root)/'data_reference/discovery.sqlite'
    if not isinstance(ident,str) or not ident.startswith('hub1349_') or not path.is_file():return None
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('SELECT * FROM restaurants WHERE coordinate_source IS NOT NULL AND latitude IS NOT NULL AND longitude IS NOT NULL').fetchall()
    for row in rows:
        food=dict(row);source=json.loads(food.get('coordinate_source') or '{}')
        if source.get('place_id')!=ident:continue
        from .catalog_store import access_flags
        ferry,access=access_flags(food['name'],food.get('address') or '',food['latitude'],food['longitude'])
        return {'id':ident,'name':food['name'],'address':food.get('address') or '', 'latitude':food['latitude'],'longitude':food['longitude'],'region':food['region'],'category':food.get('category') or '음식점','kind':'food','featured':False,'source_overlap_verified':False,'source_platform':'jeju_datahub','source_name':'제주데이터허브 음식점 인허가·전체주소 일치 좌표','source_url':food['source_url'],'requires_ferry':ferry,'requires_access_point':access,'planning_stay_minutes':60,'current_opening_verified':False,'menu_verified':False}
    return None
