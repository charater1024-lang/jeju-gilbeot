"""Offline coordination of source-grounded local analysis tools."""
import datetime as dt
from pathlib import Path
import time
from .audience_model import predict_audience
from .catalog_store import affinity_food
from .mobility_model import predict_mobility
from .reference import read_json

def food_insight(root,audience='resident',month=None,region='all'):
    root=Path(root);started=time.perf_counter()
    if month is None:month=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).month
    result=predict_audience(root/'models_audience'/'audience_model.json',audience,month)
    trace=[{'agent':'집계 분석','status':'completed','detail':'원자료 집단과 8업종 안의 관측 이용건수 분포 모델을 조회했습니다.','duration_ms':round((time.perf_counter()-started)*1000,3)}]
    before=time.perf_counter()
    result['restaurants']=affinity_food(root,result['categories'],region)
    result['region']=region;result['scope']='제주 전체 선택 8개 식음료 업종 안의 구성비'
    result['restaurant_note']='업종 경향을 참고한 이름순 예시이며 식당별 인기도·맛 평점 순위가 아닙니다.'
    trace.append({'agent':'음식점 후보','status':'completed','detail':'지역과 자료상 업종을 연결하고 다른 업종의 예시가 함께 나오도록 구성했습니다.','duration_ms':round((time.perf_counter()-before)*1000,3)})
    result['trace']=trace;result['execution_model']='local_tool_pipeline';return result

def mobility_insight(root,date,period='daytime'):
    return predict_mobility(Path(root)/'models_mobility'/'mobility_model.json',date,period)

def insight_status(root):
    root=Path(root)
    food=read_json(root/'models_audience'/'audience_metrics.json',{})
    bus=read_json(root/'models_mobility'/'mobility_metrics.json',{})
    catalogue=read_json(root/'data_reference'/'catalog_profile.json',{})
    return {'runtime':'offline_cpu','requires_gpu':False,'requires_external_api':False,
       'target_hardware':{'cpu':'Intel Core i7-8700','gpu':'GTX 1060 optional, unused','ram_gb':32},
       'food':{'available':bool(food),'observation_period':food.get('observation_period'),'selection':food.get('selection'),'metrics':food.get('test')},
       'mobility':{'available':bool(bus),'observation_period':bus.get('observation_period'),'selection':bus.get('serving_selection'),'metrics':bus.get('test')},
       'catalogue':catalogue,'kiosk':{'favorite_storage':'sessionStorage','manual_reset':True,'account_required':False},
       'note':'집단별 소비와 시간대 승차의 과거 패턴을 분석합니다. 현재 혼잡·개별 점포 인기·영업을 검증한 서비스는 아닙니다.'}
