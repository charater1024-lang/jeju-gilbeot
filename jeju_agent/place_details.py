"""Source-grounded details for public places; no generated attraction facts."""
import json,sqlite3
from pathlib import Path
from functools import lru_cache
from contextlib import closing

@lru_cache(maxsize=2)
def _food_tags(path,mtime):
    raw=json.loads(Path(path).read_text(encoding='utf-8'))
    return {f"osm_{p['type']}_{p['id']}":p.get('tags',{}) for p in raw.get('elements',[]) if p.get('type') in {'node','way','relation'}}

def place_details(root,ident):
    root=Path(root)
    if not isinstance(ident,str) or not ident or len(ident)>120:raise ValueError('장소 ID를 확인하세요.')
    from .reference import catalogue
    from .tourism_access import resolve_trip_place
    from .discovery import resolve_discovery_place
    from .tourism import resolve_tourism_place
    place=next((dict(p) for p in catalogue(root)['items'] if p['id']==ident),None)
    if place is None:place=resolve_tourism_place(root,ident)
    if place is None:place=resolve_trip_place(root,ident)
    if place is None:place=resolve_discovery_place(root,ident)
    if place is None:
        with closing(sqlite3.connect((root/'data_reference/catalog.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row;row=db.execute('SELECT id,name,address,category,region,status,source_date,source_url FROM restaurants WHERE id=?',(ident,)).fetchone()
            if row:place=dict(row,source_name='제주데이터허브 음식점 인허가',latitude=None,longitude=None)
    if place is None:return None
    place=dict(place)
    if ident.startswith('osm_') and not place.get('observed_tags'):
        source=root/'data_raw/osm/jeju_food_overpass.json'
        if source.exists():place['observed_tags']=_food_tags(str(source.resolve()),source.stat().st_mtime_ns).get(ident,{})
    tags=place.get('observed_tags') or {}
    if not place.get('description') and isinstance(tags,dict):place['description']=tags.get('description:ko') or tags.get('description') or ''
    place['plan_place_id']=place.get('plan_place_id') or (ident if place.get('latitude') is not None else None)
    place['detail_note']='원자료에 실제로 있는 정보만 표시합니다. 현재 영업·요금·입구·메뉴를 확인한 안내가 아닙니다.'
    from .tourism_guides import enrich_tourism
    place=enrich_tourism(root,place)
    return {'item':place,'available':True}
