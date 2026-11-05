"""Frozen temporal comparison of real Jeju 512/561 CPU regression families.

Training dependencies are isolated outside the service. Exported serving models
use only standard-library prediction implemented in jeju_agent/bus_v20.py.
"""
from pathlib import Path
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
WORK=Path(os.environ.get('JEJU_EXPERIMENT_WORKSPACE',str(Path.cwd())))
if os.environ.get('JEJU_TRAINING_LIBS'):sys.path.insert(0,os.environ['JEJU_TRAINING_LIBS'])
sys.path.insert(0,str(ROOT))
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor,ExtraTreesRegressor,RandomForestRegressor
import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import time
from collections import defaultdict

SUPPORT=ROOT/'development_support/bus_v20'
OUTPUT=ROOT/'models_candidates_v20/bus'
for folder in [SUPPORT,OUTPUT]:folder.mkdir(parents=True,exist_ok=True)

def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def day(text):return dt.date.fromisoformat(text)
def phase(d):return 2*math.pi*(d.timetuple().tm_yday-1)/365.25
def score(y,p):
    y,p=np.asarray(y,float),np.maximum(0,np.asarray(p,float))
    e=np.abs(y-p);positive=y>0;hits=int(np.sum(e[positive]<=.2*y[positive]+1e-10));n=int(positive.sum())
    return {'mae':float(e.mean()),'rmse':float(np.sqrt(np.mean(e*e))),'wape_percent':float(100*e.sum()/y.sum()) if y.sum() else None,
      'observations':len(y),'within_20_percent':{'hits':hits,'denominator':n,'percent':100*hits/n if n else None,'excluded_zero_actual':int((~positive).sum())}}
def group_scores(rows,p):
    out={}
    for group in sorted({r['group'] for r in rows}):
        idx=[i for i,r in enumerate(rows) if r['group']==group]
        out[group]=score([rows[i]['y'] for i in idx],[p[i] for i in idx])
    return out
def load(source):
    if source=='512':
        from jeju_agent.mobility_model import _read_rows
        path=ROOT/'data_raw/hub/hub_512_5856.csv';raw,audit=_read_rows(path)
        rows=[{'date':r['date'],'group':r['bucket'],'y':r['rate'],'hours':r['hours']} for r in raw]
        audit.update(source_sha256=sha(path),raw_period={'start':rows[0]['date'],'end':rows[-1]['date']})
    else:
        import re
        path=ROOT/'data_raw/hub/hub_561_5842.csv'
        old=json.loads((ROOT/'models_route_demand/route_demand_metrics.json').read_text('utf-8'))
        cached=WORK/'tmp/route_v18/observed.json';receipt=WORK/'tmp/route_v18/audit.json'
        if cached.exists() and receipt.exists() and json.loads(receipt.read_text('utf-8'))['source_sha256']==old['audit']['sha256']==sha(path):
            raw=json.loads(cached.read_text('utf-8'))
            rows=[{'date':r['date'],'group':r['route_id'],'y':r['count'],'hours':1} for r in raw if re.fullmatch(r'\d{1,4}(?:-\d{1,3})?',r['route_id'])]
            del raw
            audit=dict(old['audit'],source_sha256=old['audit']['sha256'],cache_sha256=sha(cached),cache_raw_audit_sha256=sha(receipt))
        else:
            from jeju_agent.route_demand import read_observations
            raw,audit=read_observations(path)
            rows=[{'date':r['date'],'group':r['route_id'],'y':r['count'],'hours':1} for r in raw]
            audit['source_sha256']=audit['sha256']
    for r in rows:
        r['ord']=day(r['date']).toordinal();r['weekday']=day(r['date']).weekday();r['phase']=phase(day(r['date']))
    return rows,audit

def configs(source):
    items=[]
    def add(family,**kw):items.append({'id':f'c{len(items):03d}','family':family,**kw})
    for half in [30,60,120,365,None]:
        for statistic in ['mean','median','geomean','trimmed_mean','tolerance_mode']:add('weekday_summary',half_life=half,statistic=statistic)
    for basis in ['fourier1','fourier2','month_dummies']:
        for transform in ['raw','sqrt','log']:
            for loss in ['ridge','relative_huber']:
                for half in [90,365]:add('calendar_regression',basis=basis,transform=transform,loss=loss,half_life=half,alpha=30.)
    for width in [30,90]:
        for half in [60,365]:add('periodic_kernel',width_days=width,half_life=half,blend_weekday=.5)
    if source=='561':
        for shrink in [10,50,200]:add('hierarchical_weekday',half_life=60,shrinkage=shrink)
    for loss in ['squared_error','absolute_error','poisson']:
        for leaves in [7,15]:
            for min_leaf in [20,50]:add('hist_gradient_boosting',loss=loss,leaves=leaves,min_leaf=min_leaf,iterations=140,half_life=180)
    for family in ['extra_trees','random_forest']:
        for depth in [8,12]:
            for leaf in [8,20]:add(family,depth=depth,min_leaf=leaf,trees=70,half_life=180)
    # All blend members and weights are specified before any validation fit.
    pairs=[('weekday_summary',{'half_life':60,'statistic':'mean'},'hist_gradient_boosting',{'loss':'poisson','leaves':15,'min_leaf':50}),
           ('weekday_summary',{'half_life':60,'statistic':'median'},'calendar_regression',{'basis':'fourier2','transform':'raw','loss':'relative_huber','half_life':90}),
           ('weekday_summary',{'half_life':60,'statistic':'mean'},'periodic_kernel',{'width_days':90,'half_life':365})]
    for af,ap,bf,bp in pairs:
        a=next(x for x in items if x['family']==af and all(x.get(k)==v for k,v in ap.items()))
        b=next(x for x in items if x['family']==bf and all(x.get(k)==v for k,v in bp.items()))
        for weight in [.25,.5,.75]:add('ensemble',members=[a['id'],b['id']],weights=[weight,1-weight])
    return items

def weight(rows,half):
    end=max(r['ord'] for r in rows)
    return np.array([2**(-(end-r['ord'])/half) if half else 1 for r in rows],float)
def quantile(y,w,q=.5):
    idx=np.argsort(y);values=np.asarray(y)[idx];weights=np.asarray(w)[idx];return float(values[min(len(values)-1,int(np.searchsorted(np.cumsum(weights),q*sum(weights))))])
def center(y,w,stat):
    y,w=np.asarray(y,float),np.asarray(w,float)
    if stat=='median':return quantile(y,w)
    if stat=='geomean':return float(np.expm1(np.average(np.log1p(y),weights=w)))
    if stat=='trimmed_mean':
        lo,hi=quantile(y,w,.1),quantile(y,w,.9);mask=(y>=lo)&(y<=hi);return float(np.average(y[mask],weights=w[mask]))
    if stat=='tolerance_mode':
        # Data-derived center maximizing a fixed relative interval on FIT only.
        candidates=np.unique(np.r_[y,y/1.2,y/.8]);totals=np.array([w[np.abs(y-v)<=.2*y+1e-10].sum() for v in candidates]);best=candidates[totals==totals.max()]
        return float(best[np.argmin(np.abs(best-np.average(y,weights=w)))])
    return float(np.average(y,weights=w))
def design(rows,basis):
    values=[]
    for r in rows:
        d=day(r['date']);x=[float(d.weekday()==i) for i in range(7)]
        if basis=='month_dummies':x += [float(d.month==i) for i in range(1,13)]
        else:
            h=1 if basis=='fourier1' else 2;x += [v for k in range(1,h+1) for v in (math.sin(k*r['phase']),math.cos(k*r['phase']))]
            x += [v*float(d.weekday()>=5) for v in x[7:]]
        values.append(x)
    return np.array(values,float)
def transform(y,name):return np.log1p(y) if name=='log' else np.sqrt(y) if name=='sqrt' else y
def invert(y,name):return np.maximum(0,np.expm1(np.clip(y,-20,20))) if name=='log' else np.maximum(0,y)**2 if name=='sqrt' else np.maximum(0,y)
def tree_design(rows,group_index,scales):
    result=[]
    for r in rows:
        d=day(r['date']);p=r['phase'];scale=scales.get(r['group'],1.)
        result.append([group_index.get(r['group'],np.nan),d.weekday(),d.month,d.day,d.timetuple().tm_yday,d.isocalendar().week,math.sin(p),math.cos(p),math.sin(2*p),math.cos(2*p),math.log1p(scale)])
    return np.array(result,float)

def fit(rows,cfg,base_models=None):
    family=cfg['family'];groups=defaultdict(list)
    for r in rows:groups[r['group']].append(r)
    scales={g:max(1.,float(np.average([r['y'] for r in rs],weights=weight(rs,60)))) for g,rs in groups.items()}
    model={'config':cfg,'scales':scales,'groups':{},'fit_end':max(r['date'] for r in rows)}
    if family=='ensemble':return {**model,'members':[base_models[k] for k in cfg['members']]}
    if family in ['hist_gradient_boosting','extra_trees','random_forest']:
        gi={g:i for i,g in enumerate(sorted(groups))};x=tree_design(rows,gi,scales);y=np.array([r['y']/scales[r['group']] for r in rows]);w=weight(rows,cfg['half_life'])
        if family=='hist_gradient_boosting':
            est=HistGradientBoostingRegressor(loss=cfg['loss'],max_iter=cfg['iterations'],learning_rate=.05,max_leaf_nodes=cfg['leaves'],min_samples_leaf=cfg['min_leaf'],l2_regularization=1.,categorical_features=([0,1,2] if len(gi)<=255 else [1,2]),max_bins=255,early_stopping=False,random_state=20261104)
        else:
            klass=ExtraTreesRegressor if family=='extra_trees' else RandomForestRegressor
            # Explicit label encoding is a statistical identifier, not a geographic distance.
            est=klass(n_estimators=cfg['trees'],max_depth=cfg['depth'],min_samples_leaf=cfg['min_leaf'],max_features=1.,n_jobs=1,random_state=20261104)
        est.fit(x,y,sample_weight=w);model.update(estimator=est,group_index=gi);return model
    for group,rs in groups.items():
        y=np.array([r['y'] for r in rs],float);w=weight(rs,cfg.get('half_life'));weekdays=np.array([r['weekday'] for r in rs]);scale=scales[group]
        if family in ['weekday_summary','hierarchical_weekday','periodic_kernel']:
            stat=cfg.get('statistic','mean');default=center(y,w,stat);centers=[center(y[weekdays==i],w[weekdays==i],stat) if np.any(weekdays==i) else default for i in range(7)]
            value={'centers':centers,'default':default,'weekday_weight':[float(w[weekdays==i].sum()) for i in range(7)]}
            if family=='periodic_kernel':value.update(history=rs,weights=w)
            model['groups'][group]=value
        else:
            x=design(rs,cfg['basis']);target=transform(y/scale,cfg['transform']);base=w.copy();working=w.copy();coefs=None
            for iteration in range(8 if cfg['loss']=='relative_huber' else 1):
                penalty=np.ones(x.shape[1])*cfg['alpha'];penalty[:7]=.001
                coefs=np.linalg.solve(x.T@(working[:,None]*x)+np.diag(penalty),x.T@(working*target))
                if cfg['loss']=='relative_huber':
                    residual=target-x@coefs;threshold=max(.01,float(np.median(np.abs(residual)))*1.4826*1.35)
                    working=base*np.minimum(1.,threshold/np.maximum(1e-9,np.abs(residual)))/np.maximum(.15,np.abs(target))
            model['groups'][group]={'coefs':coefs,'scale':scale}
    if family=='hierarchical_weekday':
        parent=defaultdict(list)
        for g,rs in groups.items():
            prefix=g.split('-')[0]
            parent[prefix].extend([{**r,'y':r['y']/scales[g]} for r in rs])
        for g,info in model['groups'].items():
            rs=parent[g.split('-')[0]];w=weight(rs,cfg['half_life']);ys=np.array([r['y'] for r in rs]);wd=np.array([r['weekday'] for r in rs]);pooled=[float(np.average(ys[wd==i],weights=w[wd==i])) if np.any(wd==i) else 1 for i in range(7)]
            info['centers']=[(n*v+cfg['shrinkage']*p*scales[g])/(n+cfg['shrinkage']) for n,v,p in zip(info['weekday_weight'],info['centers'],pooled)]
    return model

def predict(model,rows):
    cfg=model['config'];family=cfg['family']
    if family=='ensemble':return sum(w*predict(m,rows) for m,w in zip(model['members'],cfg['weights']))
    if family in ['hist_gradient_boosting','extra_trees','random_forest']:
        x=tree_design(rows,model['group_index'],model['scales']);return np.maximum(0,model['estimator'].predict(x)*np.array([model['scales'].get(r['group'],1) for r in rows]))
    if family in ['periodic_kernel','calendar_regression']:
        result=np.empty(len(rows),float);indexed=defaultdict(list)
        for i,r in enumerate(rows):indexed[r['group']].append(i)
        for group,indices in indexed.items():
            value=model['groups'].get(group)
            if value is None:result[indices]=float(np.median(list(model['scales'].values())));continue
            subset=[rows[i] for i in indices]
            if family=='calendar_regression':result[indices]=invert(design(subset,cfg['basis'])@value['coefs'],cfg['transform'])*value['scale']
            else:
                history=value['history'];p=np.array([r['phase'] for r in subset])[:,None];q=np.array([r['phase'] for r in history])[None,:]
                dist=np.abs(p-q);dist=np.minimum(dist,2*math.pi-dist)*365.25/(2*math.pi)
                same=np.array([r['weekday'] for r in subset])[:,None]==np.array([r['weekday'] for r in history])[None,:]
                w=np.exp(-.5*(dist/cfg['width_days'])**2)*same*value['weights'][None,:]
                learned=(w@np.array([r['y'] for r in history]))/np.maximum(1e-12,w.sum(axis=1));baseline=np.array([value['centers'][r['weekday']] for r in subset])
                result[indices]=cfg['blend_weekday']*baseline+(1-cfg['blend_weekday'])*learned
        return np.maximum(0,result)
    pred=[]
    for r in rows:
        value=model['groups'].get(r['group'])
        if value is None:pred.append(float(np.median(list(model['scales'].values()))));continue
        if family in ['weekday_summary','hierarchical_weekday']:p=value['centers'][r['weekday']]
        elif family=='periodic_kernel':
            rs=value['history'];dist=np.array([min(abs(v['phase']-r['phase']),2*math.pi-abs(v['phase']-r['phase']))*365.25/(2*math.pi) for v in rs]);w=value['weights']*np.exp(-.5*(dist/cfg['width_days'])**2)*np.array([v['weekday']==r['weekday'] for v in rs]);p=float(np.average([v['y'] for v in rs],weights=w)) if w.sum() else value['centers'][r['weekday']];p=cfg['blend_weekday']*value['centers'][r['weekday']]+(1-cfg['blend_weekday'])*p
        else:p=float(invert(np.array(design([r],cfg['basis'])[0]@value['coefs']),cfg['transform'])*value['scale'])
        pred.append(max(0,p))
    return np.array(pred,float)

def export(model):
    cfg=model['config'];family=cfg['family'];out={k:v for k,v in model.items() if k not in ['estimator','groups','members']}
    out['groups']={}
    if family=='ensemble':out['members']=[export(m) for m in model['members']];return out
    if family=='hist_gradient_boosting':
        est=model['estimator'];out['baseline_prediction']=float(est._baseline_prediction[0,0]);trees=[]
        categorical=np.flatnonzero(est.is_categorical_).astype(int).tolist();numerical=np.flatnonzero(~est.is_categorical_).astype(int).tolist()
        out['feature_order']=categorical+numerical
        out['categorical_encoding']={str(index):values.astype(float).tolist() for index,values in zip(categorical,est._preprocessor.named_transformers_['encoder'].categories_)}
        for iteration in est._predictors:
            predictor=iteration[0];trees.append({'nodes':[{name:(float(node[name]) if name in ['value','num_threshold'] else int(node[name])) for name in ['value','feature_idx','num_threshold','missing_go_to_left','left','right','is_leaf','is_categorical','bitset_idx']} for node in predictor.nodes],
                  'raw_left_cat_bitsets':predictor.raw_left_cat_bitsets.astype(int).tolist()})
        out['trees']=trees;return out
    if family in ['extra_trees','random_forest']:
        out['trees']=[{'left':e.tree_.children_left.tolist(),'right':e.tree_.children_right.tolist(),'feature':e.tree_.feature.tolist(),'threshold':e.tree_.threshold.tolist(),'value':e.tree_.value[:,0,0].tolist()} for e in model['estimator'].estimators_];return out
    for g,v in model['groups'].items():out['groups'][g]={key:(value.tolist() if isinstance(value,np.ndarray) else value) for key,value in v.items()}
    return out

def incumbent(source,train,validation):
    if source=='512':
        from jeju_agent.mobility_model import _fit_calendar,_predict_calendar
        old=json.loads((ROOT/'models_mobility/mobility_model.json').read_text('utf-8'));parameters=old['calendar']['parameters']
        converted=[{'date':r['date'],'bucket':r['group'],'rate':r['y']} for r in train];fitted=_fit_calendar(converted,parameters)
        return np.array([_predict_calendar(fitted,day(r['date']),r['group']) for r in validation]),parameters
    config={'id':'incumbent','family':'weekday_summary','half_life':60,'statistic':'mean'}
    return predict(fit(train,config),validation),config

def split(source,rows):
    dates=sorted({r['date'] for r in rows})
    if source=='512':
        specs=[(dates[308],dates[309],dates[429]),(dates[429],dates[430],dates[550])];test_start,test_end=dates[551],dates[-1];final_end=dates[429]
    else:
        latest=day(dates[-1]);test_start=(latest-dt.timedelta(days=119)).isoformat();test_end=dates[-1];final_end=(latest-dt.timedelta(days=240)).isoformat()
        specs=[((day(final_end)-dt.timedelta(days=120)).isoformat(),(day(final_end)-dt.timedelta(days=119)).isoformat(),final_end),
               (final_end,(day(final_end)+dt.timedelta(days=1)).isoformat(),(day(test_start)-dt.timedelta(days=1)).isoformat())]
    def sample(end,start=None,stop=None):
        if source=='561':
            from jeju_agent.route_demand import _eligible
            original=[{'date':r['date'],'route_id':r['group'],'count':r['y']} for r in rows if r['date']<=end]
            groups=set(_eligible(original,day(end)));lower=(day(end)-dt.timedelta(days=729)).isoformat()
        else:groups={r['group'] for r in rows};lower=dates[0]
        train=[r for r in rows if lower<=r['date']<=end and r['group'] in groups]
        val=[r for r in rows if start and start<=r['date']<=stop and r['group'] in groups]
        return train,val,sorted(groups)
    folds=[sample(end,start,stop) for end,start,stop in specs];train,test,groups=sample(final_end,test_start,test_end)
    serving,_,serving_groups=sample(dates[-1])
    return folds,train,test,serving,{'fold_dates':[{'fit_end':a,'validation_start':b,'validation_end':c} for a,b,c in specs],
            'test_start':test_start,'test_end':test_end,'final_fit_end':final_end,'evaluation_groups':groups,'serving_groups':serving_groups,
            'test_count':len(test),'test_all_source_cells':sum(test_start<=r['date']<=test_end for r in rows),
            'test_population_rule':'unchanged original per-source eligibility; absent cells never zero-filled',
            'validation_cohort_rule':'eligibility recalculated from fit rows at each historical fold end'}

def run(source):
    began=time.time();rows,audit=load(source);candidates=configs(source);folds,training,test,serving,split_info=split(source,rows)
    protocol={'source_id':source,'source_sha256':audit['source_sha256'],'created_before_fitting':True,'metric':'observed positive count ±20 percent hit rate',
       'selection':'max mean chronological-fold hit rate among MAE <=1.02*incumbent same-fold MAE; tie minimum MAE then config ID',
       'test_previously_reported':True,'test_status':'retrospective_existing_holdout_not_fresh_external','no_test_tuning':True,'split':split_info,
       'candidate_count':len(candidates),'candidates':candidates,'libraries':{'numpy':np.__version__,'scikit_learn':sklearn.__version__},'forecast_features':'known calendar and train-only source-group statistics; no validation/test actual lags'}
    folder=OUTPUT/source;folder.mkdir(parents=True,exist_ok=True);write(folder/'protocol.json',protocol)
    scores=defaultdict(list);fold_details=[]
    for fi,(train,val,groups) in enumerate(folds):
        y=[r['y'] for r in val];base_pred,base_cfg=incumbent(source,train,val);base_metrics=score(y,base_pred);fold_details.append({'fold':fi,'incumbent':base_metrics,'train_rows':len(train),'validation_rows':len(val),'groups':len(groups)})
        models={};preds={}
        for ci,cfg in enumerate(candidates):
            fitted=fit(train,cfg,models);pred=predict(fitted,val);measured=score(y,pred);scores[cfg['id']].append(measured)
            # Retain only explicit ensemble bases; avoid keeping all fitted forests in memory.
            required={m for c in candidates if c['family']=='ensemble' for m in c['members']}
            if cfg['id'] in required:models[cfg['id']]=fitted
            if ci%15==0:print(json.dumps({'source':source,'fold':fi,'candidate':ci,'family':cfg['family'],'hit':measured['within_20_percent']['percent'],'elapsed':round(time.time()-began,1)}),flush=True)
        write(folder/'validation_progress.json',{'fold_details':fold_details,'candidate_scores':dict(scores)})
    baseline_mae=float(np.mean([f['incumbent']['mae'] for f in fold_details]));table=[]
    for cfg in candidates:
        vals=scores[cfg['id']];mae=float(np.mean([v['mae'] for v in vals]));hit=float(np.mean([v['within_20_percent']['percent'] for v in vals]));table.append({'config':cfg,'mean_validation_hit_percent':hit,'mean_validation_mae':mae,'mae_guard_pass':mae<=baseline_mae*1.02,'folds':vals})
    eligible=[row for row in table if row['mae_guard_pass']]
    selected=min(eligible,key=lambda row:(-row['mean_validation_hit_percent'],row['mean_validation_mae'],row['config']['id'])) if eligible else None
    freeze={'protocol_sha256':sha(folder/'protocol.json'),'selection':selected,'validation_incumbent':fold_details,'selection_has_seen_test_targets':False}
    write(folder/'selection_freeze.json',freeze)
    # Target arrays are first used for scoring only AFTER the selection receipt.
    allcfg={c['id']:c for c in candidates}
    def selected_fit(train,cfg):
        if cfg['family']=='ensemble':return fit(train,cfg,{m:selected_fit(train,allcfg[m]) for m in cfg['members']})
        return fit(train,cfg)
    if selected is not None:
        fitted=selected_fit(training,selected['config']);test_pred=predict(fitted,test);test_score=score([r['y'] for r in test],test_pred)
        base_pred,base_cfg=incumbent(source,training,test);baseline_score=score([r['y'] for r in test],base_pred)
        learned=selected_fit(serving,selected['config']);artifact=export(learned)
        artifact.update(schema_version=1,source_id=source,source_sha256=audit['source_sha256'],selection_freeze_sha256=sha(folder/'selection_freeze.json'),
           observation_period=audit['raw_period'],fit_period={'start':min(r['date'] for r in serving),'end':max(r['date'] for r in serving)},
           group_history_last_date={g:max(r['date'] for r in serving if r['group']==g) for g in learned['scales']})
        write(folder/'candidate_model.json',artifact)
        write(folder/'predictions_test.json',{'rows':[{'date':r['date'],'group':r['group'],'observed':r['y'],'predicted':float(p),'baseline':float(b)} for r,p,b in zip(test,test_pred,base_pred)]})
        final={'source_id':source,'protocol':protocol,'validation_candidates':table,'selected_config':selected['config'],'test':test_score,'incumbent_test':baseline_score,
          'selected_by_validation_only':True,'test_config_read_count':1,'test_by_group':group_scores(test,test_pred),
          'passes_93_fixed_tolerance':test_score['within_20_percent']['percent']>=93,
          'test_mae_improves':test_score['mae']<baseline_score['mae'],'test_hit_improves':test_score['within_20_percent']['percent']>baseline_score['within_20_percent']['percent'],
          'raw_audit':audit,'runtime_standard_library_only':True,'elapsed_seconds':time.time()-began,'artifact_sha256':sha(folder/'candidate_model.json')}
    else:final={'source_id':source,'protocol':protocol,'validation_candidates':table,'selected_config':None,'reason':'no candidate passed predeclared MAE guard','passes_93_fixed_tolerance':False,'raw_audit':audit,'elapsed_seconds':time.time()-began}
    write(folder/'experiment_report.json',final)
    print(json.dumps({'source':source,'selected':final['selected_config'],'test':final.get('test'),'baseline':final.get('incumbent_test'),'pass93':final['passes_93_fixed_tolerance'],'elapsed':final['elapsed_seconds']},ensure_ascii=False),flush=True)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--source',choices=['512','561','both'],default='both');args=p.parse_args()
    for s in ['512','561'] if args.source=='both' else [args.source]:run(s)
