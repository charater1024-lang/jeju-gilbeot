"""Portable prediction for frozen CPU bus-regression experiment artifacts.

No numpy, sklearn, LLM or GPU is required by this serving module. Candidate
selection and release decisions belong to the frozen experiment protocol.
"""
import datetime as dt
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path


def _day(value):
    if not isinstance(value,str):raise ValueError('날짜는 YYYY-MM-DD 문자열이어야 합니다.')
    try:result=dt.date.fromisoformat(value)
    except ValueError as exc:raise ValueError('올바른 날짜를 입력해 주세요.') from exc
    if not 1900<=result.year<=2200:raise ValueError('날짜 범위를 확인해 주세요.')
    return result

def _phase(day):return 2*math.pi*(day.timetuple().tm_yday-1)/365.25
def _design(day,basis):
    result=[float(day.weekday()==i) for i in range(7)]
    if basis=='month_dummies':result += [float(day.month==i) for i in range(1,13)]
    else:
        p=_phase(day);h=1 if basis=='fourier1' else 2
        result += [v for k in range(1,h+1) for v in (math.sin(k*p),math.cos(k*p))]
        result += [v*float(day.weekday()>=5) for v in result[7:]]
    return result

def _tree_design(model,day,group):
    p=_phase(day);scale=model['scales'][group]
    return [model['group_index'][group],day.weekday(),day.month,day.day,day.timetuple().tm_yday,day.isocalendar().week,
            math.sin(p),math.cos(p),math.sin(2*p),math.cos(2*p),math.log1p(scale)]

def predict_artifact(model,date,group):
    """Predict one known source group using exported, finite learned parameters."""
    selected_day=_day(date) if isinstance(date,str) else date
    if not isinstance(selected_day,dt.date):raise ValueError('올바른 날짜가 필요합니다.')
    if group not in model.get('scales',{}):raise ValueError('학습 범위에 없는 원자료 통계 코드 또는 시간구간입니다.')
    cfg=model['config'];family=cfg['family']
    if family=='ensemble':
        return max(0.,sum(w*predict_artifact(m,selected_day,group) for m,w in zip(model['members'],cfg['weights'])))
    if family in {'hist_gradient_boosting','extra_trees','random_forest'}:
        x=_tree_design(model,selected_day,group)
        if family=='hist_gradient_boosting':
            original=x;encoded=[]
            for index in model['feature_order']:
                categories=model.get('categorical_encoding',{}).get(str(index))
                raw=original[index]
                encoded.append(float(categories.index(raw)) if categories is not None and raw in categories else float('nan') if categories is not None else raw)
            x=encoded
            total=model['baseline_prediction']
            for tree in model['trees']:
                index=0
                while True:
                    node=tree['nodes'][index]
                    if node['is_leaf']:
                        total+=node['value'];break
                    value=x[node['feature_idx']]
                    if math.isnan(value):left=bool(node['missing_go_to_left'])
                    elif node['is_categorical']:
                        category=int(value);bits=tree['raw_left_cat_bitsets'][node['bitset_idx']]
                        left=category>=0 and category//32<len(bits) and bool((bits[category//32]>>(category%32))&1)
                    else:left=value<=node['num_threshold']
                    index=node['left'] if left else node['right']
            if cfg['loss']=='poisson':total=math.exp(max(-20.,min(20.,total)))
            return max(0.,total*model['scales'][group])
        values=[]
        for tree in model['trees']:
            index=0
            while tree['left'][index]!=-1:
                index=tree['left'][index] if x[tree['feature'][index]]<=tree['threshold'][index] else tree['right'][index]
            values.append(tree['value'][index])
        return max(0.,sum(values)/len(values)*model['scales'][group])
    learned=model['groups'][group]
    if family in {'weekday_summary','hierarchical_weekday'}:return max(0.,learned['centers'][selected_day.weekday()])
    if family=='calendar_regression':
        value=sum(a*b for a,b in zip(_design(selected_day,cfg['basis']),learned['coefs']))
        value=math.expm1(max(-20.,min(20.,value))) if cfg['transform']=='log' else max(0.,value)**2 if cfg['transform']=='sqrt' else value
        return max(0.,value*learned['scale'])
    if family=='periodic_kernel':
        numerator=denominator=0.;p=_phase(selected_day)
        for row,base in zip(learned['history'],learned['weights']):
            if row['weekday']!=selected_day.weekday():continue
            distance=abs(row['phase']-p);distance=min(distance,2*math.pi-distance)*365.25/(2*math.pi)
            w=base*math.exp(-.5*(distance/cfg['width_days'])**2);numerator+=w*row['y'];denominator+=w
        baseline=learned['centers'][selected_day.weekday()]
        value=numerator/denominator if denominator else baseline
        return max(0.,cfg['blend_weekday']*baseline+(1-cfg['blend_weekday'])*value)
    raise ValueError('지원하지 않는 버스 후보 모델 형식입니다.')

def _sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def _finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def validate_artifact(model):
    if not isinstance(model,dict) or model.get('schema_version')!=1 or model.get('source_id') not in {'512','561'}:raise ValueError('버스 후보 모델 버전·출처가 올바르지 않습니다.')
    if not isinstance(model.get('scales'),dict) or not model['scales'] or any(not isinstance(g,str) or not _finite(v) or v<1 for g,v in model['scales'].items()):raise ValueError('버스 모델의 그룹 척도를 확인해 주세요.')
    _day(model['fit_period']['start']);_day(model['fit_period']['end'])
    family=model.get('config',{}).get('family')
    if family not in {'weekday_summary','hierarchical_weekday','calendar_regression','periodic_kernel','hist_gradient_boosting','extra_trees','random_forest','ensemble'}:raise ValueError('버스 모델 종류가 올바르지 않습니다.')
    if family=='ensemble':
        members=model.get('members',[]);weights=model['config'].get('weights',[])
        if len(members)!=len(weights) or not members or any(not _finite(w) or w<0 for w in weights) or abs(sum(weights)-1)>1e-8:raise ValueError('앙상블 가중치가 올바르지 않습니다.')
    elif family in {'weekday_summary','hierarchical_weekday'}:
        if set(model.get('groups',{}))!=set(model['scales']) or any(len(v.get('centers',[]))!=7 or any(not _finite(x) or x<0 for x in v['centers']) for v in model['groups'].values()):raise ValueError('요일별 계수를 확인해 주세요.')
    elif family=='calendar_regression':
        expected=len(_design(dt.date(2025,1,1),model['config']['basis']))
        if any(len(v.get('coefs',[]))!=expected or any(not _finite(x) for x in v['coefs']) for v in model['groups'].values()):raise ValueError('회귀 계수를 확인해 주세요.')
    elif family in {'hist_gradient_boosting','extra_trees','random_forest'}:
        if not isinstance(model.get('trees'),list) or not model['trees'] or not isinstance(model.get('group_index'),dict):raise ValueError('트리 모델을 확인해 주세요.')
    return True

@lru_cache(maxsize=4)
def _load(folder,signature):
    base=Path(folder);receipt=json.loads((base/'artifact_integrity.json').read_text('utf-8'))
    for name in ('candidate_model.json','experiment_report.json','selection_freeze.json','protocol.json'):
        if receipt['sha256'].get(name)!=_sha(base/name):raise ValueError('버스 후보 모델·평가 명세의 해시가 일치하지 않습니다.')
    model=json.loads((base/'candidate_model.json').read_text('utf-8'));report=json.loads((base/'experiment_report.json').read_text('utf-8'))
    validate_artifact(model)
    if model['selection_freeze_sha256']!=_sha(base/'selection_freeze.json') or model['source_sha256']!=report['raw_audit']['source_sha256']:raise ValueError('모델 선정·출처 연결이 일치하지 않습니다.')
    return model,report

def get_bus_candidate(root,source_id,date,groups=None):
    """Expose an auditable calendar-only candidate without changing incumbents."""
    if not isinstance(source_id,str) or source_id not in {'512','561'}:raise ValueError('지원하는 버스 자료는 512·561입니다.')
    selected_day=_day(date);folder=Path(root)/'models_candidates_v20/bus'/source_id
    names=('candidate_model.json','experiment_report.json','selection_freeze.json','protocol.json','artifact_integrity.json')
    signature=tuple((folder/name).stat().st_mtime_ns for name in names)
    model,report=_load(str(folder.resolve()),signature)
    if model['source_id']!=source_id or report['source_id']!=source_id or model['config']!=report['selected_config']:raise ValueError('요청한 자료와 모델 선정이 일치하지 않습니다.')
    available=sorted(model['scales'])
    selected=available if groups is None else groups
    if not isinstance(selected,(list,tuple)) or not selected or len(selected)>1000 or any(not isinstance(g,str) or g not in model['scales'] for g in selected):raise ValueError('원자료 그룹 목록을 확인해 주세요.')
    return {'source_id':source_id,'date':selected_day.isoformat(),'estimate_type':'historical_calendar_pattern','runtime_llm':False,
      'config':model['config'],'source_sha256':model['source_sha256'],'fit_period':model['fit_period'],'observation_period':model['observation_period'],
      'predictions':[{'group':g,'prediction':predict_artifact(model,selected_day,g),'history_last_date':model['group_history_last_date'][g]} for g in selected],
      'prediction_unit':'persons_per_hour' if source_id=='512' else 'persons_per_source_code_day',
      'metrics':report['test'],'incumbent_metrics':report['incumbent_test'],'evaluation_population':report['protocol']['split'],
      'test_by_group':report['test_by_group'],'evaluation_group_count':len(report['protocol']['split']['evaluation_groups']),
      'serving_group_count':len(model['scales']),'release_gate':report.get('release_gate'),
      'passes_93_fixed_tolerance':report['passes_93_fixed_tolerance'],'limitations':['과거 관측의 달력 패턴 참고값입니다. 현재 혼잡·좌석·시간표와 구분합니다.','기존에 보고한 과거 테스트를 사용한 후향평가이며 새로운 현장 정확도가 아닙니다.']}
