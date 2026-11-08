"""Read immutable Hub 877 data, validate only relevant temperature observations."""
from collections import Counter
import csv,datetime,json,math
from pathlib import Path
from climate_runtime import STATIONS,calendar_day,features,sha
HERE=Path(__file__).resolve().parent;SOURCE=HERE.parent/'weather_research'
def number(value):
 try:v=float(value.strip())
 except (ValueError,AttributeError):return None
 return v if math.isfinite(v) else None
def build():
 rows=[];sources=[];drops=Counter();seen=set()
 for station in STATIONS:
  path=SOURCE/f'hub877_{station["attachment_id"]}.csv';original=list(csv.DictReader(path.open(encoding='utf-8-sig',newline='')))
  sources.append({'file':path.name,'station':station['id'],'station_name':station['name'],'attachment_id':station['attachment_id'],'url':f'https://www.jejudatahub.net/api/file?fileId=2220&id={station["attachment_id"]}','bytes':path.stat().st_size,'rows':len(original),'sha256':sha(path)})
  for index,raw in enumerate(original,2):
   raw={k.strip():v.strip() for k,v in raw.items()}
   try:date=datetime.date.fromisoformat(raw['Date'])
   except (ValueError,KeyError):drops['invalid_date']+=1;continue
   key=(station['id'],date.isoformat())
   if key in seen:raise ValueError('duplicate station/date')
   seen.add(key);target=number(raw['Tem_mean']);minimum=number(raw['Tem_min']);maximum=number(raw['Tem_max'])
   if target is None:drops['missing_or_nonfinite_mean_temperature']+=1;continue
   if not -30<=target<=50:drops['mean_temperature_outside_minus30_plus50C']+=1;continue
   if (minimum is not None and minimum>target+.01) or (maximum is not None and maximum<target-.01):drops['inconsistent_min_mean_max']+=1;continue
   split='train' if date.year<=2016 else 'dev' if date.year<=2018 else 'test'
   if not datetime.date(2000,1,1)<=date<=datetime.date(2021,10,31):raise ValueError('source period changed')
   rows.append({'id':f'{path.stem}:{index}','station':station['id'],'date':date.isoformat(),'month':date.month,'day':date.day,'calendar_day':calendar_day(date.month,date.day),'target':target,'split':split})
 return rows,sources,{'raw_rows':sum(s['rows'] for s in sources),'retained_rows':len(rows),'drops':dict(drops),'partition_counts':{part:dict(Counter(r['station'] for r in rows if r['split']==part)) for part in ['train','dev','test']},'target_column':'Tem_mean','unused_columns':['Tem_max','Tem_min','Wspeed_mean','Wspeed_max','Wspeed_min','Humid_mean','Sunshine_mean','Solar_mean','Cloud_max','Cloud_min','Season'],'quality_note':'Min/max used only for target consistency screen when observed; missing min/max does not impute or discard an otherwise valid mean. No zero filling.'}
if __name__=='__main__':
 rows,sources,audit=build();(HERE/'data_audit.json').write_text(json.dumps(dict(audit,sources=sources),ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(audit,ensure_ascii=True))
