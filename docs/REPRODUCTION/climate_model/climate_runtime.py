"""Offline calendar-only historical climate estimates; never a weather forecast."""
import calendar,datetime,hashlib,json,math
from pathlib import Path

ALGORITHM='calendar_station_climate_numeric_v1'
STATIONS=[{'id':'jeju','name':'제주','attachment_id':2596},{'id':'gosan','name':'고산','attachment_id':2597},{'id':'seongsan','name':'성산','attachment_id':2598},{'id':'seogwipo','name':'서귀포','attachment_id':2599}]
FEATURE_NAMES=[f'station_{s["id"]}' for s in STATIONS]+['doy_sin_h1','doy_cos_h1','doy_sin_h2','doy_cos_h2','monthphase_sin','monthphase_cos']
PERIOD=365.25
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def calendar_day(month,day):
 if not isinstance(month,int) or isinstance(month,bool) or not isinstance(day,int) or isinstance(day,bool):raise ValueError('월과 일은 정수여야 합니다.')
 datetime.date(2000,month,day)
 if month==2 and day==29:return 58.5
 return float((datetime.date(2001,month,day)-datetime.date(2001,1,1)).days)
def features(station,month,day):
 ids=[s['id'] for s in STATIONS]
 if station not in ids:raise ValueError('관측지점을 선택하세요.')
 doy=calendar_day(month,day);angle=2*math.pi*doy/PERIOD
 phase=2*math.pi*((month-1)+(day-1)/calendar.monthrange(2000,month)[1])/12
 return [float(station==s) for s in ids]+[math.sin(angle),math.cos(angle),math.sin(2*angle),math.cos(2*angle),math.sin(phase),math.cos(phase)]
def component_predict(model,x):
 if model['kind']=='ridge':return model['intercept']+sum(a*b for a,b in zip(model['weights'],x))
 if model['kind']=='hist_gradient_boosting':
  value=model['baseline']
  for nodes in model['trees']:
   i=0
   while not nodes[i]['is_leaf']:
    node=nodes[i];i=node['left'] if x[node['feature']]<=node['threshold'] else node['right']
   value+=nodes[i]['value']
  return value
 raise ValueError('unsupported model kind')
def predict(model,station,month,day):
 x=features(station,month,day)
 if model.get('deployment_status')!='adoptable':return {'available':False,'reason':'quality_gate_not_passed'}
 point=component_predict(model['point_model'],x)
 lower=component_predict(model['lower_model'],x);upper=component_predict(model['upper_model'],x)
 if lower>upper:lower,upper=upper,lower
 return {'available':True,'station':station,'station_name':next(s['name'] for s in STATIONS if s['id']==station),'month':month,'day':day,'point_c':point,'lower_c':lower,'upper_c':upper,'interval_quantiles':[.1,.9],'target':'historical_daily_mean_temperature','reference_period':model['reference_period'],'current_forecast':False,'rainfall_available':False,'measurement':'historical seasonal distribution estimate; not daily minimum/maximum or a confidence interval for the mean'}
def load_model_value(value):
 if not isinstance(value,dict):raise ValueError('model object')
 if value.get('schema_version')!=1 or value.get('algorithm')!=ALGORITHM or value.get('feature_names')!=FEATURE_NAMES:raise ValueError('model format')
 def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
 for key in ['point_model','lower_model','upper_model']:
  m=value[key]
  if m['kind']=='ridge':
   if len(m['weights'])!=len(FEATURE_NAMES) or not all(finite(v) for v in m['weights']+[m['intercept']]):raise ValueError('ridge dimensions')
  elif m['kind']=='hist_gradient_boosting':
   if not finite(m['baseline']) or not 1<=len(m['trees'])<=500:raise ValueError('tree model')
   for nodes in m['trees']:
    if not 1<=len(nodes)<=127:raise ValueError('tree size')
    for i,node in enumerate(nodes):
     if not finite(node['value']):raise ValueError('leaf finite')
     if not node['is_leaf']:
      if not isinstance(node['feature'],int) or not 0<=node['feature']<len(FEATURE_NAMES) or not finite(node['threshold']):raise ValueError('feature threshold')
      if not all(isinstance(node[k],int) and i<node[k]<len(nodes) for k in ['left','right']):raise ValueError('acyclic child indices')
  else:raise ValueError('model kind')
 return value
def load_model(path):
 value=json.loads(Path(path).read_text(encoding='utf-8'),parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
 return load_model_value(value)
