"""Read frozen experimental composition candidates without a training runtime.

Candidates that failed the declared promotion gate cannot silently replace a
service model. Diagnostic access must be requested explicitly by the caller.
"""
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

_SOURCES={'1048':'data_raw/hub/hub_1048_5832.csv','1047':'data_raw/hub/hub_1047_5831.csv'}
_COUNTS={'1048':8,'1047':94}
_THRESHOLDS={'1048':1.0,'1047':.25}


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


@lru_cache(maxsize=4)
def _load(path,mtime,size,source_path,source_mtime,source_size):
    model=json.loads(Path(path).read_text('utf-8'))
    if not isinstance(model,dict):raise ValueError('실험 모델 형식을 확인하세요.')
    claimed=model.pop('model_sha256',None)
    if not isinstance(claimed,str) or _digest(model)!=claimed:raise ValueError('실험 모델 해시가 일치하지 않습니다.')
    model['model_sha256']=claimed
    ident=model.get('dataset_id')
    if ident not in _SOURCES or model.get('schema_version')!=1 or model.get('threshold_percentage_points')!=_THRESHOLDS[ident]:
        raise ValueError('실험 모델의 출처 또는 평가 기준이 다릅니다.')
    if hashlib.sha256(Path(source_path).read_bytes()).hexdigest()!=model.get('source_sha256'):
        raise ValueError('실험 모델과 원자료 해시가 일치하지 않습니다.')
    categories=model.get('categories')
    if not isinstance(categories,list) or len(categories)!=_COUNTS[ident] or len(set(categories))!=len(categories) or any(not isinstance(v,str) or not v for v in categories):
        raise ValueError('실험 모델 업종 범위가 다릅니다.')
    profiles=model.get('monthly_profiles')
    expected={'resident','tourist'} if ident=='1048' else {'all'}
    if not isinstance(profiles,dict) or set(profiles)!=expected:raise ValueError('실험 모델 집단 범위가 다릅니다.')
    for group in profiles.values():
        if not isinstance(group,dict) or set(group)!={str(i) for i in range(1,13)}:raise ValueError('실험 모델의 월별 표가 다릅니다.')
        for shares in group.values():
            if not isinstance(shares,list) or len(shares)!=len(categories) or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or v>1 for v in shares) or abs(sum(shares)-1)>1e-8:
                raise ValueError('실험 모델 구성비가 올바르지 않습니다.')
    if model.get('runtime_llm') is not False or model.get('test_status')!='previously_seen_retrospective_fixed_period_not_pristine_external_holdout':
        raise ValueError('실험 모델 평가 범위를 확인하세요.')
    return model


def load_candidate(root,dataset_id):
    ident=str(dataset_id)
    if ident not in _SOURCES:raise ValueError('지원하는 자료는1048·1047입니다.')
    root=Path(root);path=root/f'models_candidates_v20/composition/{ident}_candidate_model.json';source=root/_SOURCES[ident]
    info,raw=path.stat(),source.stat()
    return _load(str(path.resolve()),info.st_mtime_ns,info.st_size,str(source.resolve()),raw.st_mtime_ns,raw.st_size)


def predict_composition(root,dataset_id,month,*,audience=None,allow_unpromoted=False):
    if isinstance(month,bool) or not isinstance(month,int) or month not in range(1,13):raise ValueError('월은1~12정수여야 합니다.')
    if not isinstance(allow_unpromoted,bool):raise ValueError('실험 실행 여부는명시적불리언이어야 합니다.')
    model=load_candidate(root,dataset_id)
    if model['deployment_gate_pass'] is not True and not allow_unpromoted:
        raise ValueError('운영 채택 기준을 통과하지 못한 실험 모델입니다. 기존 운영 모델을 유지하세요.')
    group=audience if model['dataset_id']=='1048' else 'all'
    if group not in model['monthly_profiles']:raise ValueError('소비 집단은resident·tourist중하나여야 합니다.')
    shares=model['monthly_profiles'][group][str(month)]
    return {'status':'experimental_not_promoted' if model['deployment_gate_pass'] is not True else 'historical_pattern',
      'dataset_id':model['dataset_id'],'audience':group,'month':month,'algorithm':model['algorithm'],'selected_family':model['selected_family'],
      'categories':[{'name':name,'share':value} for name,value in zip(model['categories'],shares)],
      'observation_period':model['source_period'],'metrics':model['metrics'],'runtime_llm':False,
      'deployment_gate_pass':model['deployment_gate_pass'],'test_status':model['test_status'],
      'limitations':['검증으로 고정한 실험 모델입니다. 현재 서비스 모델로 채택되지 않은 후보는 진단 목적으로만 실행합니다.',
                     '허용오차 내 비율은 과거 구성비와의 비교이며 분류 정확도·현재 업소 인기도·실사용 만족도가 아닙니다.']}
