"""Prepare downloaded reference CSVs without mixing them into synthetic POI ML."""
import csv
import hashlib
import json
from collections import defaultdict,Counter
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from jeju_agent.context_model import train_context, forecast_context

def region_for(address):
    if any(t in address for t in ['구좌읍','성산읍','우도면','표선면']): return 'east'
    if any(t in address for t in ['한림읍','한경면','애월읍','대정읍','안덕면']): return 'west'
    if '서귀포시' in address or '남원읍' in address: return 'south'
    return 'north'

def main(root=ROOT):
    raw=root/'data_raw'/'hub'; out=root/'data_reference';out.mkdir(exist_ok=True)
    food=raw/'jeju_food_registry_780.csv'
    with food.open(encoding='cp949',newline='') as f: records=list(csv.DictReader(f))
    items=[];seen=set();updated=[]
    for row in records:
        if row['데이터갱신일자']:updated.append(row['데이터갱신일자'][:10])
        if row['영업상태명']!='영업/정상':continue
        address=(row['도로명전체주소'] or row['소재지전체주소']).strip()
        name=row['사업장명'].strip();category=row['업종구분소분류'].strip() or row['업종구분대분류']
        if not name or not address:continue
        key=(name,address,category)
        if key in seen:continue
        seen.add(key)
        items.append({'id':'food_'+hashlib.sha256('|'.join(key).encode()).hexdigest()[:14],
             'name':name,'category':category,'address':address,'region':region_for(address),
             'status':row['영업상태명'],'source_date':row['데이터갱신일자'][:10],
             'source_url':'https://www.jejudatahub.net/data/view/data/780'})
    items.sort(key=lambda r:(r['name'],r['address']))
    food_summary={'source_rows':len(records),'active_snapshot_rows':sum(r['영업상태명']=='영업/정상' for r in records),
      'indexed_rows':len(items),'latest_row_updated':max(updated),'region_counts':dict(Counter(r['region'] for r in items)),
      'source_url':'https://www.jejudatahub.net/data/view/data/780'}
    (out/'restaurants.json').write_text(json.dumps({'items':items,'source_date':max(updated),
      'note':f'허브 인허가 원자료 {len(records):,}행 중 과거 영업/정상 기록을 주소와 함께 정리했습니다. 최종 행 갱신일 {max(updated)}이며 현재 영업 여부와 맛 평가는 확인하지 않았습니다.',
      'summary':food_summary},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (out/'restaurant_profile.json').write_text(json.dumps(food_summary,ensure_ascii=False,indent=2),encoding='utf-8')

    # Keep each sex/user-type cell separate. This avoids assuming person-count
    # additivity, and trains on one explicitly defined source stratum.
    card=raw/'hub_1048_5832.csv'
    with card.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    wanted={'한식 음식점업','중식 음식점업','일식 음식점업','서양식 음식점업','비알콜 음료점업','자동차 임대업','호텔업','내항 여객 운송업'}
    groups=defaultdict(list)
    for row in rows:
        if row['user_type']=='내국인' and row['sex']=='여성' and row['biz_nm'] in wanted:
            groups[row['biz_nm']].append(row)
    all_months=sorted({r['base_year_month'] for rs in groups.values() for r in rs})
    # A consistent, complete historical panel makes missing months explicit.
    accepted={name:rs for name,rs in groups.items() if {r['base_year_month'] for r in rs}==set(all_months) and len(rs)==len(all_months)}
    if not accepted: raise ValueError('실제 카드 자료에 완전한 월별 계열이 없습니다.')
    path=out/'card_industry_month.csv'
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['month','region','category','value','measure','source_id']);w.writeheader()
        for name,rs in sorted(accepted.items()):
            for r in sorted(rs,key=lambda r:r['base_year_month']):
                ym=r['base_year_month']
                w.writerow({'month':ym[:4]+'-'+ym[4:],'region':'제주 전체 집계','category':name,'value':r['use_count'],
                            'measure':'transactions','source_id':'JBDC_1048_NATIVE_FEMALE'})
    training=train_context(path,root/'models_real_context')
    last=all_months[-1];y,m=int(last[:4]),int(last[4:]);forecast_month=f'{y+(m==12):04d}-{(m%12)+1:02d}'
    forecasts=forecast_context(root/'models_real_context'/'model_context.json',forecast_month)
    report={'source_title':'업종별 성별 카드 이용 정보','source_id':1048,
       'source_url':'https://www.jejudatahub.net/data/view/data/1048','scope_label':'제주 전체 업종별 이용건수 · 원자료 내국인 여성 구간',
       'source_filter':{'user_type':'내국인','sex':'여성'},'observation_start':all_months[0][:4]+'-'+all_months[0][4:],
       'observation_end':last[:4]+'-'+last[4:],'months':len(all_months),'categories':len(accepted),
       'excluded_incomplete_categories':sorted(wanted-set(accepted)),
       'forecast_month':forecast_month,'metrics':training['metrics'],'forecasts':forecasts,
       'note':'실제 다운로드한 과거 소비 구간으로 학습·검증했습니다. 지역별·점포별 인기 모델이 아니며 현재 제주 인기도를 의미하지 않습니다. 특정 인구집단을 모든 여행자의 선호로 일반화하지 않습니다.'}
    (out/'real_model_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'restaurants':food_summary,'real_ml_months':len(all_months),'real_ml_categories':len(accepted),
                     'real_ml_model':training['metrics']['model'],'real_ml_baseline':training['metrics']['baseline']},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
