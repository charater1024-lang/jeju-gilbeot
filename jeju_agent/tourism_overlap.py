"""Conservative, reproducible intersection of two independent place sources.

This module never accepts a map tag by itself as proof of a tourist attraction.
It reads the full OSM source tags because the old normalized file omitted food
and shop tags. All rejected records are retained in a local audit, not served.
"""
from collections import Counter, defaultdict
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata

from .discovery import _distance
from .catalog_store import access_flags, region_for
from .tourism_names import prefer_hub_name

POLICY_ID = 'jeju_hub_osm_exact_name_250m_v1'


def normalized_name(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', str(value or '')).casefold() if c.isalnum())


def valid_point(item):
    lat, lon = item.get('latitude'), item.get('longitude')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in [lat, lon]):
        return None
    return (float(lat), float(lon)) if 32.9 <= lat <= 33.8 and 126 <= lon <= 127.05 else None


def _active(value):
    return bool(value is not None and str(value).strip().casefold() not in {'', 'no', 'none', 'false', '0'})


def classification_reason(tags, policy, food_name_collision=False):
    """Return a rejection reason, or None for an eligible observed category."""
    if not isinstance(tags, dict):return 'missing_full_osm_tags'
    tourism = str(tags.get('tourism') or '').casefold()
    natural = str(tags.get('natural') or '').casefold()
    leisure = str(tags.get('leisure') or '').casefold()
    if tourism in policy['excluded_tourism'] or _active(tags.get('accommodation')):
        return 'lodging_or_camping'
    if any(v.strip().casefold() in policy['excluded_amenity'] for v in str(tags.get('amenity') or '').split(';')):
        return 'food_or_ordinary_amenity'
    if _active(tags.get('shop')):return 'shop'
    if any(_active(tags.get(key)) for key in policy['excluded_infrastructure_keys']):return 'transport_or_utility_infrastructure'
    if _active(tags.get('man_made')) and str(tags['man_made']).casefold() not in policy['allowed_man_made']:
        return 'ordinary_man_made_feature'
    if _active(tags.get('office')) or _active(tags.get('craft')) or _active(tags.get('industrial')):
        return 'ordinary_business_or_industry'
    historic = _active(tags.get('historic'))
    if not (tourism in policy['allowed_tourism'] or natural in policy['allowed_natural'] or leisure in policy['allowed_leisure'] or historic):
        return 'not_eligible_tourist_classification'
    strong = natural in policy['allowed_natural'] or tourism in {'museum', 'gallery', 'zoo', 'aquarium', 'theme_park'} or historic or leisure in policy['allowed_leisure']
    if food_name_collision and not strong:return 'generic_map_tag_conflicts_with_food_permit_name'
    return None


def _public_hub(row):
    return {k:row.get(k) for k in ['id','name','address','latitude','longitude','source_date','source_url']}


def _public_map(row):
    ident=row['id'];match=re.fullmatch(r'osm_tourism_(node|way|relation)_([1-9][0-9]*)',ident)
    return {'id':ident,'name':row['name'],'category':row.get('category'),'latitude':row['latitude'],'longitude':row['longitude'],
            'source_url':f'https://www.openstreetmap.org/{match.group(1)}/{match.group(2)}',
            'observed_tags':dict(row['observed_tags']),'source_date':row.get('source_date'),'snapshot_at':row.get('snapshot_at')}


def match_candidates(map_items, hub_items, featured_items, policy, food_names=()):
    """Pure intersection. Names are never fuzzy-matched or substring-matched."""
    if policy.get('policy_id') != POLICY_ID or policy.get('max_distance_m') != 250:
        raise ValueError('지원하는 관광 교차확인 정책이 아닙니다.')
    hubs=defaultdict(list)
    for row in hub_items:
        key=normalized_name(row.get('name'))
        if key and valid_point(row):hubs[key].append(row)
    food_keys={normalized_name(name) for name in food_names if normalized_name(name)}
    eligible_by_name=defaultdict(list);rejected=[];seen_ids=set()
    for raw in sorted(map_items,key=lambda p:str(p.get('id',''))):
        ident=raw.get('id');name=raw.get('name');point=valid_point(raw)
        item={'osm_id':ident,'name':name}
        reason=None
        if not isinstance(ident,str) or not re.fullmatch(r'osm_tourism_(node|way|relation)_([1-9][0-9]*)',ident) or not normalized_name(name) or point is None:
            reason='invalid_map_id_name_or_coordinate'
        elif ident in seen_ids:reason='duplicate_map_id'
        elif raw.get('_raw_evidence_error'):reason=raw['_raw_evidence_error']
        else:reason=classification_reason(raw.get('observed_tags'),policy,normalized_name(name) in food_keys)
        seen_ids.add(ident)
        if reason:
            rejected.append({**item,'reason':reason});continue
        rows=hubs.get(normalized_name(name),[])
        if not rows:
            rejected.append({**item,'reason':'no_exact_hub_name'});continue
        distances=[(_distance(point,valid_point(row))*1000,row) for row in rows]
        near=[(distance,row) for distance,row in distances if distance<=policy['max_distance_m']]
        if not near:
            rejected.append({**item,'reason':'exact_name_outside_250m','nearest_distance_m':round(min(d for d,_ in distances),3)});continue
        near.sort(key=lambda entry:(entry[0],entry[1]['id']))
        eligible_by_name[normalized_name(name)].append((near[0][0],raw,near))
    accepted_groups=[]
    for name,matches in sorted(eligible_by_name.items()):
        # Complete-link grouping avoids long chains of individually nearby map
        # points turning into one widely separated attraction candidate.
        groups=[]
        for match in sorted(matches,key=lambda entry:entry[1]['id']):
            group=next((g for g in groups if all(_distance(valid_point(match[1]),valid_point(other[1]))*1000<=250 for other in g)),None)
            if group is None:groups.append([match])
            else:group.append(match)
        supports=[{hub['id'] for _,_,near in group for _,hub in near} for group in groups]
        ambiguous={i for i in range(len(groups)) if any(i!=j and supports[i]&supports[j] for j in range(len(groups)))}
        for i,group in enumerate(groups):
            if i in ambiguous:
                for _,raw,near in group:rejected.append({'osm_id':raw['id'],'name':raw['name'],'reason':'ambiguous_separated_map_groups','hub_ids':[hub['id'] for _,hub in near]})
            else:accepted_groups.append(group)
    records=[];aliases={};curated_decisions=[]
    accepted_name_counts=Counter(normalized_name(group[0][1]['name']) for group in accepted_groups)
    for matches in accepted_groups:
        matches.sort(key=lambda entry:(entry[0],entry[1]['id']))
        distance,raw,near=matches[0];hub=near[0][1];hub_id=hub['id'];point=valid_point(raw)
        supporting={h['id']:h for _,_,nearby in matches for _,h in nearby}
        # The map+hub match is established before any official-card enrichment.
        curated=[p for p in featured_items if accepted_name_counts[normalized_name(raw['name'])]==1 and normalized_name(p.get('name'))==normalized_name(raw['name']) and valid_point(p) and any(_distance(valid_point(match[1]),valid_point(p))*1000<=policy['curated_enrichment_max_distance_m'] for match in matches)]
        curated=sorted(curated,key=lambda p:str(p.get('id','')))
        official=curated[0] if len(curated)==1 else None
        if official:
            distance,raw,near=min(matches,key=lambda entry:(_distance(valid_point(entry[1]),valid_point(official)),entry[0],entry[1]['id']))
            hub=near[0][1];hub_id=hub['id'];point=valid_point(raw)
        canonical=official['id'] if official else raw['id']
        if canonical in aliases:raise ValueError('교차확인 관광지 대표 ID가 충돌합니다.')
        tags=dict(raw['observed_tags']);address=str((official or {}).get('address') or raw.get('address') or tags.get('addr:full') or '')
        region=((official or {}).get('region') or region_for(address)) if address else ('east' if point[1]>=126.75 else 'west' if point[1]<=126.4 else 'south' if point[0]<=33.36 else 'north')
        classification=[f'{key}:{tags[key]}' for key in ['tourism','natural','leisure','historic'] if tags.get(key)]
        item=dict(raw)
        for key in [k for k in item if k.startswith('_')]:item.pop(key)
        item.update(id=canonical,name=raw['name'],kind='attraction',category=str(raw.get('category') or '관광·자연 장소'),source_platform='openstreetmap',source_name='제주데이터허브 명부 × OpenStreetMap 교차확인',source_url=_public_map(raw)['source_url'],address=address,region=region,region_quality='official_reference' if official else 'observed_map_address' if address else 'coordinate_sector_heuristic',featured=bool(official),latitude=point[0],longitude=point[1],observed_tags=tags,tags=classification,classifications=classification,image=None,description=str(tags.get('description:ko') or tags.get('description') or ''),description_provenance='observed_osm_description_tag' if tags.get('description:ko') or tags.get('description') else 'not_provided',current_opening_verified=False,popularity_verified=False,routing_access_verified=False,source_overlap_verified=True,coordinate_quality='빅데이터 명부와 명칭·250m 범위가 일치한 지도 좌표 · 실제 입구·현재 운영 미검증',data_license='ODbL-1.0',attribution='© OpenStreetMap contributors',copyright_url='https://www.openstreetmap.org/copyright',source_ids=sorted(supporting)+[p['id'] for _,p,_ in matches])
        if official:
            for key in ['image','image_alt','image_credit','image_source_url','image_license','tags','description','verified_on','duration_minutes','category']:
                if key in official:item[key]=official[key]
            item.update(tags_provenance='editorial_browse_labels_excluded_from_model_training',description_provenance='editorial_browse_summary_excluded_from_model_training',official_source_url=official.get('source_url'))
            item['editorial_enrichment']={'source_id':official['id'],'source_url':official.get('source_url'),'purpose':'photo_and_editorial_metadata_only_not_candidate_acceptance','curated_coordinate_offset_m':round(_distance(point,valid_point(official))*1000,3),'max_offset_m':policy['curated_enrichment_max_distance_m'],'served_coordinate':'matched_osm_coordinate'}
            item['source_ids'].append(official['id'])
        item['cross_source']={'policy_id':POLICY_ID,'match_method':'normalized_exact_name_and_distance','max_distance_m':250,'distance_m':round(distance,3),'hub':_public_hub(hub),'osm':_public_map(raw),'additional_hub_records':[_public_hub(h) for key,h in sorted(supporting.items()) if key!=hub_id],'supporting_hub_records':len(supporting),'hub_address_verified':False,'hub_unique_place_identity_verified':False,'additional_map_records':[_public_map(p) for _,p,_ in matches if p['id']!=raw['id']],'limitation':policy['limitation']}
        item=prefer_hub_name(item)
        ferry,access=access_flags(item['name'],address,*point)
        item['requires_ferry']=bool(ferry or hub.get('requires_ferry') or raw.get('requires_ferry'))
        item['requires_access_point']=bool(access or hub.get('requires_access_point') or raw.get('requires_access_point') or tags.get('natural') in {'peak','volcano','cave_entrance'})
        records.append(item)
        for source_id in item['source_ids']:
            if source_id in aliases and aliases[source_id]!=canonical:raise ValueError('관광 원본 ID 연결이 중복되었습니다.')
            aliases[source_id]=canonical
    for official in featured_items:
        curated_decisions.append({'id':official.get('id'),'name':official.get('name'),'accepted':official.get('id') in aliases,'canonical_id':aliases.get(official.get('id'))})
    audit={'policy_id':POLICY_ID,'max_distance_m':250,'input_map_records':len(map_items),'input_hub_records':len(hub_items),'accepted_map_records':sum(len(v) for v in accepted_groups),'accepted_tourist_places':len(records),'count_definition':'same-name map candidates grouped with maximum pairwise distance 250m; not certified unique tourist attractions','rejected_map_records':len(rejected),'rejection_counts':dict(sorted(Counter(row['reason'] for row in rejected).items())),'food_permit_name_guard_count':len(food_keys),'curated':curated_decisions,'accepted':[{'id':r['id'],'name':r['name'],'source_ids':r['source_ids'],'cross_source':r['cross_source']} for r in records],'rejected':rejected,'limitation':policy['limitation']}
    return records,aliases,audit


def _hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_overlap_records(root):
    root=Path(root).resolve();reference=root/'data_reference'
    policy_path=root/'config/tourism_overlap_policy.json';osm_path=reference/'osm_tourism_places.json';hub_path=reference/'catalog.sqlite'
    if not all(p.is_file() for p in [policy_path,osm_path,hub_path]):raise ValueError('지도·허브·교차확인 정책 원본이 모두 있어야 관광 색인을 만들 수 있습니다.')
    policy=json.loads(policy_path.read_text(encoding='utf-8'));osm=json.loads(osm_path.read_text(encoding='utf-8'))
    if osm.get('data_license')!='ODbL-1.0' or not osm.get('attribution'):raise ValueError('지도 원본 출처·라이선스를 확인하세요.')
    raw_relative=osm.get('raw_file');raw_path=(root/raw_relative).resolve() if isinstance(raw_relative,str) else None
    if raw_path is None or not raw_path.is_relative_to(root) or not raw_path.is_file() or not osm.get('raw_sha256') or _hash(raw_path)!=osm['raw_sha256']:
        raise ValueError('전체 OSM 원본 태그 및 SHA256 근거가 없거나 일치하지 않습니다. 지도 목록으로 대체하지 않습니다.')
    raw=json.loads(raw_path.read_text(encoding='utf-8'));full={f"osm_tourism_{p.get('type')}_{p.get('id')}":p for p in raw.get('elements',[]) if p.get('type') in {'node','way','relation'}}
    maps=[]
    for row in osm.get('items',[]):
        item=dict(row);original=full.get(row.get('id'));item['observed_tags']=dict(original.get('tags',{})) if original else None
        if not original:item['_raw_evidence_error']='missing_raw_osm_element'
        elif not item['observed_tags']:item['_raw_evidence_error']='missing_full_osm_tags'
        else:
            c=original if original.get('type')=='node' else original.get('center',{})
            original_point=valid_point({'latitude':c.get('lat'),'longitude':c.get('lon')})
            if original_point is None or valid_point(item) is None or _distance(original_point,valid_point(item))*1000>1:
                item['_raw_evidence_error']='raw_normalized_coordinate_mismatch'
            raw_names={normalized_name(item['observed_tags'].get(k)) for k in ['name','name:ko','name:en'] if item['observed_tags'].get(k)}
            if normalized_name(item.get('name')) not in raw_names:item['_raw_evidence_error']='raw_normalized_name_mismatch'
        maps.append(item)
    with closing(sqlite3.connect(hub_path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        hubs=[dict(row) for row in db.execute('SELECT id,name,address,latitude,longitude,region,source_date,source_url,requires_ferry,requires_access_point FROM places ORDER BY id')]
        tables={r[0] for r in db.execute('SELECT name FROM sqlite_master')}
        foods=[row[0] for row in db.execute('SELECT name FROM restaurants')] if 'restaurants' in tables else []
    featured_path=reference/'destinations.json';featured=json.loads(featured_path.read_text(encoding='utf-8')).get('items',[]) if featured_path.is_file() else []
    records,aliases,audit=match_candidates(maps,hubs,featured,policy,foods)
    sources={'osm':{'path':'data_reference/osm_tourism_places.json','sha256':_hash(osm_path),'snapshot_at':osm.get('snapshot_at'),'data_license':'ODbL-1.0','attribution':'© OpenStreetMap contributors','copyright_url':'https://www.openstreetmap.org/copyright'},'osm_raw':{'path':raw_path.relative_to(root).as_posix(),'sha256':_hash(raw_path)},'hub1349':{'path':'data_reference/catalog.sqlite','sha256':_hash(hub_path),'reference_date':None},'overlap_policy':{'path':'config/tourism_overlap_policy.json','sha256':_hash(policy_path),'policy_id':POLICY_ID}}
    profile_path=reference/'catalog_profile.json'
    if profile_path.is_file():sources['hub1349']['reference_date']=json.loads(profile_path.read_text(encoding='utf-8')).get('place_source_date')
    if featured_path.is_file():sources['featured']={'path':'data_reference/destinations.json','sha256':_hash(featured_path)}
    audit['sources']=sources
    return records,aliases,sources,audit
