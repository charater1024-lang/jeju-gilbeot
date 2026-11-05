"""Conservative, offline eligibility and evidence checks for real tourist drafts.

This policy verifies source-record integrity and candidate identity, not today's
opening status, entrance access or navigation safety. It performs no network IO.
"""
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

POLICY_ID = 'jeju_place_trust_v15'
GUIDE_PATH = 'data_reference/tourism_guides_v12.json'
GUIDE_HOSTS = {'visitjeju.net','www.visitjeju.net','m.visitjeju.net','korean.visitkorea.or.kr'}


class TrustPolicyError(ValueError):
    """An unavailable or unsupported policy must stop automatic recommendation."""


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
                                    separators=(',',':'),allow_nan=False).encode()).hexdigest()


def identity_digest(item):
    """Stable input fields shared by canonical, search and enriched records."""
    proof=item.get('cross_source') or {}
    return _digest({'id':item.get('id'),'kind':item.get('kind'),
        'latitude':item.get('latitude'),'longitude':item.get('longitude'),
        'source_overlap_verified':item.get('source_overlap_verified'),
        'cross_source':proof,'requires_ferry':bool(item.get('requires_ferry')),
        'requires_access_point':bool(item.get('requires_access_point'))})


@lru_cache(maxsize=128)
def _bytes(path,mtime,size):
    return Path(path).read_bytes()


def _file_bytes(path,maximum=8_000_000):
    stat=path.stat()
    if stat.st_size>maximum:raise ValueError('source metadata is too large')
    return _bytes(str(path.resolve()),stat.st_mtime_ns,stat.st_size)


def _url(value,hosts):
    if not isinstance(value,str) or len(value)>2000:return None
    try:
        parsed=urlsplit(value)
        if parsed.scheme!='https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in {None,443}:return None
    except ValueError:return None
    return value


def _day(value):
    """Accept only an unambiguous calendar date, never a truncated timestamp."""
    if not isinstance(value,str) or len(value)!=10:return None
    try:
        parsed=date.fromisoformat(value)
        return parsed if parsed.isoformat()==value else None
    except ValueError:return None


def _sha256(value):
    return isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value) is not None


def _text(value,maximum=2000):
    return isinstance(value,str) and 0<len(value.strip())<=maximum


def _policy_dates(entry,required=(),optional=()):
    for key in required:
        if _day(entry.get(key)) is None:raise ValueError('invalid review date')
    for key in optional:
        # A missing/null recheck explicitly means that no recheck was performed.
        if entry.get(key) is not None and _day(entry[key]) is None:
            raise ValueError('invalid optional review date')


@lru_cache(maxsize=4)
def _policy(path,mtime,size):
    try:
        data=json.loads(_bytes(path,mtime,size).decode('utf-8'))
        if not isinstance(data,dict) or type(data.get('schema_version')) is not int or data.get('schema_version')!=1 or data.get('policy_id')!=POLICY_ID:raise ValueError('unsupported policy')
        if not isinstance(data.get('max_guide_age_days'),int) or isinstance(data['max_guide_age_days'],bool) or not 1<=data['max_guide_age_days']<=365:raise ValueError('invalid review age')
        if not isinstance(data.get('approved_identity_sha256'),dict) or not data['approved_identity_sha256']:raise ValueError('missing candidate fingerprints')
        if not isinstance(data.get('guide_records'),dict) or not data['guide_records'] or not isinstance(data.get('automatic_exclusions'),dict):raise ValueError('missing source policy')
        if not _sha256(data.get('guide_catalog_sha256')):raise ValueError('missing guide snapshot')
        if any(not isinstance(k,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',k) or not _sha256(v) for k,v in data['approved_identity_sha256'].items()):raise ValueError('invalid candidate fingerprints')
        for ident,entry in data['guide_records'].items():
            if ident not in data['approved_identity_sha256'] or not isinstance(entry,dict):raise ValueError('invalid source receipt')
            if any(not _sha256(entry.get(key)) for key in ['guide_record_sha256','cache_file_sha256','original_page_sha256']):raise ValueError('invalid receipt digest')
            if entry.get('source_cache')!=f'data_raw/tourism/v12/official_fields/{ident}.json':raise ValueError('invalid receipt path')
            _policy_dates(entry,required=['guide_reviewed_at'])
        for ident,entry in data['automatic_exclusions'].items():
            if ident not in data['approved_identity_sha256'] or not isinstance(entry,dict):raise ValueError('invalid exception')
            if not _text(entry.get('code'),120) or not _text(entry.get('reason')) or not _url(entry.get('source_url'),GUIDE_HOSTS):raise ValueError('invalid exception evidence')
            for key,maximum in [('name',180),('review_kind',100)]:
                if key in entry and not _text(entry[key],maximum):raise ValueError('invalid exception description')
            if 'current_operation_verified' in entry and entry['current_operation_verified'] is not False:raise ValueError('unsupported operation claim')
            _policy_dates(entry,required=['reviewed_at','source_reviewed_at'],optional=['public_page_rechecked_at'])
        if not isinstance(data.get('name_notices',{}),dict):raise ValueError('invalid name notices')
        for ident,entry in data.get('name_notices',{}).items():
            if ident not in data['approved_identity_sha256'] or not isinstance(entry,dict):raise ValueError('invalid name notice')
            if not _text(entry.get('message')) or not _url(entry.get('source_url'),GUIDE_HOSTS):raise ValueError('invalid name notice evidence')
            _policy_dates(entry,required=['source_reviewed_at'],optional=['reviewed_at','public_page_rechecked_at'])
        _policy_dates(data,required=['reviewed_at'])
        return data
    except (ValueError,KeyError,TypeError,UnicodeError) as exc:
        raise TrustPolicyError('신뢰성 정책이 손상되었거나 지원하지 않는 버전입니다. 자동 코스 생성을 중단합니다.') from exc


def _reference_day(as_of):
    today=as_of if as_of is not None else datetime.now(timezone(timedelta(hours=9))).date()
    if type(today) is not date:raise ValueError('신뢰성 확인 기준일을 확인하세요.')
    return today


def _check_policy_dates(policy,today):
    dates=[policy['reviewed_at']]
    for section,keys in [('automatic_exclusions',['reviewed_at','source_reviewed_at','public_page_rechecked_at']),
                         ('name_notices',['reviewed_at','source_reviewed_at','public_page_rechecked_at'])]:
        dates.extend(entry[key] for entry in policy.get(section,{}).values()
                     for key in keys if entry.get(key) is not None)
    if any(_day(value)>today for value in dates):
        raise TrustPolicyError('확인 기준일보다 미래인 검토일이 있어 자동 코스 생성을 중단합니다.')


def load_policy(root,*,as_of=None):
    today=_reference_day(as_of)
    path=Path(root)/'config/place_trust_policy_v15.json'
    try:
        stat=path.stat()
        if stat.st_size>500_000:raise ValueError('policy too large')
        policy=_policy(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
        # Check each call, outside the file cache: as_of and the KST day can change.
        _check_policy_dates(policy,today)
        return policy
    except (OSError,ValueError) as exc:
        if isinstance(exc,TrustPolicyError):raise
        raise TrustPolicyError('신뢰성 정책을 읽을 수 없어 자동 코스 생성을 중단합니다.') from exc


def _guide(root,ident,policy):
    """Check saved metadata receipts; a receipt is not the original page body."""
    try:
        raw=_file_bytes(root/GUIDE_PATH)
        if hashlib.sha256(raw).hexdigest()!=policy['guide_catalog_sha256']:return None,'guide_catalog_changed'
        data=json.loads(raw.decode('utf-8'))
        guide=next((g for g in data.get('guides',[]) if g.get('id')==ident),None)
        receipt=policy['guide_records'].get(ident)
        if not guide or not isinstance(receipt,dict):return None,'official_guide_missing'
        if _digest(guide)!=receipt.get('guide_record_sha256'):return None,'guide_record_changed'
        if not _url(guide.get('source_url'),GUIDE_HOSTS):return None,'official_guide_source_invalid'
        if not isinstance(guide.get('summary'),str) or not 30<=len(guide['summary'].strip())<=1600:return None,'official_guide_invalid'
        relative=guide.get('source_cache')
        if not isinstance(relative,str):return None,'source_receipt_missing'
        if relative!=receipt['source_cache'] or guide.get('page_sha256')!=receipt['original_page_sha256'] or guide.get('retrieved_at')!=receipt['guide_reviewed_at']:return None,'source_receipt_mismatch'
        path=(root/relative).resolve();allowed=(root/'data_raw/tourism/v12/official_fields').resolve()
        if not path.is_relative_to(allowed) or path==allowed:return None,'source_receipt_path_invalid'
        cache_raw=_file_bytes(path,100_000)
        if hashlib.sha256(cache_raw).hexdigest()!=receipt.get('cache_file_sha256'):return None,'source_receipt_changed'
        cache=json.loads(cache_raw.decode('utf-8'))
        if cache.get('id')!=ident or cache.get('source_url')!=guide.get('source_url') or cache.get('page_sha256')!=guide.get('page_sha256') or cache.get('http_status')!=200:return None,'source_receipt_mismatch'
        return guide,None
    except (OSError,ValueError,TypeError,KeyError,UnicodeError):
        return None,'source_receipt_unavailable'


def place_trust(root,item,purpose='automatic',*,as_of=None):
    if purpose not in {'automatic','manual'}:raise ValueError('신뢰성 검사 목적은 automatic 또는 manual이어야 합니다.')
    if not isinstance(item,dict):raise ValueError('장소 기록 형식을 확인하세요.')
    root=Path(root).resolve();today=_reference_day(as_of);policy=load_policy(root,as_of=today)
    ident=item.get('id');proof=item.get('cross_source');proof=proof if isinstance(proof,dict) else {};reasons=[];warnings=[];sources=[]
    def reject(code,message):reasons.append({'code':code,'message':message})
    from .tourism import _approved
    try:
        identity=(_approved(item) and policy['approved_identity_sha256'].get(ident)==identity_digest(item))
    except (TypeError,ValueError,AttributeError):identity=False
    if not identity:reject('identity_not_verified','허브·지도 교차확인 정책을 통과한 원본 관광 후보와 일치하지 않습니다.')
    lat,lon=item.get('latitude'),item.get('longitude')
    point=all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in [lat,lon])
    point=point and 32.9<=lat<=33.8 and 126<=lon<=127.1
    if not point:reject('coordinate_not_valid','제주 권역의 공개 장소 좌표를 확인하지 못했습니다.')
    checks={'identity':{'status':'cross_source_verified' if identity else 'not_verified','label':'명부·지도 교차확인','match_policy':proof.get('policy_id'),'distance_m':proof.get('distance_m') if identity else None},
            'coordinate':{'status':'source_representative_point' if point else 'not_verified','label':'원자료 대표 좌표이며 실제 입구 확인 아님'},
            'current_operation':{'status':'not_verified','label':'현재 영업·개방 미확인','checked_at':None},
            'entrance':{'status':'not_verified','label':'실제 방문 입구·접근 동선 미확인','checked_at':None},
            'opening_hours':{'status':'not_verified','label':'방문일 운영시간·휴무 미확인'},
            'fees':{'status':'not_verified','label':'입장료·예약·주차비 미확인'}}
    for key,hosts,name in [('hub',{'jejudatahub.net','www.jejudatahub.net'},'제주데이터허브 여행장소 명부'),('osm',{'www.openstreetmap.org','openstreetmap.org'},'OpenStreetMap 원자료')]:
        source=proof.get(key);source=source if isinstance(source,dict) else {};url=_url(source.get('source_url'),hosts)
        if url:sources.append({'kind':'hub_registry' if key=='hub' else 'map_record','name':name,'url':url,'checked_at':source.get('source_date'),'date_kind':'hub_reference' if key=='hub' else 'map_record_edit','snapshot_at':source.get('snapshot_at')})
        elif identity:reject('identity_source_url_invalid','교차확인 원자료의 출처 링크를 확인하지 못했습니다.')
    guide,error=_guide(root,ident,policy)
    if error:reject(error,'공식 관광 소개와 보존된 출처 기록의 무결성을 확인하지 못해 자동 코스에서 제외합니다.')
    reviewed=_day(guide.get('retrieved_at')) if guide else None
    age=(today-reviewed).days if reviewed else None
    if guide and (age is None or age<0):reject('guide_date_invalid','공식 소개 확인일이 없거나 기준일보다 미래입니다.')
    elif guide and age>policy['max_guide_age_days']:reject('guide_review_overdue','공식 소개의 재검토 기한이 지나 자동 코스에서 제외합니다.')
    checks['official_guide']={'status':'official_source_record_verified' if guide else 'not_verified','label':'공식 관광 소개 출처 기록','retrieved_at':guide.get('retrieved_at') if guide else None,'age_days':age,'max_review_age_days':policy['max_guide_age_days'],'source_receipt_scope':'saved_metadata_and_original_page_hash_not_full_original_page'}
    if guide and (age is None or age<0):checks['official_guide']['status']='review_date_invalid'
    elif guide and age>policy['max_guide_age_days']:checks['official_guide']['status']='review_overdue'
    if guide:sources.append({'kind':'tourism_guide','name':guide.get('source_name') or '공식 관광 안내','url':guide['source_url'],'checked_at':guide.get('retrieved_at'),'date_kind':'guide_review'})
    if item.get('requires_ferry'):reject('ferry_not_supported','배편과 섬 안 이동 조건이 확인되지 않아 자동 코스에서 제외합니다.')
    if item.get('requires_access_point'):reject('entrance_required','대표 좌표와 실제 탐방 입구를 구분해야 하는 장소이므로 자동 코스에서 제외합니다.')
    explicit=policy['automatic_exclusions'].get(ident)
    if explicit:
        reject(explicit['code'],explicit['reason'])
        checks['specific_review']={'status':'excluded_pending_recheck','label':explicit['reason'],'reviewed_at':explicit.get('reviewed_at'),'source_reviewed_at':explicit.get('source_reviewed_at'),'public_page_rechecked_at':explicit.get('public_page_rechecked_at'),'source_url':explicit.get('source_url'),'review_kind':explicit.get('review_kind')}
    else:checks['specific_review']={'status':'no_recorded_exception','label':'기록된 별도 자동 제외 사유 없음'}
    notice=policy.get('name_notices',{}).get(ident)
    if notice:warnings.append(notice['message'])
    warnings.extend(['공식 소개와 명부·지도는 장소 확인 근거이며 현재 영업·개방을 확인한 결과가 아닙니다.',
                     '운영시간·휴무·예약·요금과 실제 방문 입구는 방문 전 공식 원문·운영기관에서 확인하세요.'])
    if item.get('category')=='해변' or (item.get('observed_tags') or {}).get('natural')=='beach':warnings.append('해변은 산책·경관 후보입니다. 수영 허용·수상활동·현장 안전은 확인하지 않았습니다.')
    auto=not reasons
    return {'policy_id':POLICY_ID,'policy_reviewed_at':policy['reviewed_at'],'place_id':ident,
            'eligible':auto if purpose=='automatic' else bool(identity and point),
            'automatic_eligible':auto,'purpose':purpose,'status':'supported_with_limits' if auto else 'excluded',
            'reasons':reasons,'checks':checks,'sources':sources,'warnings':warnings,
            'current_operation_verified':False,
            'explanation':'원자료 교차확인·공식 소개·기록된 접근 제한을 검사한 자동 코스 후보 조건입니다. 현장 검증이나 현재 영업 보증이 아닙니다.'}
