"""Freeze source-grounded development benchmarks, select on dev, evaluate once."""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import math
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
from jeju_agent.retrieval_v20 import load_documents,LexicalIndex,candidate_configs,digest

SUPPORT=ROOT/'development_support/retrieval_v20'
OUTPUT=ROOT/'models_candidates_v20/retrieval'

def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')

def matches(doc,predicate):
    for key,values in predicate.items():
        if key=='kind':
            if doc.get('kind')!=values:return False
        elif key.endswith('_any'):
            field=key[:-4]
            if not any(value.replace(' ','').casefold() in str(doc.get(field) or '').replace(' ','').casefold() for value in values):return False
        elif key.endswith('_all'):
            field=key[:-4]
            if not all(value.replace(' ','').casefold() in str(doc.get(field) or '').replace(' ','').casefold() for value in values):return False
        else:raise ValueError(key)
    return True

def build_benchmark():
    path=SUPPORT/'benchmark.json'
    if path.exists():raise ValueError('Frozen benchmark already exists. Do not rewrite after inspecting candidate/test results.')
    documents={domain:load_documents(ROOT,domain) for domain in ('tourism','guide','food','travel')}
    cases=[]
    def add(domain,split,group,stratum,queries,predicate=None,kind=None):
        relevant=[doc['id'] for doc in documents[domain] if predicate and matches(doc,predicate)]
        if predicate and not relevant:raise ValueError(('ground truth predicate has no real records',domain,group,predicate))
        for text in queries:
            cases.append({'id':f'{domain}_{len(cases):03d}','domain':domain,'split':split,'group':domain+':'+group,'stratum':stratum,'query':text,'relevant_ids':relevant,
                          'label_basis':{'source_field_predicate':predicate,'method':'explicit_source_fields_not_retrieval_output'},'kind':kind})
    # Every landmark/topic group stays entirely in one split. No rank output is consulted.
    definitions=[
      ('dev','dragon','exact_name',['용두암','용두암을 찾아주세요'],{'name_any':['용두암']}),
      ('dev','haenyeo','description_theme',['물질 해녀 도구 전시','해녀 생활 문화를 전시하는 박물관'],{'name_any':['해녀박물관']}),
      ('dev','hamdeok','description_theme',['서우봉 모래사장 해변','함덕 해수욕장'],{'name_any':['함덕']}),
      ('dev','bija','description_theme',['오래된 비자나무 숲','비자림 산책'],{'name_any':['비자림']}),
      ('dev','maze','description_theme',['현무암 돌담 미로','메이즈랜드 정보'],{'name_any':['메이즈랜드']}),
      ('dev','national','description_theme',['고고 역사 문화유산 박물관','국립 제주 박물관'],{'name_all':['국립','박물관']}),
      ('dev','porktrip','exact_name',['섭지 코지','섭지코지 소개'],{'name_any':['섭지코지']}),
      ('dev','snoopy','description_theme',['피너츠 캐릭터 정원','스누피 가든'],{'name_any':['스누피가든']}),
      ('dev','borom','description_theme',['메밀밭 꽃 농장','보롬왓 정보'],{'name_any':['보롬왓']}),
      ('test','waterfall','description_theme',['난대림 폭포 산책로','천지연 폭포를 찾아줘'],{'name_any':['천지연']}),
      ('test','tea','description_theme',['차 문화 녹차밭','오설록 티뮤지엄'],{'name_any':['오설록']}),
      ('test','folk','description_theme',['조선 말기 가옥 생활문화','제주 민속촌'],{'name_any':['제주민속촌']}),
      ('test','peace','description_theme',['평화 인권 추모 기념관','제주4.3평화공원'],{'name_any':['제주4.3평화공원']}),
      ('test','computer','description_theme',['컴퓨터 게임 전시','넥슨 컴퓨터 박물관'],{'name_any':['넥슨컴퓨터박물관']}),
      ('test','office','description_theme',['옛 행정 관청 관아','제주 목관아'],{'name_any':['제주목관아']}),
      ('test','horsebeach','description_theme',['조랑말 등대 원담 해변','이호 테우 해변'],{'name_any':['이호테우']}),
      ('test','arboretum','description_theme',['자생식물 아열대 수목원','한라 수목원'],{'name_any':['한라수목원']}),
      ('test','rockcolumns','description_theme',['기둥 모양 암석 해안','주상 절리'],{'name_any':['주상절리']}),
    ]
    for domain in ('tourism','guide'):
        for split,group,stratum,queries,predicate in definitions:add(domain,split,group,stratum,queries,predicate)
        for split in ('dev','test'):
            queries=['현재 영업 중인 관광지','실시간 혼잡한 곳','예약 가능한 관광지','지금 수영가능 해변'] if split=='dev' else ['오늘 주차가능 명소','근처 관광지','반경 1km 관광지','영업시간 알려줘']
            add(domain,split,'unsupported_'+split,'unsupported',queries)
    food_defs=[
      ('dev','aewolcoffee',['애월 커피숍','애월읍 카페 명부'],{'address_any':['애월'],'category_any':['커피숍','다방','카페']}),
      ('dev','seongsankorean',['성산 한식','성산읍 한식 음식점'],{'address_any':['성산'],'category_any':['한식']}),
      ('dev','fish',['횟집','횟집 기록 검색'],{'category_any':['횟집']}),
      ('dev','noodle',['고기국수','국수 이름이 들어간 음식점'],{'name_any':['국수']}),
      ('dev','cutlass',['갈치','갈치 음식점 이름'],{'name_any':['갈치']}),
      ('dev','jocheoncoffee',['조천 커피숍','조천읍 카페 명부'],{'address_any':['조천'],'category_any':['커피숍','다방','카페']}),
      ('dev','snack',['분식','분식 업종 기록'],{'category_any':['분식']}),
      ('test','gujwacoffee',['구좌 커피숍','구좌읍 카페 명부'],{'address_any':['구좌'],'category_any':['커피숍','다방','카페']}),
      ('test','hallimkorean',['한림 한식','한림읍 한식 음식점'],{'address_any':['한림'],'category_any':['한식']}),
      ('test','pyoseoncoffee',['표선 커피숍','표선면 카페 명부'],{'address_any':['표선'],'category_any':['커피숍','다방','카페']}),
      ('test','pork',['흑돼지','흑돼지 이름 음식점'],{'name_any':['흑돼지']}),
      ('test','chinese',['중국식','중국식 업종 음식점'],{'category_any':['중국식']}),
      ('test','western',['경양식','경양식 업종 기록'],{'category_any':['경양식']}),
      ('test','seogwipofish',['서귀포 횟집','서귀포시 횟집 기록'],{'address_any':['서귀포'],'category_any':['횟집']}),
    ]
    for split,group,queries,predicate in food_defs:add('food',split,group,'category_address' if len(predicate)>1 else 'name_or_category',queries,predicate)
    for split in ('dev','test'):
        add('food',split,'unsupported_'+split,'unsupported',['지금 영업중 식당','예약가능 음식점','실시간 혼잡 식당','근처 카페'] if split=='dev' else ['영업시간 확인 식당','현재영업 식당','주차가능 음식점','가까운 식당'])
    travel_defs=[
      ('dev','gapa',['가파도 올레','가파도 걷기 코스'],{'kind':'walk','name_any':['가파도']},'walk'),
      ('dev','meoche',['머체왓 숲길','머체왓 산책 코스'],{'kind':'walk','name_any':['머체왓']},'walk'),
      ('dev','saryeoni',['사려니 숲길','사려니 걷기 정보'],{'kind':'walk','name_any':['사려니']},'walk'),
      ('dev','hyupjae',['협재 해수욕장','협재 해변 시설'],{'kind':'beach','name_any':['협재']},'beach'),
      ('dev','gwakji',['곽지 해수욕장','곽지 해변 시설'],{'kind':'beach','name_any':['곽지']},'beach'),
      ('dev','accessible_arb',['한라수목원 명부','한라수목원 접근성 참고'],{'kind':'accessible','name_any':['한라수목원']},'accessible'),
      ('dev','charger',['전기차충전소','전기차충전소 위치 기록'],{'kind':'amenity','category_any':['전기차충전소']},'amenity'),
      ('test','songak',['송악산 숲길','송악산 걷기 코스'],{'kind':'walk','name_any':['송악산']},'walk'),
      ('test','mulyeong',['물영아리오름 숲길','물영아리오름 걷기'],{'kind':'walk','name_any':['물영아리']},'walk'),
      ('test','sunrise',['해맞이길','해맞이길 산책 기록'],{'kind':'walk','name_any':['해맞이길']},'walk'),
      ('test','geumneung',['금능 해수욕장','금능 해변 시설'],{'kind':'beach','name_any':['금능']},'beach'),
      ('test','gimnyeong',['김녕 해수욕장','김녕 해변 시설'],{'kind':'beach','name_any':['김녕']},'beach'),
      ('test','accessible_folk',['제주민속촌 명부','제주민속촌 접근성 참고'],{'kind':'accessible','name_any':['제주민속촌']},'accessible'),
      ('test','parking',['공영주차장','주차장 위치 기록'],{'kind':'amenity','category_any':['주차장']},'amenity'),
    ]
    for split,group,queries,predicate,kind in travel_defs:add('travel',split,group,'source_record',queries,predicate,kind)
    for split in ('dev','test'):
        add('travel',split,'unsupported_'+split,'unsupported',['실시간 주차장','현재영업 편의시설','주차가능 시설','근처 화장실'] if split=='dev' else ['충전가능 충전소','지금영업 시설','가까운 공영주차장','없는 화장실'],None,'amenity')
    from jeju_agent.assistant_intent import _EXAMPLES
    intent_dev={
      'plan':['공항에서 오전 9시 자동차 여행 계획','내일 오전 열 시부터 다섯 시간 관광 코스','차를 타고 오전 여덟 시 출발 일정 추천','오후 1시부터 오후 6시까지 도보 일정','공항에서 아침 아홉 시 출발 저녁 다섯 시 복귀 일정','제주 여행 경로를 차로 만들어 주세요'],
      'revise':['이전 여행에서 방문 수를 하나 줄여','아까 만든 코스의 이동 시간을 줄여 줘','계산한 일정을 도보로 수정해 주세요','현재 코스에서 두 군데 줄여줘','앞서 만든 일정 시작을 오전 8시로 바꿔','추천 코스에서 용두암을 제외해'],
      'food':['5월 도민 식음료 구성비를 볼래','내국인 참고집단의 8월 카드 업종 비율','제주도민과 내국인 소비 비율을 비교해줘','2월 외식 업종 이용건수 구성비를 보고 싶어','9월 도민 외식 소비 구성 비중','내국인 12월 음식 업종 비중을 알려 주세요'],
      'mobility':['수요일 오후 버스 승차 통계를 비교해줘','일요일 아침 제주 전체 버스 이용 경향','토요일 저녁 승차 인원 추정치를 보여 주세요','버스 일반승차권의 시간대별 이용 패턴','목요일 아침과 낮 승차 집계 비교','평일 오후 버스 탑승 경향 알려줘'],
      'search':['제주 바다 경치 볼 관광지 검색','전통 생활을 볼 수 있는 박물관을 찾아줘','한림 카페 명부를 검색해 주세요','흑돼지 이름의 식당 기록 찾아줘','성산 지역 관광지 검색해 주세요','숲을 걸을 수 있는 명소 찾아줘'],
      'clarify':['오늘 비가 올지 알려줘','호텔 예약을 결제해 줘','미국 주식 가격 알려주세요','근처 식당에 전화해 줘','비밀번호를 새로 만들어 줘','한국어를 영어로 통역해 줘'],
    }
    intent_test={
      'plan':['제주공항 오전 11시 출발 자동차로 두 곳 코스 부탁해','내일 오전 8시에서 오후 4시까지 차로 여행 일정','도보로 오전 10시에 출발해 네 시간 돌아볼 코스','오늘 오후 두 시부터 여섯 시까지 일정 짜 주세요','공항 출발 자동차 여행 코스를 만들고 싶어','아침 여덟 시 출발 오후 세 시 공항 복귀하는 코스','오전 열한 시 출발해서 세 군데 관광하는 일정','제주공항에서 차로 두 시간 여행하고 돌아오게 계획','모레 오전 9시에 차로 출발하는 제주 여행 계획','자동차로 서쪽에서 하루 둘러보는 일정을 추천해 주세요'],
      'revise':['방금 만든 일정에서 방문지를 하나 줄일래','기존 관광 코스 출발을 오전 10시로 고쳐줘','추천 결과에서 용두암을 빼고 다시 계산','이 여행을 오후 네 시까지 돌아오게 수정','아까 코스의 최대 장소를 두 곳으로 바꿔','계산해 둔 동선을 더 짧게 바꿔 주세요','앞의 여행 일정은 걷는 방식으로 변경해줘','일정에서 두 장소를 덜 방문하게 줄여줘','방금 일정의 복귀 시각만 오후 다섯 시로 바꿔','처음 출발 시간을 오전 아홉 시 반으로 수정해 줘'],
      'food':['주민의 1월 외식 업종별 이용건수 비중을 보여줘','내국인의 4월 식음료 카드 소비 구성을 보고 싶어','6월 도민과 내국인 업종 비율 비교 부탁해','10월 제주도민 음식 업종 소비 패턴','12월 내국인 참고 집단 음식 이용건수 비율','3월 카드 소비 업종 구성을 비교해 주세요','제주 주민 8월 외식 소비 비중이 궁금해','7월 집단별 식음료 이용건수 구성을 보여줘','11월 도민 외식 업종별 비중 비교','내국인 참고 집단과 주민의 2월 음식 소비 비율'],
      'mobility':['월요일 오전 제주 전체 일반승차 통계','금요일 오후와 저녁 버스 승차 경향을 보여줘','일요일 버스 일반승차권 시간당 이용 인원','화요일 오전 오후 버스 이용 패턴 비교 부탁해','주말 아침 버스 승차 경향을 확인하고 싶어','수요일 저녁 제주 버스 탑승 집계를 볼래','토요일 낮 일반승차 인원 추정값 알려줘','목요일 버스 이용 통계 시간대 비교','월요일과 금요일 제주 전체 버스 승차 패턴','일요일 아침과 저녁 승차 인원을 비교해 주세요'],
      'search':['제주 옛 생활을 전시하는 관광지를 검색해줘','구좌 카페 이름과 주소를 찾아주세요','해안 풍경을 볼 수 있는 곳 검색 부탁해','한식 음식점 명부 기록을 찾고 싶어','동부 박물관을 검색해서 보여줘','푸른 숲 산책 명소를 알아봐 줘','해녀 생활문화와 관련된 관광지 찾아줘','갈치 이름이 들어간 식당을 검색해 주세요','제주의 역사 유적을 보고 싶어','전망을 감상할 수 있는 관광 명소를 찾아줘'],
      'clarify':['내 계정 암호를 바꿔 주세요','항공권을 대신 결제해 줘','오늘 날씨 예보 알려줘','해외 주가를 조회해 줘','음악을 재생해 주세요','지금 식당이 문 열었는지 확인','이번 주 축제의 실시간 예약 가능 여부','음성으로 영어 통역을 시작해 줘','카페에 전화해서 예약해 줘','그림 한 장을 그려 주세요'],
    }
    intent={'training':[{'label':label,'text':text,'group':'original_v17_'+label} for label,texts in _EXAMPLES.items() for text in texts],
            'dev':[{'label':label,'text':text,'group':'v20_dev_'+label+'_'+str(i)} for label,texts in intent_dev.items() for i,text in enumerate(texts)],
            'test':[{'label':label,'text':text,'group':'v20_test_'+label+'_'+str(i)} for label,texts in intent_test.items() for i,text in enumerate(texts)]}
    all_texts=[row['text'] for partition in intent.values() for row in partition]
    assert len(all_texts)==len(set(all_texts))
    for domain in documents:
        dev={c['group'] for c in cases if c['domain']==domain and c['split']=='dev'}
        test={c['group'] for c in cases if c['domain']==domain and c['split']=='test'}
        assert not dev&test
    benchmark={'version':1,'label_scope':'curated_source_grounded_proxy_not_real_user_accuracy','label_author':'developer authored task queries and explicit real-source field predicates',
        'training_uses_test_labels':False,'retrieval_index_scope':'all_current_source_documents_unsupervised_transductive_catalog_index',
        'corpus_counts':{d:len(v) for d,v in documents.items()},'corpus_sha256':{d:digest([{k:v for k,v in row.items() if k!='record'} for row in rows]) for d,rows in documents.items()},
        'cases':cases,'intent':intent,'candidate_configs':candidate_configs(),
        'production_rerank_scope':'reorder_same_actual_incumbent_top5_ids_only_no_candidate_additions_or_noanswer_changes',
        'primary_retrieval_metric':'first_returned_record_relevant_or_correct_no_answer_percent','additional_metrics':['hit_at_5','mrr','precision_at_5_fixed_denominator','supported_coverage','unsupported_abstention'],
        'limitations':['Queries are authored from source fields, not sampled actual user requests.','Exact-name success is reported separately from descriptive and composite queries.','No-answer safeguards are rules, not learned factual verification.','Group holdout prevents same topic/entity paraphrases crossing retrieval dev/test; indexed factual documents remain available in both as in catalog search.']}
    dump(path,benchmark)
    dump(SUPPORT/'benchmark_freeze.json',{'benchmark_sha256':digest(benchmark),'case_count':len(cases),'intent_counts':{k:len(v) for k,v in intent.items()},'created_before_candidate_selection':True,'test_tuning_forbidden':True})
    print(json.dumps({'frozen_cases':len(cases),'corpus_counts':benchmark['corpus_counts'],'intent_counts':{k:len(v) for k,v in intent.items()}},ensure_ascii=False),flush=True)

def measure(cases,predict):
    details=[]
    for case in cases:
        ids=predict(case)
        truth=set(case['relevant_ids']);valid=[i in truth for i in ids]
        success=bool(ids and ids[0] in truth) if truth else not ids
        rank=next((i for i,correct in enumerate(valid,1) if correct),None)
        details.append({'id':case['id'],'group':case['group'],'stratum':case['stratum'],'query':case['query'],'expected_count':len(truth),'returned_ids':ids,'success':success,'hit_at_5':bool(rank),'reciprocal_rank':1/rank if rank else 0,'precision_at_5':sum(valid)/5,'supported':bool(truth)})
    n=len(details);supported=[d for d in details if d['supported']];unsupported=[d for d in details if not d['supported']]
    def summarize(rows):
        return {'cases':len(rows),'successes':sum(d['success'] for d in rows),'success_percent':100*sum(d['success'] for d in rows)/len(rows) if rows else None}
    return {**summarize(details),'hit_at_5_percent':100*sum(d['hit_at_5'] for d in supported)/len(supported) if supported else None,
      'mrr':sum(d['reciprocal_rank'] for d in supported)/len(supported) if supported else None,
      'precision_at_5_fixed_denominator_percent':100*sum(d['precision_at_5'] for d in supported)/len(supported) if supported else None,
      'supported':summarize(supported),'unsupported':summarize(unsupported),
      'strata':{name:summarize([d for d in details if d['stratum']==name]) for name in sorted({d['stratum'] for d in details})},'details':details}

def baseline(case):
    domain=case['domain'];query=case['query']
    if domain=='tourism':
        from jeju_agent.tourism import search_tourism
        return [x['id'] for x in search_tourism(ROOT,{'query':query,'limit':5,'kind':'attraction'})['items']]
    if domain=='guide':
        from jeju_agent.assistant_search import search_assistant
        return [x['id'] for x in search_assistant(ROOT,query,limit=5)]
    if domain=='food':
        from jeju_agent.discovery import discovery_recommend
        result=discovery_recommend(ROOT,{'query':query,'limit':5})
        return [x['id'] for x in (result.get('unmapped_restaurants',[])+result.get('restaurants',[]))[:5]]
    from jeju_agent.travel_context import search_travel_context
    return [x['id'] for x in search_travel_context(ROOT,kind=case['kind'],query=query,limit=5)['items']]

def evaluate():
    if (OUTPUT/'retrieval_metrics.json').exists() or (OUTPUT/'intent_metrics.json').exists():
        raise SystemExit('This frozen benchmark has already been evaluated. Keep its test result; use a new version for a new experiment.')
    benchmark=json.loads((SUPPORT/'benchmark.json').read_text('utf-8'))
    frozen=json.loads((SUPPORT/'benchmark_freeze.json').read_text('utf-8'))
    assert frozen['benchmark_sha256']==digest(benchmark)
    selections={};indexes={};validations={};production_selections={};production_validations={}
    for domain in ('tourism','guide','food','travel'):
        started=time.perf_counter();docs=load_documents(ROOT,domain)
        assert digest([{k:v for k,v in row.items() if k!='record'} for row in docs])==benchmark['corpus_sha256'][domain]
        index=LexicalIndex(docs);indexes[domain]=index
        dev=[c for c in benchmark['cases'] if c['domain']==domain and c['split']=='dev']
        pools={c['id']:baseline(c) for c in dev}
        candidates=[]
        constrained=[]
        for ordinal,config in enumerate(benchmark['candidate_configs']):
            metric=measure(dev,lambda c:[r['id'] for r in index.rank(c['query'],config,kind=c['kind'],limit=5)])
            candidates.append({'candidate':ordinal,'config':config,'metrics':{k:v for k,v in metric.items() if k!='details'}})
            constrained_metric=measure(dev,lambda c:rerank_ids(index,c,config,pools[c['id']]))
            constrained.append({'candidate':ordinal,'config':config,'metrics':{k:v for k,v in constrained_metric.items() if k!='details'}})
        best=max(candidates,key=lambda c:(c['metrics']['success_percent'],c['metrics']['mrr'],c['metrics']['precision_at_5_fixed_denominator_percent'],-c['candidate']))
        selections[domain]={'selected_config':best['config'],'candidate':best['candidate'],'dev_metrics':best['metrics'],'corpus_documents':len(docs),'corpus_sha256':benchmark['corpus_sha256'][domain]}
        validations[domain]=candidates
        production_best=max(constrained,key=lambda c:(c['metrics']['success_percent'],c['metrics']['mrr'],c['metrics']['precision_at_5_fixed_denominator_percent'],-c['candidate']))
        production_selections[domain]={'selected_config':production_best['config'],'candidate':production_best['candidate'],'dev_metrics':production_best['metrics'],'corpus_documents':len(docs),'corpus_sha256':benchmark['corpus_sha256'][domain]}
        production_validations[domain]=constrained
        print(domain,'dev',best['metrics']['success_percent'],'selected',best['config'],'seconds',round(time.perf_counter()-started,2),flush=True)
    selection={'schema_version':1,'benchmark_sha256':frozen['benchmark_sha256'],'selection_scope':'dev_only_group_heldout_authored_queries','test_used_for_selection':False,'domains':selections,'production_domains':production_selections}
    selection['selection_sha256']=digest(selection)
    dump(OUTPUT/'selection.json',selection)
    dump(SUPPORT/'validation_all_candidates.json',validations)
    dump(SUPPORT/'validation_production_rerank.json',production_validations)
    # All domain selections are serialized before any test prediction is made.
    results={}
    for domain,index in indexes.items():
        test=[c for c in benchmark['cases'] if c['domain']==domain and c['split']=='test']
        selected=measure(test,lambda c:[r['id'] for r in index.rank(c['query'],selections[domain]['selected_config'],kind=c['kind'],limit=5)])
        original=measure(test,baseline)
        pools={c['id']:row['returned_ids'] for c,row in zip(test,original['details'])}
        production=measure(test,lambda c:rerank_ids(index,c,production_selections[domain]['selected_config'],pools[c['id']]))
        results[domain]={'selected':selected,'incumbent_service':original,'test_tuned':False,'real_user_accuracy_proven':False,
             'production_constrained_rerank':production,
             'production_promotion_recommended':production['success_percent']>original['success_percent'] and production['hit_at_5_percent']>=original['hit_at_5_percent'] and production['unsupported']['success_percent']>=original['unsupported']['success_percent'],
             'scope_comparison':'prototype adds reviewed source descriptions; incumbent actual API called; production candidate only reorders same five IDs, no recall/scope expansion'}
        print(domain,'test',selected['success_percent'],'incumbent',original['success_percent'],flush=True)
    dump(OUTPUT/'retrieval_metrics.json',{'schema_version':1,'benchmark_sha256':frozen['benchmark_sha256'],'quality_scope':benchmark['label_scope'],'domains':results,'all_service_accuracy_93_proven':False})
    evaluate_intent(benchmark,frozen)
    finalize()

def rerank_ids(index,case,config,ids):
    ranked=index.rank(case['query'],config,kind=case['kind'],limit=len(index.documents))
    positions={row['id']:i for i,row in enumerate(ranked)}
    return sorted(ids,key=lambda ident:positions.get(ident,len(positions)))

def evaluate_intent(benchmark,frozen):
    import numpy as np
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.naive_bayes import MultinomialNB,ComplementNB
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import LinearSVC
    from sklearn.metrics import accuracy_score,f1_score,confusion_matrix
    from jeju_agent.assistant_intent import _classify,_EXAMPLES,parse_request
    rows=benchmark['intent'];train=rows['training'];dev=rows['dev'];test=rows['test']
    texts=lambda values:[r['text'] for r in values]
    labels=lambda values:[r['label'] for r in values]
    configs=[];fits=[]
    for grams in ((2,4),(2,5),(1,3)):
        vectorizer=TfidfVectorizer(analyzer='char',ngram_range=grams,lowercase=False,sublinear_tf=True)
        x=vectorizer.fit_transform(texts(train));xd=vectorizer.transform(texts(dev))
        for family in ('nb','complement_nb','logreg','linear_svm'):
            for alpha in (.1,1.,10.):
                estimator=MultinomialNB(alpha=alpha) if family=='nb' else ComplementNB(alpha=alpha) if family=='complement_nb' else LogisticRegression(C=alpha,max_iter=1000,random_state=2026) if family=='logreg' else LinearSVC(C=alpha,random_state=2026)
                estimator.fit(x,labels(train));pred=estimator.predict(xd)
                ordinal=len(configs);configs.append({'id':ordinal,'family':family,'ngram_range':grams,'alpha_or_C':alpha,'dev_accuracy_percent':100*accuracy_score(labels(dev),pred),'dev_macro_f1':f1_score(labels(dev),pred,average='macro')})
                fits.append((vectorizer,estimator))
    best=max(configs,key=lambda r:(r['dev_accuracy_percent'],r['dev_macro_f1'],-r['id']))
    vectorizer,estimator=fits[best['id']]
    dump(OUTPUT/'intent_selection.json',{'benchmark_sha256':frozen['benchmark_sha256'],'selected':best,'candidates':configs,'test_used_for_selection':False,'sklearn_version':sklearn.__version__})
    # Portable inference exactly reproduces TF-IDF and class linear scores.
    if best['family'] in ('nb','complement_nb'):
        weights=estimator.feature_log_prob_.tolist()
        if best['family']=='complement_nb':intercepts=[0.]*len(estimator.classes_)
        else:intercepts=estimator.class_log_prior_.tolist()
    else:weights=estimator.coef_.tolist();intercepts=estimator.intercept_.tolist()
    model={'schema_version':1,'family':best['family'],'ngram_range':list(best['ngram_range']),'vocabulary':vectorizer.vocabulary_,'idf':vectorizer.idf_.tolist(),
           'weights':weights,'intercepts':intercepts,'classes':estimator.classes_.tolist(),'training_examples':len(train),'training_scope':'authored_original_v17_utterances_only','benchmark_sha256':frozen['benchmark_sha256'],'runtime_llm':False,'normalization':'sklearn_char_whitespace_collapse_lowercase_false_sublinear_tf_l2'}
    model['sha256']=digest(model);dump(OUTPUT/'intent_model.json',model)
    from jeju_agent.retrieval_v20 import classify_intent
    predictions=estimator.predict(vectorizer.transform(texts(test))).tolist()
    portable=[classify_intent(ROOT,row['text']) for row in test]
    assert predictions==portable,'portable inference differs from selected training estimator'
    baseline_predictions=[_classify(row['text'],tuple(_EXAMPLES)) for row in test]
    routed=[parse_request(row['text'])['intent'] for row in test]
    def metric(pred):return {'cases':len(test),'correct':sum(a==b for a,b in zip(labels(test),pred)),'accuracy_percent':100*accuracy_score(labels(test),pred),'macro_f1':f1_score(labels(test),pred,average='macro'),
       'classes':estimator.classes_.tolist(),'confusion_matrix':confusion_matrix(labels(test),pred,labels=estimator.classes_).tolist(),
       'errors':[{'text':r['text'],'expected':r['label'],'predicted':p} for r,p in zip(test,pred) if r['label']!=p]}
    result={'scope':'independently_frozen_authored_proxy_not_actual_user_accuracy','training_examples':len(train),'dev_examples':len(dev),'test_examples':len(test),'selected':best,
      'selected_test':metric(predictions),'incumbent_nb_test':metric(baseline_predictions),'incumbent_full_parser_test':metric(routed),'portable_matches_training_estimator':True,'real_user_accuracy_93_proven':False,
      'deployment_note':'Raw classifier comparison only. Existing parser safety/condition extraction must remain and require full regression before activation.'}
    dump(OUTPUT/'intent_metrics.json',result)
    print('intent test',result['selected_test']['accuracy_percent'],'baseline NB',result['incumbent_nb_test']['accuracy_percent'],'full parser',result['incumbent_full_parser_test']['accuracy_percent'],flush=True)

def finalize():
    """Add a post-test scope audit without changing labels, selections or predictions."""
    benchmark=json.loads((SUPPORT/'benchmark.json').read_text('utf-8'))
    frozen=json.loads((SUPPORT/'benchmark_freeze.json').read_text('utf-8'))
    assert digest(benchmark)==frozen['benchmark_sha256']
    selection=json.loads((OUTPUT/'selection.json').read_text('utf-8'))
    metrics=json.loads((OUTPUT/'retrieval_metrics.json').read_text('utf-8'))
    overlap={}
    for domain in ('tourism','guide','food','travel'):
        ids={split:{ident for row in benchmark['cases'] if row['domain']==domain and row['split']==split for ident in row['relevant_ids']} for split in ('dev','test')}
        overlap[domain]={'dev_relevant_ids':len(ids['dev']),'test_relevant_ids':len(ids['test']),'dev_test_relevant_id_overlap':len(ids['dev']&ids['test'])}
    audit={'schema_version':1,'benchmark_sha256':frozen['benchmark_sha256'],'audit_timing':'post_test_no_reselection_no_label_changes','entity_overlap':overlap,
      'food_findings':['Food query groups are disjoint, but some broad category and region/category predicates share relevant records across dev/test.','Food comparator concatenates unmapped then mapped restaurants; this differs from production UI grouping and assistant Hub780-only scope.','Food metrics are an exploratory weak proxy and cannot justify production promotion.'],
      'intent_findings':['Authored train/dev/test contain no exact duplicate utterances, but similar templates remain.','Raw classifier scores do not measure complete parser safety, missing-condition clarification or real-user accuracy.'],
      'retrieval_findings':['All query labels were derived from frozen real-source fields, not ranking outputs.','Full-index prototypes enrich descriptions and change recall; only same-top-five rerank metrics represent the proposed production hook.','Tourism and guide test positive cases mix name alternatives and descriptive queries within frozen theme strata; do not interpret their 100% prototype result as open-ended request accuracy.'],
      'all_models_93_proven':False}
    dump(SUPPORT/'quality_audit.json',audit)
    reasons={'tourism':'Small curated benchmark improves first-result success from 13/22 to 15/22 in the identical incumbent first-five pool; preserve every trust/source/geography gate.',
             'guide':'No measured gain over incumbent in identical first-five pool.',
             'food':'Production scope/group-order mismatch and dev/test relevant-record overlap; exploratory only.',
             'travel':'No measured gain over incumbent in identical first-five pool.'}
    domains={}
    for domain in reasons:
        row=metrics['domains'][domain]
        activate=domain=='tourism' and row['production_constrained_rerank']['success_percent']>row['incumbent_service']['success_percent']
        row['production_promotion_recommended']=activate
        row['promotion_scope_note']=reasons[domain]
        if domain=='food':row['evaluation_limitation']='weak_proxy_partial_entity_overlap_and_noncongruent_food_pool'
        domains[domain]={'activate':activate,'reason':reasons[domain],'pool_size':5,'same_records_only':True}
    dump(OUTPUT/'retrieval_metrics.json',metrics)
    receipt={'schema_version':1,'selection_sha256':selection['selection_sha256'],'benchmark_sha256':frozen['benchmark_sha256'],'quality_audit_sha256':digest(audit),
        'quality_scope':'curated_source_grounded_proxy_not_real_user_accuracy','domains':domains,'intent_activate':False,
        'intent_reason':'Dev-selected candidate 52/60 is lower than incumbent raw NB 54/60 on frozen authored test.',
        'failure_policy':'Return original record list if model receipt or current source corpus validation fails.','all_models_93_proven':False}
    receipt['sha256']=digest(receipt)
    dump(OUTPUT/'promotion.json',receipt)
    print(json.dumps({'promotion':{k:v['activate'] for k,v in domains.items()},'relevant_id_overlap':overlap,'intent_activate':False},ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['freeze','evaluate','finalize']);args=parser.parse_args()
    {'freeze':build_benchmark,'evaluate':evaluate,'finalize':finalize}[args.phase]()
