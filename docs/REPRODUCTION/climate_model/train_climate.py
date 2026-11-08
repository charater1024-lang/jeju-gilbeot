"""Train the frozen station/calendar experiment; evaluate its holdout once."""
from collections import Counter
import calendar,datetime,json,math,os,pickle,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;WORKSPACE=HERE.parents[1]
os.environ['OMP_NUM_THREADS']='4';os.environ['OPENBLAS_NUM_THREADS']='4';os.environ['MKL_NUM_THREADS']='4'
sys.path.append(str(WORKSPACE/'model_upgrade_20261107_work'/'training_libs'))
import numpy as np
import scipy,sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error,mean_squared_error,mean_pinball_loss
from climate_runtime import ALGORITHM,FEATURE_NAMES,PERIOD,STATIONS,features,calendar_day,component_predict,sha,load_model
from prepare_climate import build,SOURCE
from freeze_climate_protocol import row_digest
TRIAL=HERE/'trial_01'
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def point_metrics(y,p):return {'rows':len(y),'mae_c':float(mean_absolute_error(y,p)),'rmse_c':float(math.sqrt(mean_squared_error(y,p))),'bias_prediction_minus_observed_c':float(np.mean(p-y))}
def interval_metrics(y,rawlower,rawupper):
 lower=np.minimum(rawlower,rawupper);upper=np.maximum(rawlower,rawupper)
 return {'rows':len(y),'coverage':float(np.mean((y>=lower)&(y<=upper))),'mean_width_c':float(np.mean(upper-lower)),'mean_q10_q90_pinball_loss':float((mean_pinball_loss(y,lower,alpha=.1)+mean_pinball_loss(y,upper,alpha=.9))/2),'q10_pinball_loss':float(mean_pinball_loss(y,lower,alpha=.1)),'q90_pinball_loss':float(mean_pinball_loss(y,upper,alpha=.9)),'unsorted_quantile_crossing_rate':float(np.mean(rawlower>rawupper))}
def matrix(rows):return np.array([features(r['station'],r['month'],r['day']) for r in rows],dtype=np.float64)
def export_component(model):
 if isinstance(model,Ridge):return {'kind':'ridge','weights':model.coef_.tolist(),'intercept':float(model.intercept_)}
 trees=[]
 for predictors in model._predictors:
  assert len(predictors)==1;nodes=[]
  for raw in predictors[0].nodes:
   assert not raw['is_categorical']
   leaf=bool(raw['is_leaf'])
   nodes.append({'is_leaf':leaf,'value':float(raw['value']),'feature':int(raw['feature_idx']) if not leaf else 0,'threshold':float(raw['num_threshold']) if not leaf else 0.,'left':int(raw['left']),'right':int(raw['right'])})
  trees.append(nodes)
 return {'kind':'hist_gradient_boosting','baseline':float(model._baseline_prediction.ravel()[0]),'trees':trees,'leaf_values_include_learning_rate':True}
def baseline_profiles(train):
 profiles={};stationrows={s['id']:[r for r in train if r['station']==s['id']] for s in STATIONS}
 for station,rows in stationrows.items():
  target=np.array([r['target'] for r in rows]);dayvalues=np.array([r['calendar_day'] for r in rows]);months=np.array([r['month'] for r in rows])
  for month in range(1,13):
   monthly=target[months==month]
   for day in range(1,calendar.monthrange(2000,month)[1]+1):
    delta=np.abs(dayvalues-calendar_day(month,day));window=target[np.minimum(delta,PERIOD-delta)<=15]
    profiles[f'{station}|{month}|{day}']={'monthly':{'count':len(monthly),'median':float(np.median(monthly)),'q10':float(np.quantile(monthly,.1)),'q90':float(np.quantile(monthly,.9))},'calendar':{'count':len(window),'mean':float(np.mean(window)),'median':float(np.median(window)),'q10':float(np.quantile(window,.1)),'q90':float(np.quantile(window,.9))}}
 return profiles
def baseline_predict(rows,profiles,name):
 point=[];lower=[];upper=[]
 for row in rows:
  profile=profiles[f'{row["station"]}|{row["month"]}|{row["day"]}'];data=profile['monthly'] if name=='station_month_median' else profile['calendar'];key='mean' if name=='station_calendar_plusminus15_mean' else 'median'
  point.append(data[key]);lower.append(data['q10']);upper.append(data['q90'])
 return np.array(point),np.array(lower),np.array(upper)
def fit_hgb(config,X,y,shared,quantile=None):
 kw=dict(shared);kw.update({k:v for k,v in config.items() if k not in ['family','quantiles']})
 if quantile is not None:kw['quantile']=quantile
 model=HistGradientBoostingRegressor(**kw);model.fit(X,y);return model
def main():
 for name in ['selection_frozen.json','test_opened.json','evaluation.json','climate_model.json']:
  if (TRIAL/name).exists():raise RuntimeError('Climate trial already selected/opened; no rerun or retune permitted.')
 protocol=json.loads((TRIAL/'protocol_frozen.json').read_text(encoding='utf-8'));split=json.loads((TRIAL/'split_frozen.json').read_text(encoding='utf-8'))
 assert sha(TRIAL/'split_frozen.json')==protocol['split']['sha256']
 assert sha(Path(__file__))==protocol['reproducibility']['training_script_sha256']
 assert sha(HERE/'climate_runtime.py')==protocol['reproducibility']['runtime_sha256']
 assert sha(HERE/'prepare_climate.py')==protocol['reproducibility']['preparation_sha256']
 rows,sources,audit=build();assert sources==protocol['source']['files'];byid={r['id']:r for r in rows};parts={}
 for part,refs in split['rows'].items():
  for ref in refs:assert row_digest(byid[ref['id']])==ref['row_sha256'] and byid[ref['id']]['split']==part
  parts[part]=[byid[ref['id']] for ref in refs]
 train=parts['train'];dev=parts['dev'];Xtrain=matrix(train);Xdev=matrix(dev);ytrain=np.array([r['target'] for r in train]);ydev=np.array([r['target'] for r in dev])
 started=time.perf_counter();profiles=baseline_profiles(train);baselinesdev={}
 for name in protocol['baselines']['point_candidates']:
  p,l,u=baseline_predict(dev,profiles,name);baselinesdev[name]={'point':point_metrics(ydev,p),'interval':interval_metrics(ydev,l,u)}
 bestbaseline=min(protocol['baselines']['point_candidates'],key=lambda name:(baselinesdev[name]['point']['mae_c'],protocol['baselines']['point_candidates'].index(name)))
 pointmodels=[];pointresults=[];shared=protocol['candidates']['shared_hgb']
 for index,config in enumerate(protocol['candidates']['point']):
  tick=time.perf_counter()
  if config['family']=='ridge':model=Ridge(alpha=config['alpha']).fit(Xtrain,ytrain)
  else:model=fit_hgb(config,Xtrain,ytrain,shared)
  prediction=model.predict(Xdev);result={'index':index,'config':config,'fit_seconds':time.perf_counter()-tick,'dev':point_metrics(ydev,prediction)};pointresults.append(result);pointmodels.append(model)
  print(json.dumps({'point_candidate':index,**result},ensure_ascii=True),flush=True)
 intervalmodels=[];intervalresults=[]
 for index,config in enumerate(protocol['candidates']['interval_pairs']):
  tick=time.perf_counter();lower=fit_hgb(config,Xtrain,ytrain,shared,.1);upper=fit_hgb(config,Xtrain,ytrain,shared,.9)
  result={'index':index,'config':config,'fit_seconds':time.perf_counter()-tick,'dev':interval_metrics(ydev,lower.predict(Xdev),upper.predict(Xdev))};intervalmodels.append((lower,upper));intervalresults.append(result)
  print(json.dumps({'interval_pair':index,**result},ensure_ascii=True),flush=True)
 pointindex=min(range(len(pointmodels)),key=lambda i:(pointresults[i]['dev']['mae_c'],pointresults[i]['dev']['rmse_c'],i))
 intervalindex=min(range(len(intervalmodels)),key=lambda i:(intervalresults[i]['dev']['mean_q10_q90_pinball_loss'],abs(intervalresults[i]['dev']['coverage']-.8),i))
 selectedpoint=pointmodels[pointindex];selectedlower,selectedupper=intervalmodels[intervalindex]
 components={name:export_component(m) for name,m in [('point_model',selectedpoint),('lower_model',selectedlower),('upper_model',selectedupper)]}
 # JSON math is tested on dev before its frozen holdout is opened; export bugs cannot influence selection.
 devparity={}
 for name,m in [('point_model',selectedpoint),('lower_model',selectedlower),('upper_model',selectedupper)]:
  dif=float(np.max(np.abs(m.predict(Xdev)-np.array([component_predict(components[name],x) for x in Xdev]))));assert dif<1e-9;devparity[name]=dif
 selected_state={'point':selectedpoint,'lower':selectedlower,'upper':selectedupper,'feature_names':FEATURE_NAMES,'profiles':profiles}
 with (TRIAL/'selected_train_fit.pkl').open('wb') as f:pickle.dump(selected_state,f,protocol=5)
 write(TRIAL/'baseline_train_profiles.json',{'schema_version':1,'fitted_partition':'train','profiles':profiles})
 selection={'schema_version':1,'selected_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'protocol_sha256':sha(TRIAL/'protocol_frozen.json'),'split_sha256':sha(TRIAL/'split_frozen.json'),'training_script_sha256':sha(Path(__file__)),'selected_fit_sha256':sha(TRIAL/'selected_train_fit.pkl'),'baseline_profiles_sha256':sha(TRIAL/'baseline_train_profiles.json'),'versions':{'python':sys.version,'sklearn':sklearn.__version__,'numpy':np.__version__,'scipy':scipy.__version__},'baseline_dev':baselinesdev,'selected_baseline':bestbaseline,'point_candidates':pointresults,'interval_pair_candidates':intervalresults,'selected_point_index':pointindex,'selected_interval_pair_index':intervalindex,'selected_point_config':pointresults[pointindex]['config'],'selected_interval_config':intervalresults[intervalindex]['config'],'dev_export_max_abs_difference':devparity,'test_has_been_opened':False,'elapsed_fit_and_selection_seconds':time.perf_counter()-started,'actual_estimator_fit_count':len(pointmodels)+2*len(intervalmodels)}
 write(TRIAL/'selection_frozen.json',selection)
 exported={'schema_version':1,'algorithm':ALGORITHM,'model_id':'climate_station_calendar_20261107_trial_01','feature_names':FEATURE_NAMES,'stations':STATIONS,'calendar_period_days':PERIOD,'reference_period':['2000-01-01','2021-10-31'],'training_period':['2000-01-01','2016-12-31'],'validation_period':['2017-01-01','2021-10-31'],'point_config':pointresults[pointindex]['config'],'interval_config':intervalresults[intervalindex]['config'],**components,'target':'historical_daily_mean_temperature_C','interval_quantiles':[.1,.9],'quantile_sorting':True,'current_forecast':False,'rainfall_available':False,'deployment_status':'pending_single_holdout_evaluation','source':{k:protocol['source'][k] for k in ['dataset_id','title','portal','portal_url','owner','createByName','original_source','original_source_url','identity_note']},'provenance':{'protocol_sha256':sha(TRIAL/'protocol_frozen.json'),'split_sha256':sha(TRIAL/'split_frozen.json'),'selection_sha256':sha(TRIAL/'selection_frozen.json'),'runtime_sha256':sha(HERE/'climate_runtime.py'),'source_file_sha256':{s['file']:s['sha256'] for s in sources}}}
 write(TRIAL/'selected_components_frozen.json',exported)
 # The chronological holdout is first scored only after all choices and numerical export are immutable.
 write(TRIAL/'test_opened.json',{'schema_version':1,'open_count':1,'opened_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'selection_sha256':sha(TRIAL/'selection_frozen.json'),'selected_components_sha256':sha(TRIAL/'selected_components_frozen.json'),'protocol_sha256':sha(TRIAL/'protocol_frozen.json'),'split_sha256':sha(TRIAL/'split_frozen.json')})
 test=parts['test'];Xtest=matrix(test);ytest=np.array([r['target'] for r in test]);p=selectedpoint.predict(Xtest);l=selectedlower.predict(Xtest);u=selectedupper.predict(Xtest)
 pointtest=point_metrics(ytest,p);intervaltest=interval_metrics(ytest,l,u);baselinestest={};basepred={}
 for name in protocol['baselines']['point_candidates']:
  bp,bl,bu=baseline_predict(test,profiles,name);basepred[name]=bp;baselinestest[name]={'point':point_metrics(ytest,bp),'interval':interval_metrics(ytest,bl,bu)}
 perstation={};monthly={};yearly={}
 for station in STATIONS:
  mask=np.array([r['station']==station['id'] for r in test]);perstation[station['id']]={'point':point_metrics(ytest[mask],p[mask]),'interval':interval_metrics(ytest[mask],l[mask],u[mask]),'baseline_point':point_metrics(ytest[mask],basepred[bestbaseline][mask])}
 for month in range(1,13):
  mask=np.array([r['month']==month for r in test]);monthly[str(month)]={'point':point_metrics(ytest[mask],p[mask]),'interval':interval_metrics(ytest[mask],l[mask],u[mask])}
 for year in ['2019','2020','2021']:
  mask=np.array([r['date'].startswith(year) for r in test]);yearly[year]={'point':point_metrics(ytest[mask],p[mask]),'interval':interval_metrics(ytest[mask],l[mask],u[mask])}
 gates=protocol['test']['point_adoption_gate'];igates=protocol['test']['interval_adoption_gate'];ratio=pointtest['mae_c']/baselinestest[bestbaseline]['point']['mae_c']
 checks={'pooled_mae_at_most_3C':pointtest['mae_c']<=gates['pooled_mae_maximum_C'],'pooled_mae_within_2percent_of_selected_baseline':ratio<=gates['pooled_mae_ratio_to_best_dev_selected_baseline_max'],'each_station_mae_within_10percent_of_selected_baseline':all(v['point']['mae_c']<=v['baseline_point']['mae_c']*gates['each_station_mae_ratio_to_same_baseline_max'] for v in perstation.values()),'interval_coverage_75_to_90percent':igates['minimum_holdout_coverage']<=intervaltest['coverage']<=igates['maximum_holdout_coverage'],'mean_interval_width_at_most_12C':intervaltest['mean_width_c']<=igates['maximum_mean_width_C']}
 passed=all(checks.values());exported['deployment_status']='adoptable' if passed else 'research_only_gate_failed'
 parity={}
 for name,m in [('point_model',selectedpoint),('lower_model',selectedlower),('upper_model',selectedupper)]:
  dif=float(np.max(np.abs(m.predict(Xtest)-np.array([component_predict(components[name],x) for x in Xtest]))));assert dif<1e-9;parity[name]=dif
 evaluation={'schema_version':1,'evaluated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'single_holdout_open_count':1,'protocol_sha256':sha(TRIAL/'protocol_frozen.json'),'split_sha256':sha(TRIAL/'split_frozen.json'),'selection_sha256':sha(TRIAL/'selection_frozen.json'),'test_opened_sha256':sha(TRIAL/'test_opened.json'),'test_period':['2019-01-01','2021-10-31'],'test_rows':len(test),'test_unique_dates':len({r['date'] for r in test}),'selected_point_config':pointresults[pointindex]['config'],'selected_interval_config':intervalresults[intervalindex]['config'],'point_test':pointtest,'interval_test':intervaltest,'baseline_test':baselinestest,'best_dev_selected_baseline':bestbaseline,'mae_ratio_to_selected_baseline':ratio,'point_mae_improvement_c':baselinestest[bestbaseline]['point']['mae_c']-pointtest['mae_c'],'per_station':perstation,'per_month':monthly,'per_year':yearly,'adoption_checks':checks,'adoption_passed':passed,'superiority_claim_authorized':False,'interpretation':'Gate tests noninferiority tolerance and a usable historical distribution; do not claim accuracy improvement based on a marginal point difference.','stdlib_export_max_abs_difference':parity,'limitations':['Historical data ends2021-10-31, model fits2000–2016 only; dev/test held out chronologically.','Station/calendar inputs cannot know a particular future day weather or precipitation.','q10/q90 describe the distribution of daily MEAN temperature, not daily max/min or a confidence interval for a climate mean.','No year feature: no climate-trend extrapolation or2026 calibration.','Four stations and adjacent dates are correlated; raw observation counts are not independent daily forecast guarantees.']}
 write(TRIAL/'evaluation.json',evaluation);exported['provenance']['evaluation_sha256']=sha(TRIAL/'evaluation.json');exported['evaluation_summary']={'test_rows':len(test),'test_dates':len({r['date'] for r in test}),'mae_c':pointtest['mae_c'],'baseline_mae_c':baselinestest[bestbaseline]['point']['mae_c'],'mae_ratio':ratio,'coverage':intervaltest['coverage'],'mean_width_c':intervaltest['mean_width_c'],'adoption_passed':passed,'superiority_claim_authorized':False}
 write(TRIAL/'climate_model.json',exported);load_model(TRIAL/'climate_model.json')
 source_manifest={'schema_version':1,'source':protocol['source'],'raw_rows':audit['raw_rows'],'retained_rows':audit['retained_rows'],'target':'Tem_mean','feature_names':FEATURE_NAMES,'model_training_period':exported['training_period'],'reference_period':exported['reference_period'],'partition_counts':audit['partition_counts'],'deployment_allowed':passed,'deployment_status':exported['deployment_status'],'adoption_checks':checks,'evaluation_summary':exported['evaluation_summary'],'current_forecast':False,'rainfall_available':False}
 write(TRIAL/'source_manifest_sanitized.json',source_manifest)
 write(TRIAL/'artifact_manifest.json',{'schema_version':1,'files':{name:sha(TRIAL/name) for name in ['protocol_frozen.json','split_frozen.json','selection_frozen.json','test_opened.json','selected_components_frozen.json','baseline_train_profiles.json','evaluation.json','climate_model.json','source_manifest_sanitized.json']},'runtime_sha256':sha(HERE/'climate_runtime.py'),'source_files_sha256':{s['file']:s['sha256'] for s in sources},'adoption_passed':passed})
 print(json.dumps({'adoption_passed':passed,'point_test':pointtest,'interval_test':intervaltest,'baseline':bestbaseline,'baseline_point_test':baselinestest[bestbaseline]['point'],'mae_ratio':ratio,'checks':checks,'point_config':pointresults[pointindex]['config'],'interval_config':intervalresults[intervalindex]['config'],'model_bytes':(TRIAL/'climate_model.json').stat().st_size,'model_sha256':sha(TRIAL/'climate_model.json')},ensure_ascii=True),flush=True)
if __name__=='__main__':main()
