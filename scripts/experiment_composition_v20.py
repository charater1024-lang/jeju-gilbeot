"""Diverse month-only composition learners with a pre-test rolling protocol.

Training uses isolated NumPy/scikit-learn. Serving exports only learned monthly
probabilities, and therefore needs no training dependencies on the center PC.
"""
from pathlib import Path
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import warnings

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT/'jeju_agent').is_dir():
    raise RuntimeError('Run this script from the project scripts directory.')
TRAIN_LIBS = Path(os.environ.get('JEJU_ML_TRAIN_LIBS',ROOT/'development_support/training_dependencies'))
if TRAIN_LIBS.is_dir():sys.path.insert(0,str(TRAIN_LIBS))
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
import numpy as np
import sklearn
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor, GradientBoostingRegressor
from sklearn.multioutput import MultiOutputRegressor
from sklearn.kernel_ridge import KernelRidge
from sklearn.neural_network import MLPRegressor
from sklearn.linear_model import MultiTaskElasticNet
from jeju_agent import audience_model as audience
from jeju_agent import dining_model as dining

OUT=ROOT/'models_candidates_v20/composition'
SUPPORT=ROOT/'development_support/composition_v20'
DOCS=ROOT/'docs/모델다양화_v20'
for folder in (OUT,SUPPORT,DOCS):folder.mkdir(parents=True,exist_ok=True)


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')


def index(month):
    year,month=map(int,month.split('-'))
    return year*12+month


def normalize(values):
    values=np.maximum(np.asarray(values,dtype=float),1e-12)
    return values/values.sum(axis=-1,keepdims=True)


def transform(values,kind):
    if kind=='clr':
        logs=np.log(np.maximum(values,1e-8))
        return logs-logs.mean(axis=1,keepdims=True)
    return values


def inverse(values,kind):
    if kind=='clr':
        values=np.exp(np.clip(values-values.max(axis=1,keepdims=True),-60,0))
    return normalize(values)


def features(months,basis='fourier',harmonics=2):
    months=np.asarray(months,dtype=float)
    if basis=='dummy':return np.column_stack([np.ones(len(months)),np.eye(12)[months.astype(int)-1]])
    angle=months*2*np.pi/12
    return np.column_stack([np.ones(len(months))]+[f(k*angle) for k in range(1,harmonics+1) for f in (np.sin,np.cos)])


def registry():
    configs=[]
    def add(family,**kw):configs.append(dict(family=family,**kw))
    # The incumbent settings are explicit candidates and an immutable comparator.
    add('ridge',window=12,half_life=6,basis='fourier',harmonics=2,alpha=10,transform='raw',incumbent=True)
    for window in (6,12,24,36,0):
        for half in (3,6,12,0):
            for family in ('weighted_mean','weighted_median'):
                add(family,window=window,half_life=half)
    for bandwidth in (.5,1,2,3):
        for window in (12,24,36):
            for half in (6,12,0):
                add('circular_kernel',window=window,half_life=half,bandwidth=bandwidth,shrinkage=.25)
    for window in (12,24,36,0):
        for half in (6,12,24):
            for shrinkage in (.5,2,6):
                add('month_empirical_bayes',window=window,half_life=half,shrinkage=shrinkage)
    for basis,harmonics in (('fourier',1),('fourier',2),('fourier',3),('dummy',0)):
        for window in (12,24,36,0):
            for half in (6,12,0):
                for alpha in (1,10,100):
                    for kind in ('raw','clr'):
                        add('ridge',window=window,half_life=half,basis=basis,harmonics=harmonics,alpha=alpha,transform=kind)
    for window in (12,24,36):
        for half in (6,12):
            for delta in (.5,1.5):
                add('huber_ridge',window=window,half_life=half,basis='fourier',harmonics=2,alpha=10,transform='raw',delta=delta)
    for window in (12,24,36):
        for half in (6,12):
            for alpha in (1,10):
                add('hierarchical_ridge',window=window,half_life=half,basis='fourier',harmonics=2,alpha=alpha,transform='raw')
    for family in ('random_forest','extra_trees'):
        for window in (12,24,36):
            for half in (6,12):
                for depth,leaf in ((3,2),(None,2)):
                    add(family,window=window,half_life=half,depth=depth,min_leaf=leaf,trees=64,transform='raw')
    for window in (24,36):
        for kind in ('raw','clr'):
            add('gradient_boosting',window=window,half_life=12,depth=2,trees=40,transform=kind)
    for gamma in (.2,1,5):
        for alpha in (.1,1):
            for kind in ('raw','clr'):
                add('rbf_kernel_ridge',window=24,half_life=12,gamma=gamma,alpha=alpha,transform=kind)
    for alpha in (.1,1):
        for width in (8,16):
            add('mlp',window=24,half_life=12,alpha=alpha,width=width,transform='clr')
    for alpha in (.01,.1):
        for ratio in (.2,.8):
            add('multitask_elastic_net',window=24,half_life=12,alpha=alpha,l1_ratio=ratio,transform='clr')
    # Prespecified blends do not use validation/test-fitted stacking weights.
    incumbent=configs[0]
    for blend_family,other in (
        ('ridge_kernel',dict(family='circular_kernel',window=24,half_life=6,bandwidth=1,shrinkage=.25)),
        ('ridge_median',dict(family='weighted_median',window=12,half_life=6)),
        ('ridge_clr',dict(family='ridge',window=24,half_life=12,basis='fourier',harmonics=2,alpha=10,transform='clr')),
        ('ridge_forest',dict(family='extra_trees',window=24,half_life=12,depth=3,min_leaf=2,trees=64,transform='raw'))):
        for ratio in (.25,.5,.75):add('fixed_blend',blend_name=blend_family,ratio=ratio,left=incumbent,right=other)
    # Exact incumbent duplicate removed, other repeated-but-labelled settings retained once.
    unique=[];seen=set()
    for config in configs:
        value=dict(config);value.pop('incumbent',None)
        key=digest(value)
        if key not in seen:unique.append(config);seen.add(key)
    return unique


def weighted_median(values,weights):
    order=np.argsort(values,axis=0)
    sorted_values=np.take_along_axis(values,order,axis=0)
    sorted_weights=weights[order]
    locations=np.argmax(np.cumsum(sorted_weights,axis=0)>=weights.sum()/2,axis=0)
    return sorted_values[locations,np.arange(values.shape[1])]


def ridge_matrix(X,Y,weights,alpha):
    gram=X.T@(X*weights[:,None])
    gram+=np.diag([1e-9]+[alpha]*(X.shape[1]-1))
    return np.linalg.solve(gram,X.T@(Y*weights[:,None]))


def fit_table(rows,config,parent_indices):
    family=config['family']
    if family=='fixed_blend':
        left=fit_table(rows,config['left'],parent_indices)
        right=fit_table(rows,config['right'],parent_indices)
        return normalize(config['ratio']*left+(1-config['ratio'])*right)
    if family=='hierarchical_ridge':
        names=sorted(parent_indices)
        parent_shares=np.array([[sum(row['shares'][i] for i in parent_indices[name]) for name in names] for row in rows])
        parent_rows=[dict(row,shares=shares.tolist()) for row,shares in zip(rows,parent_shares)]
        direct=dict(config,family='ridge')
        parent_table=fit_table(parent_rows,direct,{name:[i] for i,name in enumerate(names)})
        result=np.zeros((12,len(rows[0]['shares'])))
        for j,name in enumerate(names):
            indices=parent_indices[name]
            conditional=[dict(row,shares=(np.array(row['shares'])[indices]/parent_shares[k,j]).tolist()) for k,row in enumerate(rows)]
            learned=fit_table(conditional,direct,{name:list(range(len(indices)))})
            result[:,indices]=parent_table[:,j,None]*learned
        return normalize(result)
    end=max(index(row['month']) for row in rows)
    rows=[row for row in rows if not config.get('window') or index(row['month'])>end-config['window']]
    months=np.array([row['calendar_month'] for row in rows])
    weights=np.array([2**(-(end-index(row['month']))/config['half_life']) if config.get('half_life') else 1. for row in rows])
    weights=weights*len(rows)/weights.sum()
    Y=np.array([row['shares'] for row in rows])
    mean=np.average(Y,axis=0,weights=weights)
    if family=='weighted_mean':return normalize(np.tile(mean,(12,1)))
    if family=='weighted_median':return normalize(np.tile(weighted_median(Y,weights),(12,1)))
    if family in ('circular_kernel','month_empirical_bayes'):
        result=[]
        for month in range(1,13):
            distance=np.minimum(abs(months-month),12-abs(months-month))
            kernel=np.exp(-distance**2/(2*config['bandwidth']**2)) if family=='circular_kernel' else (distance==0).astype(float)
            w=weights*kernel
            result.append(((Y*w[:,None]).sum(axis=0)+config['shrinkage']*mean)/(w.sum()+config['shrinkage']))
        return normalize(result)
    kind=config.get('transform','raw')
    targets=transform(Y,kind)
    X=features(months,config.get('basis','fourier'),config.get('harmonics',2))
    future=features(range(1,13),config.get('basis','fourier'),config.get('harmonics',2))
    if family in ('ridge','huber_ridge'):
        coef=ridge_matrix(X,targets,weights,config['alpha'])
        if family=='huber_ridge':
            for _ in range(4):
                residual=targets-X@coef
                scale=np.maximum(np.median(abs(residual),axis=0)*1.4826,1e-7)
                for category in range(targets.shape[1]):
                    robust=np.minimum(1,config['delta']*scale[category]/np.maximum(abs(residual[:,category]),1e-9))
                    coef[:,category]=ridge_matrix(X,targets[:,category:category+1],weights*robust,config['alpha'])[:,0]
        predicted=future@coef
    elif family in ('random_forest','extra_trees'):
        cls=RandomForestRegressor if family=='random_forest' else ExtraTreesRegressor
        model=cls(n_estimators=config['trees'],max_depth=config['depth'],min_samples_leaf=config['min_leaf'],random_state=20261104,n_jobs=1)
        model.fit(X[:,1:],targets,sample_weight=weights)
        predicted=model.predict(future[:,1:])
    elif family=='gradient_boosting':
        model=MultiOutputRegressor(GradientBoostingRegressor(n_estimators=config['trees'],max_depth=config['depth'],learning_rate=.05,loss='huber',random_state=20261104),n_jobs=1)
        model.fit(X[:,1:],targets,sample_weight=weights)
        predicted=model.predict(future[:,1:])
    elif family=='rbf_kernel_ridge':
        model=KernelRidge(alpha=config['alpha'],kernel='rbf',gamma=config['gamma'])
        model.fit(X[:,1:],targets,sample_weight=weights)
        predicted=model.predict(future[:,1:])
    elif family=='mlp':
        model=MLPRegressor(hidden_layer_sizes=(config['width'],),activation='tanh',solver='lbfgs',alpha=config['alpha'],max_iter=500,random_state=20261104)
        model.fit(X[:,1:],targets,sample_weight=weights)
        predicted=model.predict(future[:,1:])
    elif family=='multitask_elastic_net':
        ymean=np.average(targets,axis=0,weights=weights)
        root=np.sqrt(weights[:,None])
        model=MultiTaskElasticNet(alpha=config['alpha'],l1_ratio=config['l1_ratio'],fit_intercept=False,max_iter=10000,random_state=20261104)
        model.fit(X[:,1:]*root,(targets-ymean)*root)
        predicted=model.predict(future[:,1:])+ymean
    else:raise ValueError('Unknown family '+family)
    if not np.isfinite(predicted).all():raise ValueError('Non-finite learned predictions')
    return inverse(predicted,kind)


def measure(actual,predicted,threshold,categories):
    actual=np.asarray(actual);predicted=np.asarray(predicted)
    errors=abs(actual-predicted)
    hits=int((errors<=threshold+1e-12).sum())
    top=np.argsort(actual.mean(axis=0))[-min(10,len(categories)):]
    return {'mae_percentage_points':float(errors.mean()*100),'rmse_percentage_points':float(np.sqrt((errors**2).mean())*100),
            'within_tolerance':{'threshold_percentage_points':threshold*100,'hits':hits,'total':int(errors.size),'percent':100*hits/errors.size},
            'panels':len(actual),'category_count':len(categories),'max_error_percentage_points':float(errors.max()*100),
            'top10_mae_percentage_points':float(errors[:,top].mean()*100),
            'by_category':{name:{'mae_percentage_points':float(errors[:,i].mean()*100),'within_percent':float((errors[:,i]<=threshold+1e-12).mean()*100)} for i,name in enumerate(categories)}}


def datasets():
    panels,source=audience.read_panels(ROOT/'data_raw/hub/hub_1048_5832.csv')
    one={'id':'1048','panels':panels,'categories':audience.CATEGORIES,'parents':{'all':list(range(8))},'source':source,
         'threshold':.01,'test_start':'2024-01','test_end':'2025-06','folds':[('2022-06','2022-07','2022-12'),('2022-12','2023-01','2023-06'),('2023-06','2023-07','2023-12')]}
    panels,categories,parents,parent_indices,source=dining.read_panels(ROOT/'data_raw/hub/hub_1047_5831.csv')
    for row in panels:row['audience']='all'
    two={'id':'1047','panels':panels,'categories':categories,'parents':parent_indices,'source':source,
         'threshold':.0025,'test_start':'2023-01','test_end':'2024-12','folds':[('2021-06','2021-07','2021-12'),('2021-12','2022-01','2022-06'),('2022-06','2022-07','2022-12')]}
    return [one,two]


def tables_for(rows,config,dataset):
    return {group:fit_table([row for row in rows if row['audience']==group],config,dataset['parents']) for group in sorted({row['audience'] for row in rows})}


def predict_rows(tables,rows):return [tables[row['audience']][row['calendar_month']-1] for row in rows]


def main():
    started=time.monotonic()
    all_configs=registry();data=datasets()
    protocol={'schema_version':1,'created_date_kst':'2026-11-04','target_percent':93,'runtime_llm':False,
        'training_libraries':{'numpy':np.__version__,'sklearn':sklearn.__version__},'candidate_count':len(all_configs),
        'candidates':[dict(candidate_id=f'c{i:03}',config=config) for i,config in enumerate(all_configs)],
        'datasets':{d['id']:{'source':d['source'],'threshold_percentage_points':d['threshold']*100,'test_start':d['test_start'],'test_end':d['test_end'],'rolling_folds':d['folds'],'categories':d['categories']} for d in data},
        'selection':{'primary':'maximum fixed-tolerance hit rate over all rolling validation cells','guard':'validation MAE <= incumbent validation MAE *1.02','secondary':'minimum validation MAE then candidate order','test_used_for_selection':False},
        'test_status':'previously_seen_retrospective_fixed_period_not_pristine_external_holdout','missing_imputed':False,'month_only_inference':True}
    protocol['protocol_sha256']=digest(protocol)
    write(SUPPORT/'protocol_frozen_before_validation.json',protocol)
    print(f'Frozen {len(all_configs)} candidates before validation; protocol '+protocol['protocol_sha256'],flush=True)
    summaries=[]
    for dataset in data:
        ident=dataset['id'];panels=dataset['panels'];categories=dataset['categories']
        candidates=[]
        for i,config in enumerate(all_configs):
            if ident=='1048' and config['family']=='hierarchical_ridge':continue
            actual=[];predicted=[];fold_results=[];captured=[]
            try:
                for end,start,finish in dataset['folds']:
                    train=[row for row in panels if row['month']<=end]
                    validation=[row for row in panels if start<=row['month']<=finish]
                    assert finish<dataset['test_start']
                    with warnings.catch_warnings(record=True) as notices:
                        warnings.simplefilter('always')
                        tables=tables_for(train,config,dataset)
                    captured.extend(str(n.message)[:250] for n in notices)
                    predictions=predict_rows(tables,validation)
                    actual.extend(row['shares'] for row in validation);predicted.extend(predictions)
                    metrics=measure([row['shares'] for row in validation],predictions,dataset['threshold'],categories)
                    fold_results.append({'fit_end':end,'validation_start':start,'validation_end':finish,'mae_percentage_points':metrics['mae_percentage_points'],'within_tolerance':metrics['within_tolerance']})
                measured=measure(actual,predicted,dataset['threshold'],categories)
                candidates.append({'candidate_id':f'c{i:03}','config':config,'validation':{key:value for key,value in measured.items() if key!='by_category'},'folds':fold_results,'warning_count':len(captured),'warning_examples':sorted(set(captured))[:2]})
            except Exception as exc:
                candidates.append({'candidate_id':f'c{i:03}','config':config,'failed':type(exc).__name__+': '+str(exc)})
            if i%100==0:print(f'{ident}: candidate {i}/{len(all_configs)} elapsed {time.monotonic()-started:.1f}s',flush=True)
        valid=[c for c in candidates if 'validation' in c]
        incumbent=next(c for c in valid if c['config'].get('incumbent'))
        guard=incumbent['validation']['mae_percentage_points']*1.02
        eligible=[c for c in valid if c['validation']['mae_percentage_points']<=guard]
        selected=min(eligible,key=lambda c:(-c['validation']['within_tolerance']['percent'],c['validation']['mae_percentage_points'],c['candidate_id']))
        frozen={'dataset_id':ident,'protocol_sha256':protocol['protocol_sha256'],'selected_candidate_id':selected['candidate_id'],'selected_config':selected['config'],'selection_uses_test':False,
                'validation':selected['validation'],'incumbent_validation':incumbent['validation'],'mae_guard':guard,'selected_before_test':True}
        frozen['selection_sha256']=digest(frozen)
        write(OUT/f'{ident}_selection_freeze.json',frozen)
        write(SUPPORT/f'{ident}_validation_candidates.json',{'protocol_sha256':protocol['protocol_sha256'],'candidates':candidates})
        # Only the selected learner, incumbent, and simple same-fit mean touch test.
        fit_rows=[row for row in panels if row['month']<dataset['test_start']]
        test_rows=[row for row in panels if dataset['test_start']<=row['month']<=dataset['test_end']]
        test_actual=[row['shares'] for row in test_rows]
        test_metrics={}
        for name,config in [('selected',selected['config']),('incumbent_same_fit',incumbent['config']),('mean_same_fit',{'family':'weighted_mean','window':0,'half_life':0})]:
            tables=tables_for(fit_rows,config,dataset)
            test_metrics[name]=measure(test_actual,predict_rows(tables,test_rows),dataset['threshold'],categories)
        chosen_test=test_metrics['selected'];old_test=test_metrics['incumbent_same_fit']
        deploy_gate=(chosen_test['within_tolerance']['percent']>old_test['within_tolerance']['percent'] and chosen_test['mae_percentage_points']<=old_test['mae_percentage_points'])
        # Full observation refit has the exact configuration chosen before test.
        serving=tables_for(panels,selected['config'],dataset)
        model={'schema_version':1,'dataset_id':ident,'algorithm':'validation_selected_monthly_composition_ensemble_v20','selected_family':selected['config']['family'],
            'selected_config':selected['config'],'source_sha256':dataset['source']['source_sha256'],'categories':categories,
            'source_period':{'start':min(row['month'] for row in panels),'end':max(row['month'] for row in panels)},
            'monthly_profiles':{group:{str(month+1):values.tolist() for month,values in enumerate(table)} for group,table in serving.items()},
            'protocol_sha256':protocol['protocol_sha256'],'selection_sha256':frozen['selection_sha256'],'metrics':chosen_test,
            'threshold_percentage_points':dataset['threshold']*100,'target_93_met_at_fixed_threshold':chosen_test['within_tolerance']['percent']>=93,
            'deployment_gate_pass':deploy_gate,'test_status':protocol['test_status'],'runtime_dependencies':'python_standard_library_only','runtime_llm':False}
        model['model_sha256']=digest(model)
        write(OUT/f'{ident}_candidate_model.json',model)
        result={'dataset_id':ident,'source':dataset['source'],'candidate_count':len(candidates),'successful_candidates':len(valid),'family_count':len({c['config']['family'] for c in valid}),
          'selection':frozen,'test_period':{'start':dataset['test_start'],'end':dataset['test_end']},'test':test_metrics,'deployment_gate_pass':deploy_gate,
          'deployment_gate_definition':'selected validation model must improve fixed hit rate AND not worsen MAE on frozen retrospective test; no test-based reselection',
          'target_93_met':model['target_93_met_at_fixed_threshold'],'model_sha256':model['model_sha256']}
        write(OUT/f'{ident}_comparison.json',result)
        summaries.append(result)
        print(json.dumps({'dataset':ident,'family':selected['config']['family'],'validation':selected['validation']['within_tolerance'],'test':chosen_test['within_tolerance'],'old_test':old_test['within_tolerance'],'test_mae':chosen_test['mae_percentage_points'],'old_mae':old_test['mae_percentage_points'],'deploy_gate':deploy_gate},ensure_ascii=False),flush=True)
    write(OUT/'summary.json',{'protocol_sha256':protocol['protocol_sha256'],'elapsed_seconds':time.monotonic()-started,'results':summaries})
    print('Finished in '+str(round(time.monotonic()-started,1))+'s',flush=True)


if __name__=='__main__':
    main()
    # The original frozen c000 reference uses normalized weights. The exact
    # operating comparator is assessed separately without reselecting a winner.
    corrector=ROOT/'development_support/composition_v20/correct_benchmark.py'
    if corrector.is_file():subprocess.run([sys.executable,str(corrector)],check=True)
