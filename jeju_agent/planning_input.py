"""Shared explicit-origin guard for manual and automatic trip drafts."""
import math


MAX_MANUAL_STOPS = 24


def validate_confirmed_origin(body):
    """Reject implicit/default locations and return only confirmed origin fields."""
    if not isinstance(body, dict):
        raise ValueError('요청은 JSON 객체여야 합니다.')
    if body.get('origin_confirmed') is not True:
        raise ValueError('실제 일정의 출발·복귀 기준을 확인한 뒤 추천 코스를 요청하세요.')
    source=body.get('origin_source')
    if not isinstance(source,str) or source not in {'manual','device','landmark'}:
        raise ValueError('출발 위치의 기준은 manual, device, landmark 중 하나여야 합니다.')
    coordinates={}
    for field in ['start_lat','start_lon','end_lat','end_lon']:
        value=body.get(field)
        if (isinstance(value,bool) or not isinstance(value,(int,float))
                or isinstance(value,float) and not math.isfinite(value)):
            raise ValueError('출발·복귀 좌표를 직접 확인해 주세요. 기본 좌표를 임의 적용하지 않습니다.')
        coordinates[field]=value
    for lat,lon in [(coordinates['start_lat'],coordinates['start_lon']),
                    (coordinates['end_lat'],coordinates['end_lon'])]:
        if not 32.9<=lat<=33.8 or not 126.0<=lon<=127.05:
            raise ValueError('출발·복귀 위치는 제주 권역이어야 합니다.')
    label=body.get('origin_label','')
    if not isinstance(label,str) or len(label)>100:
        raise ValueError('출발 기준 이름은 100자 이내 문자열이어야 합니다.')
    return dict(coordinates,origin_confirmed=True,origin_source=source,origin_label=label.strip())
