"""Offline public-OSM road geometry. Reference routing, never turn-by-turn navigation."""
import hashlib,heapq,json,math,sqlite3,time
from functools import lru_cache
from pathlib import Path
from threading import Lock
from contextlib import closing

ALLOWED={'motorway','trunk','primary','secondary','tertiary','unclassified','residential','service','living_street'}
BLOCKED={'no','private','permit','military','agricultural','forestry'}
GRAPH_LOCK=Lock()

def km(a,b):
    lat1,lon1=map(math.radians,a);lat2,lon2=map(math.radians,b)
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 12742*math.asin(min(1,math.sqrt(h)))

def build_roads(root):
    root=Path(root);source=root/'data_raw/osm/jeju_roads_v5.json';out=root/'data_reference';out.mkdir(exist_ok=True)
    raw=json.loads(source.read_text(encoding='utf-8'));elements=raw.get('elements',[])
    nodes={e['id']:(float(e['lat']),float(e['lon'])) for e in elements if e.get('type')=='node' and 'lat' in e and 'lon' in e}
    barriers={e['id'] for e in elements if e.get('type')=='node' and (e.get('tags',{}).get('barrier') in {'block','fence','wall','bollard','turnstile'} or any(e.get('tags',{}).get(k) in BLOCKED for k in ['access','vehicle','motor_vehicle','motorcar']))}
    path=out/'roads.building.sqlite';db=sqlite3.connect(path)
    db.executescript('DROP TABLE IF EXISTS nodes;DROP TABLE IF EXISTS edges;CREATE TABLE nodes(id INTEGER PRIMARY KEY,lat REAL,lon REAL);CREATE TABLE edges(a INTEGER,b INTEGER,km REAL);CREATE INDEX edge_source ON edges(a);')
    edges=[];used=set();base=[];ways_used=0;rejected=0;missing=0
    for way in elements:
        if way.get('type')!='way':continue
        tags=way.get('tags',{});kind=tags.get('highway','');basekind=kind.removesuffix('_link')
        if basekind not in ALLOWED or any(tags.get(k) in BLOCKED for k in ['access','vehicle','motor_vehicle','motorcar']):rejected+=1;continue
        ids=way.get('nodes',[]);oneway=tags.get('oneway','').lower()
        direction=-1 if oneway=='-1' else 1 if oneway in {'yes','1','true'} or tags.get('junction') in {'roundabout','circular'} and oneway not in {'no','0','false'} else 0
        accepted=[]
        for a,b in zip(ids,ids[1:]):
            if a not in nodes or b not in nodes:missing+=1;continue
            if a in barriers or b in barriers:continue
            d=km(nodes[a],nodes[b])
            if not 0<d<25:continue
            if direction>=0:edges.append((a,b,d))
            if direction<=0:edges.append((b,a,d))
            used.update((a,b));accepted.append(a)
        if accepted:
            ways_used+=1
            if basekind in {'motorway','trunk','primary','secondary','tertiary'} and len(base)<6500:
                coords=[[nodes[i][1],nodes[i][0]] for i in ids if i in nodes]
                if len(coords)>1:base.append({'kind':kind,'coordinates':coords})
    db.executemany('INSERT INTO nodes VALUES(?,?,?)',[(i,*nodes[i]) for i in used]);db.executemany('INSERT INTO edges VALUES(?,?,?)',edges);db.commit();db.close();path.replace(out/'roads.sqlite')
    profile={'status':'ready','source':'© OpenStreetMap contributors','license':'ODbL-1.0','source_url':'https://www.openstreetmap.org/copyright','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'snapshot_at':raw.get('osm3s',{}).get('timestamp_osm_base'),'nodes':len(used),'directed_edges':len(edges),'ways_used':ways_used,'ways_excluded':rejected,'barrier_nodes_excluded':len(barriers),'missing_node_references':missing,'base_road_lines':len(base),'limitations':['자동차용 공개 도로 연결 참고 경로입니다. 회전 제한 관계·교통 통제·현재 통행 가능 여부를 반영한 내비게이션이 아닙니다.','OSM의 일방통행·회전교차로·명시적 차량 접근 제한과 일부 노드 장벽을 반영합니다.','입구를 확인한 목적지가 아니며 가까운 도로까지 연결은 점선으로 표시합니다.']}
    (out/'roads_profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'offline_roads.json').write_text(json.dumps({'lines':base,'source':profile['source'],'source_url':profile['source_url'],'license':profile['license'],'snapshot_at':profile['snapshot_at']},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return profile

@lru_cache(maxsize=2)
def _load(path,mtime):
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as db:
        points={i:(lat,lon) for i,lat,lon in db.execute('SELECT id,lat,lon FROM nodes')};adj={i:[] for i in points}
        for a,b,d in db.execute('SELECT a,b,km FROM edges'):adj[a].append((b,d))
    cells={}
    for i,(lat,lon) in points.items():cells.setdefault((math.floor(lat*100),math.floor(lon*100)),[]).append(i)
    return points,adj,cells

def _graph(root):
    path=(Path(root)/'data_reference/roads.sqlite').resolve()
    if not path.exists():return None
    with GRAPH_LOCK:return _load(str(path),path.stat().st_mtime_ns)

def nearest(point,points,cells):
    row,col=math.floor(point[0]*100),math.floor(point[1]*100)
    candidates=[i for r in range(row-2,row+3) for c in range(col-2,col+3) for i in cells.get((r,c),[])]
    if not candidates:return None,None
    d,i=min((km(point,points[i]),i) for i in candidates)
    return (i,d) if d<=1.5 else (None,d)

def astar(start,end,points,adj,maximum=350000):
    if start==end:return [start],0.0
    queue=[(km(points[start],points[end]),0.,start)];cost={start:0.};parent={};visited=0
    while queue:
        _,g,a=heapq.heappop(queue)
        if g>cost.get(a,math.inf)+1e-10:continue
        if a==end:
            path=[a]
            while a!=start:a=parent[a];path.append(a)
            return list(reversed(path)),g
        visited+=1
        if visited>maximum:break
        for b,d in adj.get(a,[]):
            ng=g+d
            if ng+1e-10<cost.get(b,math.inf):
                cost[b]=ng;parent[b]=a;heapq.heappush(queue,(ng+km(points[b],points[end]),ng,b))
    return None,None

def _resolve(root,ident):
    from .tourism_access import resolve_trip_place
    return resolve_trip_place(root,ident)

def route_geometry(root,body):
    root=Path(root);started=time.perf_counter();ids=body.get('destination_ids')
    if not isinstance(ids,list) or not 1<=len(ids)<=8 or len(set(ids))!=len(ids) or any(not isinstance(i,str) for i in ids):raise ValueError('공개 장소 ID 1~8개를 중복 없이 선택하세요.')
    stops=[_resolve(root,i) for i in ids]
    if any(p is None for p in stops):raise ValueError('목록에 없는 장소입니다.')
    if len({p['id'] for p in stops})!=len(stops):raise ValueError('같은 실제 장소를 중복 선택할 수 없습니다.')
    if any(p.get('requires_ferry') or p.get('requires_access_point') for p in stops):raise ValueError('배편·탐방로 입구 확인이 필요한 장소는 자동차 도로 경로에서 제외해 주세요.')
    transport=body.get('transport','car')
    if transport not in {'car','walk'}:raise ValueError('도로 참고 경로는 자동차 또는 도보 방문 순서만 지원합니다.')
    def endpoint(key):
        value=body.get(key)
        if value is None:return None
        if not isinstance(value,dict):raise ValueError('출발·도착 위치 형식을 확인하세요.')
        try:p=(float(value['latitude']),float(value['longitude']))
        except (ValueError,TypeError,KeyError):raise ValueError('출발·도착 좌표를 확인하세요.')
        if not all(math.isfinite(v) for v in p) or not 32.9<=p[0]<=33.8 or not 126<=p[1]<=127.1:raise ValueError('출발·도착 위치는 제주 권역이어야 합니다.')
        return p
    origin=endpoint('origin');destination=endpoint('destination');locations=([origin] if origin else [])+[(p['latitude'],p['longitude']) for p in stops]+([destination] if destination else [])
    direct=[[p[1],p[0]] for p in locations];response={'kind':'straight_line','geometry':{'type':'LineString','coordinates':direct},'coordinates':direct,'stops':stops,'connectors':[],'distance_km':round(sum(km(a,b) for a,b in zip(locations,locations[1:])),3),'warnings':['점선은 방문 순서를 직선으로 연결한 표시이며 실제 도로 경로가 아닙니다.'],'privacy':{'precise_location_persisted':False},'source':'공개 장소 좌표'}
    response['contains_private_location']=bool(origin or destination)
    graph=_graph(root) if transport=='car' else None
    if not graph or len(locations)<2:return response
    points,adj,cells=graph;snapped=[nearest(p,points,cells) for p in locations]
    if any(i is None for i,d in snapped):response['warnings'].append('목적지 가까이 연결 가능한 자동차 도로가 없어 방문 순서만 표시합니다.');return response
    full=[];total=0.
    for (a,_),(b,_) in zip(snapped,snapped[1:]):
        path,d=astar(a,b,points,adj)
        if not path:response['warnings'].append('지도 데이터에서 도로가 이어지지 않아 방문 순서만 표시합니다.');return response
        full.extend(path if not full else path[1:]);total+=d
    coords=[[points[i][1],points[i][0]] for i in full]
    if len(coords)<2:return response
    response.update(kind='road',geometry={'type':'LineString','coordinates':coords},coordinates=coords,distance_km=round(total,3),connectors=[{'from':[p[1],p[0]],'to':[points[i][1],points[i][0]],'distance_m':round(d*1000)} for p,(i,d) in zip(locations,snapped) if d>.005],source='© OpenStreetMap contributors · ODbL',source_url='https://www.openstreetmap.org/copyright',warnings=['OSM 도로 연결 참고 경로입니다. 회전 제한·교통 통제·현재 통행 가능 여부를 반영한 내비게이션이 아닙니다.','점선 연결 구간은 원자료 좌표에서 가까운 도로까지이며 실제 입구를 확인하지 않았습니다.','일정의 시간·이동비는 계획용 추정값이며 이 도로 경로의 실시간 소요시간이 아닙니다.'],elapsed_ms=round((time.perf_counter()-started)*1000,2))
    return response
