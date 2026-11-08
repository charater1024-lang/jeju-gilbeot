"""Past flower schedules + independently verified observations + climate ML.

Only temperature is learned. Month comparison is an explicit user-condition
rule; no schedule is a bloom label or a current event/route recommendation.
"""
from datetime import date,timedelta
from functools import lru_cache
import os
from .climate_guide import _verified,_json,climate_status,climate_reference,ClimateDataError

DATA_PATH='data_reference/flower_seasons.json'
DATA_SHA256='98c5e0dcd195a694f0f6ec925a0efb0649ff7d662a2390a8bcca044b52fd4672'
PREFERENCES=[{'id':'cool','name':'시원하게','min_c':15,'max_c':20},
             {'id':'mild','name':'온화하게','min_c':18,'max_c':24},
             {'id':'warm','name':'따뜻하게','min_c':22,'max_c':27}]
LIMITATIONS=[
    '꽃 정보는 과거 공개 행사 일정입니다. 실제 개최·개화·만발·현재 영업을 확인한 기록이 아닙니다.',
    '일정이 기록된 월과 사용자가 고른 일평균기온 조건을 규칙으로 비교합니다. 꽃 개화나 개인 만족도를 학습한 순위가 아닙니다.',
    '기온은 2000~2016년 관측을 학습한 HGB의 매월 15일 과거 계절 대표값입니다. 올해·다음 여행일의 날씨 예보가 아닙니다.',
    '기온 모델의 전체 시험 MAE는 1.92℃, 기준 통계는 1.90℃입니다. 2021년 범위 포함률은 68.8%여서 최근 기후로 보정한 결과로 사용할 수 없습니다.',
    '일정 기록은 일부 연도·행사만 포함하고 유사 중복도 남아 있습니다. 기록 건수를 인기·고유 행사 수·관람 성공률로 해석하지 않습니다.',
    '수국 등은 품종·재배 환경별 개화 기간을 구분하지 못합니다. 기준목 관측은 해당 관측지점의 관측이며 관광지 전체 만개일이 아닙니다.',
    '새 행사·명소·좌표를 자동 코스에 넣지 않습니다. 출발·위치 동의·관광지 검증은 기존 절차를 따릅니다.',
]

class FlowerDataError(RuntimeError):pass

@lru_cache(maxsize=2)
def _parsed(content):
    data=_json(content)
    if data.get('schema_version')!=1 or len(data.get('events',[]))!=28 or len(data.get('observations',[]))!=12:
        raise ValueError('flower source dimensions')
    for event in data['events']:
        start,end=date.fromisoformat(event['start_date']),date.fromisoformat(event['end_date'])
        if not 0<=(end-start).days<=365 or event['reference_only'] is not True or event['bloom_observation'] is not False:
            raise ValueError('flower schedule period/scope')
    for observation in data['observations']:
        date.fromisoformat(observation['observed_date'])
        if observation['phase'] not in {'개화','만발'} or observation.get('future_prediction') is not False:
            raise ValueError('observation phase/scope')
    return data

def _assets(root):
    try:
        content=_verified(root,DATA_PATH,DATA_SHA256,200_000);data=_parsed(content)
        for spec in data['source_files']:_verified(root,spec['path'],spec['sha256'])
        return data
    except (ClimateDataError,OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        raise FlowerDataError('꽃 원본·정제 자료의 출처를 확인할 수 없습니다.') from exc

def _public(root,data,climate):
    from .flower_weather import weather_places
    return {'schema_version':1,'available':True,'flowers':data['flowers'],'stations':climate['stations'],
            'preferences':PREFERENCES,'default_request':{'flower':'hydrangea','station':'seogwipo','preference':'mild'},
            'event_period':data['event_period'],'sources':data['sources'],
            'weather':{'available':os.environ.get('JEJU_FLOWER_WEATHER_API','1').strip()!='0','provider':'Open-Meteo','places':weather_places(root)},
            'flower_prediction':{'available':False,'status':'excluded','reason':'excluded_by_user','api_key_required':False,'user_message':'꽃 개화일 예측은 제공하지 않습니다. 공개 일정과 과거 기온을 참고해 주세요.'},
            'temperature_model':climate['model'],'temperature_source':climate['source'],
            'current_event_verified':False,'flower_ml_trained':False,'llm_used':False,'limitations':list(LIMITATIONS)}

def flower_status(root):
    data=_assets(root)
    try:return _public(root,data,climate_status(root))
    except ClimateDataError as exc:raise FlowerDataError('검증한 기온 모델을 확인할 수 없습니다.') from exc

@lru_cache(maxsize=64)
def _months(start,end):
    current,finish=date.fromisoformat(start),date.fromisoformat(end);months=set()
    while current<=finish:months.add(current.month);current+=timedelta(days=1)
    return frozenset(months)

def flower_seasons(root,flower='hydrangea',station='seogwipo',preference='mild'):
    data=_assets(root)
    if flower not in [row['id'] for row in data['flowers']]:raise ValueError('자료가 있는 꽃 종류를 선택해 주세요.')
    pref=next((row for row in PREFERENCES if row['id']==preference),None)
    if pref is None:raise ValueError('선호 일평균기온 조건을 선택해 주세요.')
    try:climate=climate_reference(root,6,15,station)
    except ClimateDataError as exc:raise FlowerDataError('검증한 기온 모델을 확인할 수 없습니다.') from exc
    events=sorted([row for row in data['events'] if flower in row['flowers']],key=lambda r:(r['start_date'],r['id']),reverse=True)
    comparisons=[];middle=(pref['min_c']+pref['max_c'])/2
    for value in climate['seasonality']:
        point=value['point_c'];month=value['month'];count=sum(month in _months(r['start_date'],r['end_date']) for r in events)
        comparisons.append({'month':month,'reference_day':15,'point_c':point,'lower_c':value['lower_c'],'upper_c':value['upper_c'],
            'event_count':count,'has_event_evidence':count>0,'within_preference':pref['min_c']<=point<=pref['max_c'],
            'gap_c':max(pref['min_c']-point,0,point-pref['max_c'])})
    ranked=sorted([row for row in comparisons if row['has_event_evidence']],key=lambda r:(abs(r['point_c']-middle),r['month']))
    observations=sorted([r for r in data['observations'] if r['flower']==flower],key=lambda r:(r['observed_date'],r['station_id']),reverse=True)
    return dict(_public(root,data,climate),requested={'flower':flower,'station':station,'preference':preference},
                month_comparisons=comparisons,suggestions=ranked[:3],events=events,observations=observations,
                observation_message='' if observations else '이 공개 관측 묶음에서는 선택한 꽃의 실제 개화 관측을 확보하지 못했습니다.',
                preference_match_found=any(r['within_preference'] for r in ranked),
                ordering='과거 일정이 기록된 월만 비교 → 대표 일평균기온과 선호 범위 중앙값의 차이 → 같은 차이면 월순',
                temperature_ml_applied=True,flower_prediction_available=False,recommendation_logic='explicit_temperature_condition_rule')
