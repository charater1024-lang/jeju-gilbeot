"""Learn recent aggregate category compositions from observed Jeju card records.

Serving is a small, serialized multi-output ridge model with month harmonics.
It describes historical group composition, never individual shop ratings.
"""
import calendar
import csv
import datetime as dt
import hashlib
import io
import json
import math
from functools import lru_cache
from pathlib import Path

CATEGORIES=['한식 음식점업','중식 음식점업','일식 음식점업','서양식 음식점업','기타 외국식 음식점업','비알콜 음료점업','피자 햄버거 샌드위치 및 유사 음식점업','빵 및 과자류 소매업']
GROUPS={'resident':'제주도민','tourist':'내국인'}
LEGACY_ALGORITHM='empirical_bayes_seasonal_category_distribution'
ALGORITHM='recency_weighted_multitarget_seasonal_ridge_composition'
SERVING_MODEL='recency_weighted_seasonal_ridge'

def _hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def read_panels(path):
    snapshot=Path(path).read_bytes()
    reader=csv.DictReader(io.StringIO(snapshot.decode('utf-8-sig')))
    if not {'base_year_month','biz_nm','user_type','sex','use_count'}<=set(reader.fieldnames or []):
        raise ValueError('카드 원자료의 필수 열이 없습니다.')
    values={};seen=set();sexes={};raw_rows=0;used_rows=0
    for row in reader:
        raw_rows+=1
        if row['user_type'] not in GROUPS.values() or row['biz_nm'] not in CATEGORIES:continue
        month=row['base_year_month'];dt.datetime.strptime(month,'%Y%m')
        if row['sex'] not in {'남성','여성','알수없음'}:raise ValueError('알 수 없는 성별 분류 또는 총계행입니다.')
        key=(month,row['user_type'],row['biz_nm'],row['sex'])
        if key in seen:raise ValueError('중복 카드 관측입니다.')
        seen.add(key);number=float(row['use_count'])
        if not math.isfinite(number) or number<0 or not number.is_integer():raise ValueError('이용건수는 유한한 0 이상의 정수여야 합니다.')
        used_rows+=1;cell=(month,row['user_type'],row['biz_nm'])
        values[cell]=values.get(cell,0)+number
        sexes.setdefault(cell,set()).add(row['sex'])
    months=sorted({k[0] for k in values})
    if len(months)<24:raise ValueError('최소 24개월의 관측이 필요합니다.')
    panels=[]
    for month in months:
        for audience,source_group in GROUPS.items():
            if any((month,source_group,c) not in values for c in CATEGORIES):
                raise ValueError('월·집단·업종에 미관측 셀이 있습니다. 결측을 0으로 채우지 않습니다.')
            if any(not {'남성','여성'}<=sexes[month,source_group,c] for c in CATEGORIES):
                raise ValueError('필수 성별 분류가 누락되어 집단 간 관측 범위를 맞출 수 없습니다.')
            counts=[values[month,source_group,c] for c in CATEGORIES];total=sum(counts)
            if total<=0:raise ValueError('월별 이용건수 합이 0입니다.')
            panels.append({'month':month[:4]+'-'+month[4:],'calendar_month':int(month[4:]),'audience':audience,'shares':[v/total for v in counts]})
    return panels,{'source_sha256':hashlib.sha256(snapshot).hexdigest(),'raw_rows':raw_rows,'used_source_rows':used_rows,'aggregate_cells':len(values),'months':len(months),'missing_cells_imputed':0}

def _fit(panels):
    result={}
    for audience in GROUPS:
        rows=[r for r in panels if r['audience']==audience]
        if not rows:raise ValueError('학습 집단이 없습니다.')
        global_share=[sum(r['shares'][i] for r in rows)/len(rows) for i in range(len(CATEGORIES))]
        seasonal={}
        for month in range(1,13):
            subset=[r for r in rows if r['calendar_month']==month]
            seasonal[str(month)]={'n':len(subset),'sum':[sum(r['shares'][i] for r in subset) for i in range(len(CATEGORIES))]}
        result[audience]={'global':global_share,'seasonal':seasonal}
    return result

def _predict(profiles,audience,month,shrinkage,static=False):
    p=profiles[audience]
    if static:return p['global'][:]
    cell=p['seasonal'][str(month)];denominator=cell['n']+shrinkage
    if not denominator:return p['global'][:]
    return [(v+shrinkage*g)/denominator for v,g in zip(cell['sum'],p['global'])]

def _score(profiles,panels,shrinkage,static=False):
    errors=[];cross_entropy=[]
    for row in panels:
        predictions=_predict(profiles,row['audience'],row['calendar_month'],shrinkage,static)
        errors.extend(abs(a-p) for a,p in zip(row['shares'],predictions))
        cross_entropy.append(-sum(a*math.log(max(p,1e-12)) for a,p in zip(row['shares'],predictions)))
    return {'mae_share':round(sum(errors)/len(errors),8),'cross_entropy':round(sum(cross_entropy)/len(cross_entropy),8),'panels':len(panels)}

def _month_index(month):
    year,number=map(int,month.split('-'))
    return year*12+number

def _features(month,harmonics):
    angle=2*math.pi*month/12
    return [1.0]+[value for k in range(1,harmonics+1) for value in (math.sin(k*angle),math.cos(k*angle))]

def _solve(matrix,target):
    size=len(target);augmented=[list(row)+[value] for row,value in zip(matrix,target)]
    for column in range(size):
        pivot=max(range(column,size),key=lambda row:abs(augmented[row][column]))
        if abs(augmented[pivot][column])<1e-14:raise ValueError('소비 모델의 학습 행렬이 특이합니다.')
        augmented[column],augmented[pivot]=augmented[pivot],augmented[column]
        divisor=augmented[column][column]
        for j in range(column,size+1):augmented[column][j]/=divisor
        for row in range(column+1,size):
            factor=augmented[row][column]
            for j in range(column,size+1):augmented[row][j]-=factor*augmented[column][j]
    result=[0.0]*size
    for row in range(size-1,-1,-1):result[row]=augmented[row][size]-sum(augmented[row][j]*result[j] for j in range(row+1,size))
    return result

def _fit_ridge(panels,config):
    end=max(_month_index(row['month']) for row in panels);coefficients={}
    size=1+2*config['harmonics']
    for audience in GROUPS:
        rows=[row for row in panels if row['audience']==audience and (not config['window'] or _month_index(row['month'])>end-config['window'])]
        if not rows:raise ValueError('소비 모델을 학습할 집단별 관측이 없습니다.')
        gram=[[0.0]*size for _ in range(size)];targets=[[0.0]*size for _ in CATEGORIES]
        for row in rows:
            x=_features(row['calendar_month'],config['harmonics'])
            weight=2**(-(end-_month_index(row['month']))/config['half_life']) if config['half_life'] else 1.0
            for j in range(size):
                for k in range(size):gram[j][k]+=weight*x[j]*x[k]
                for category in range(len(CATEGORIES)):targets[category][j]+=weight*x[j]*row['shares'][category]
        for j in range(size):gram[j][j]+=config['alpha'] if j else 1e-10
        coefficients[audience]=[_solve(gram,target) for target in targets]
    return coefficients

def _predict_ridge(coefficients,audience,month,config):
    x=_features(month,config['harmonics'])
    raw=[max(1e-10,sum(value*coefficient for value,coefficient in zip(x,weights))) for weights in coefficients[audience]]
    total=sum(raw)
    return [value/total for value in raw]

def _measure(panels,predict):
    errors=[];cross_entropy=[];by_audience={group:[] for group in GROUPS};by_category={category:[] for category in CATEGORIES}
    for row in panels:
        predictions=predict(row)
        row_errors=[abs(actual-predicted) for actual,predicted in zip(row['shares'],predictions)]
        errors.extend(row_errors);by_audience[row['audience']].extend(row_errors)
        for category,error in zip(CATEGORIES,row_errors):by_category[category].append(error)
        cross_entropy.append(-sum(actual*math.log(max(predicted,1e-12)) for actual,predicted in zip(row['shares'],predictions)))
    ordered=sorted(errors)
    return {'mae_share':round(sum(errors)/len(errors),8),'mae_percentage_points':round(100*sum(errors)/len(errors),6),
            'rmse_share':round(math.sqrt(sum(value*value for value in errors)/len(errors)),8),
            'cross_entropy':round(sum(cross_entropy)/len(cross_entropy),8),'panels':len(panels),'category_observations':len(errors),
            'p90_absolute_error_percentage_points':round(100*ordered[min(len(ordered)-1,math.ceil(len(ordered)*.9)-1)],6),
            'max_absolute_error_percentage_points':round(100*ordered[-1],6),
            'by_audience':{group:{'mae_share':round(sum(values)/len(values),8),'mae_percentage_points':round(100*sum(values)/len(values),6),'category_observations':len(values)} for group,values in by_audience.items() if values},
            'by_category':{category:{'mae_share':round(sum(values)/len(values),8),'mae_percentage_points':round(100*sum(values)/len(values),6)} for category,values in by_category.items() if values}}

def _candidate_configs():
    # Fixed search space, chosen on validation only. No test-dependent branches.
    for window in [0,12,18,24,36,48]:
        for half_life in [0,6,12,24,36]:
            for harmonics in [0,1,2,3]:
                for alpha in [.1,1,10,100]:
                    yield {'window':window,'half_life':half_life,'harmonics':harmonics,'alpha':alpha}

def train_audience(csv_path,output_dir):
    panels,source=read_panels(csv_path);months=sorted({r['month'] for r in panels})
    first=int(len(months)*.6);second=int(len(months)*.8)
    train=[r for r in panels if r['month']<=months[first-1]]
    validation=[r for r in panels if months[first]<=r['month']<=months[second-1]]
    test=[r for r in panels if r['month']>=months[second]]
    profiles=_fit(train)
    candidates=[{'shrinkage':k,**_score(profiles,validation,k)} for k in [0,1,3,6,12]]
    chosen=min(candidates,key=lambda c:(c['mae_share'],c['shrinkage']))['shrinkage']
    ridge_candidates=[]
    for config in _candidate_configs():
        coefficients=_fit_ridge(train,config)
        score=_measure(validation,lambda row:_predict_ridge(coefficients,row['audience'],row['calendar_month'],config))
        ridge_candidates.append({'config':config,'mae_share':score['mae_share'],'cross_entropy':score['cross_entropy']})
    # Preserve full-precision ordering used by the frozen experiment.
    def precise_validation(candidate):
        config=candidate['config'];coefficients=_fit_ridge(train,config)
        errors=[abs(a-p) for row in validation for a,p in zip(row['shares'],_predict_ridge(coefficients,row['audience'],row['calendar_month'],config))]
        return (sum(errors)/len(errors),config['harmonics'],config['window'],config['half_life'],config['alpha'])
    best=min(ridge_candidates,key=precise_validation);config=best['config']
    coefficients=_fit_ridge(train,config)
    baseline_val=_measure(validation,lambda row:_predict(profiles,row['audience'],row['calendar_month'],chosen,True))
    model_val=_measure(validation,lambda row:_predict_ridge(coefficients,row['audience'],row['calendar_month'],config))
    legacy_val=_measure(validation,lambda row:_predict(profiles,row['audience'],row['calendar_month'],chosen))
    selected=SERVING_MODEL if model_val['mae_share']<baseline_val['mae_share'] else 'audience_mean'
    # Evaluation configuration is fixed above. No test value enters selection.
    test_profiles=_fit(train+validation)
    test_coefficients=_fit_ridge(train+validation,config)
    recent_config=dict(config,harmonics=0);recent_coefficients=_fit_ridge(train+validation,recent_config)
    test_model=_measure(test,lambda row:_predict_ridge(test_coefficients,row['audience'],row['calendar_month'],config))
    test_baseline=_measure(test,lambda row:_predict(test_profiles,row['audience'],row['calendar_month'],chosen,True))
    metrics={'schema_version':2,'source_id':'1048','source_url':'https://www.jejudatahub.net/data/view/data/1048','algorithm':ALGORITHM,'source':source,
       'observation_period':{'start':months[0],'end':months[-1]},
       'split':{'train_start':months[0],'train_end':months[first-1],'validation_start':months[first],'validation_end':months[second-1],'test_start':months[second],'test_end':months[-1],
                'validation_fit_scope':'training_partition_only','test_fit_scope':'training_plus_validation_for_all_comparators','serving_fit_scope':'all_observed_months_after_evaluation',
                'test_status':'retrospective_existing_v13_test_period_not_pristine_external_holdout','test_used_for_selection':False},
       'validation':{'model':model_val,'baseline':baseline_val,'legacy_seasonal':legacy_val,'candidates':ridge_candidates,'legacy_candidates':candidates},
       'test':{'model':test_model,'baseline':test_baseline,
               'legacy_seasonal':_measure(test,lambda row:_predict(test_profiles,row['audience'],row['calendar_month'],chosen)),
               'recent_weighted_mean_ablation':_measure(test,lambda row:_predict_ridge(recent_coefficients,row['audience'],row['calendar_month'],recent_config))},
       'selection':{'selected':selected,'config':config,'shrinkage':chosen,'criterion':'validation_mae_share_only','candidate_count':len(ridge_candidates),'test_used_for_selection':False},
       'improvement_vs_same_fit_baseline':{'validation_mae_reduction_percent':round(100*(1-model_val['mae_share']/baseline_val['mae_share']),4) if baseline_val['mae_share'] else None,
                                           'test_mae_reduction_percent':round(100*(1-test_model['mae_share']/test_baseline['mae_share']),4) if test_baseline['mae_share'] else None},
       'definition':'각 성별 분류의 관측 이용건수를 합하고 월별 8업종 안에서 정규화한 집단 소비 구성비. 고유 이용자수 합계가 아님.',
       'metric_definitions':{'mae_share':'8개 업종 구성비별 절대오차의 평균. 0.01 = 1퍼센트포인트이며 분류 정확도가 아님.','cross_entropy':'관측 구성비와 추정 구성비의 자연로그 교차엔트로피. 낮을수록 좋음.','p90_absolute_error_percentage_points':'평가 집단·월·업종 셀 절대오차의 경험적 90백분위. 예측구간/신뢰구간이 아님.'},
       'limitations':['관측은 제주 전체 집계이며 점포별 방문량·평점이나 개인 취향의 정답이 아닙니다.','내국인 구간을 관광객 모드의 참고 집단으로 사용하며 모든 관광객 선호로 일반화하지 않습니다.','실제 원거래의 중복 여부까지 독립 검증한 자료는 아닙니다.','최근 관측창과 감쇠 가중치를 이용한 월별 과거 구성비 모형이며 현재 소비나 장기 추세를 실시간 예측하지 않습니다.','480개 구성을 같은 검증기간에서 비교했습니다. 테스트는 구성 선택에 사용하지 않았으나 기존 공개 평가기간을 재사용한 후향 평가로 새로운 외부 검증이 필요합니다.','모델 개선의 대부분은 최근 자료 반영에서 나올 수 있습니다. 계절 성분의 추가 효과는 recent_weighted_mean_ablation과 구분해 확인합니다.']}
    model={'schema_version':2,'algorithm':ALGORITHM,'source_id':'1048','source_sha256':source['source_sha256'],'categories':CATEGORIES,
           'groups':GROUPS,'profiles':_fit(panels),'shrinkage':chosen,'selected_serving_model':selected,'config':config,'coefficients':_fit_ridge(panels,config),'observation_period':metrics['observation_period'],'metrics':metrics}
    model['model_sha256']=_hash(model)
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'audience_model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'audience_metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    return metrics

@lru_cache(maxsize=8)
def _load(path,mtime):
    m=json.loads(Path(path).read_text(encoding='utf-8'));fingerprint=m.pop('model_sha256',None)
    if fingerprint!=_hash(m) or (m.get('schema_version'),m.get('algorithm')) not in {(1,LEGACY_ALGORITHM),(2,ALGORITHM)} or m.get('categories')!=CATEGORIES or m.get('groups')!=GROUPS:
        raise ValueError('소비 모델의 구조 또는 해시가 유효하지 않습니다.')
    if m.get('selected_serving_model') not in {'seasonal','audience_mean',SERVING_MODEL}:raise ValueError('소비 모델 선택 정보가 유효하지 않습니다.')
    if not isinstance(m.get('shrinkage'),(int,float)) or isinstance(m['shrinkage'],bool) or not math.isfinite(m['shrinkage']) or m['shrinkage']<0:raise ValueError('소비 모델의 평활화 값이 유효하지 않습니다.')
    for audience in GROUPS:
        p=m['profiles'][audience]
        if set(p['seasonal'])!={str(i) for i in range(1,13)}:raise ValueError('소비 모델의 월별 정의가 누락됐습니다.')
        if len(p['global'])!=len(CATEGORIES) or any(not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in p['global']) or abs(sum(p['global'])-1)>1e-6:
            raise ValueError('소비 모델의 확률 구성비가 유효하지 않습니다.')
        for cell in p['seasonal'].values():
            if not isinstance(cell['n'],int) or isinstance(cell['n'],bool) or cell['n']<0 or len(cell['sum'])!=len(CATEGORIES) or any(not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in cell['sum']):raise ValueError('계절별 소비 모델이 유효하지 않습니다.')
    if m.get('schema_version')==2:
        config=m.get('config',{})
        if set(config)!={'window','half_life','harmonics','alpha'} or any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) for value in config.values()):raise ValueError('소비 회귀 모델의 설정이 유효하지 않습니다.')
        if not isinstance(config['harmonics'],int) or not 0<=config['harmonics']<=3 or not isinstance(config['window'],int) or config['window']<0 or config['half_life']<0 or config['alpha']<=0:raise ValueError('소비 회귀 모델의 설정 범위가 유효하지 않습니다.')
        coefficients=m.get('coefficients',{})
        if set(coefficients)!=set(GROUPS):raise ValueError('소비 회귀 모델 집단이 누락됐습니다.')
        for group in GROUPS:
            rows=coefficients[group]
            if not isinstance(rows,list) or len(rows)!=len(CATEGORIES):raise ValueError('소비 회귀 모델 업종이 누락됐습니다.')
            for row in rows:
                if not isinstance(row,list) or len(row)!=1+2*config['harmonics'] or any(not isinstance(value,(float,int)) or isinstance(value,bool) or not math.isfinite(value) for value in row):raise ValueError('소비 회귀 계수가 유효하지 않습니다.')
    elif m.get('selected_serving_model')==SERVING_MODEL:raise ValueError('소비 회귀 모델 스키마가 유효하지 않습니다.')
    return m

def predict_audience(model_path,audience='resident',month=1):
    if audience not in GROUPS:raise ValueError('이용 모드는 resident 또는 tourist여야 합니다.')
    if isinstance(month,bool):raise ValueError('월은 1~12 정수여야 합니다.')
    try:number=int(month)
    except (ValueError,TypeError):raise ValueError('월은 1~12 정수여야 합니다.')
    if str(number)!=str(month) or not 1<=number<=12:raise ValueError('월은 1~12 정수여야 합니다.')
    path=Path(model_path);m=_load(str(path.resolve()),path.stat().st_mtime_ns)
    shares=_predict_ridge(m['coefficients'],audience,number,m['config']) if m['selected_serving_model']==SERVING_MODEL else _predict(m['profiles'],audience,number,m['shrinkage'],m['selected_serving_model']=='audience_mean')
    ranked=sorted(zip(CATEGORIES,shares),key=lambda pair:(-pair[1],pair[0]))
    today=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date();year,mo=map(int,m['observation_period']['end'].split('-'))
    age=(today-dt.date(year,mo,calendar.monthrange(year,mo)[1])).days
    return {'status':'historical_pattern','audience':audience,'audience_label':'도민 모드' if audience=='resident' else '관광객 모드',
       'data_group_label':'원자료 '+GROUPS[audience]+' 구간','month':number,'source_id':'1048','source_url':'https://www.jejudatahub.net/data/view/data/1048',
       'observation_period':m['observation_period'],'data_age_days':age,'is_stale':age>90,
       'categories':[{'id':CATEGORIES.index(name),'name':name,'share':round(share,6),'rank':i+1} for i,(name,share) in enumerate(ranked)],
       'model':{'algorithm':m['algorithm'],'selected_serving_model':m['selected_serving_model'],'version':m['schema_version'],'config':m.get('config'),'source_sha256':m['source_sha256'],
                'monthly_periodicity':m['selected_serving_model']=='seasonal' or (m['selected_serving_model']==SERVING_MODEL and m['config']['harmonics']>0)},'metrics':m['metrics']['test'],
       'warnings':['과거 집단의 업종별 소비 구성을 학습한 참고값이며 현재 맛집 인기도나 개인의 취향을 예측한 값은 아닙니다.',
                   '관광객 모드는 원자료 내국인 구간을 참고하며 전체 관광객을 대표한다고 보장하지 않습니다.',
                   f"자료의 마지막 관측월은 {m['observation_period']['end']}입니다. 지역별·개별 점포별 수요는 제공하지 않습니다."]}
