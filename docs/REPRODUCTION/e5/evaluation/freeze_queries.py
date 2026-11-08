"""Author source-grounded evaluation prompts without inspecting model scores.

These are developer-written evaluation questions, not observed user queries,
not training examples, and not an independent field-accuracy dataset.
"""
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
parts=json.loads((OUT/'source_partitions.json').read_text(encoding='utf-8'))
by_name={r['name']:r for r in parts['rows']}

dev=[
 ('테디베어 뮤지엄','여러 나라의 곰 모양 인형과 명화를 재해석한 전시를 보고 싶어'),
 ('비자림','오래 자란 비자나무 숲에서 화산송이로 된 길을 걸어보고 싶어'),
 ('용눈이오름','둥근 산줄기와 분화구가 여러 개 있는 동부 오름의 소개가 궁금해'),
 ('일출랜드','용암으로 만들어진 굴과 전통 집, 식물을 한 동선에서 볼 수 있는 장소'),
 ('성산일출봉','얕은 바다에서 일어난 화산활동으로 생긴 분화구와 해안 절벽을 소개해줘'),
 ('용머리해안','파도가 깎은 층층의 바위 벽에서 지층 흔적을 살펴볼 장소'),
 ('사려니숲길 입구','숲 전체 소개와 실제 출발 입구를 구분해야 하는 울창한 삼나무 숲길을 찾아줘'),
 ('제주절물자연휴양림','중산간에서 삼나무 그늘길과 연못을 함께 볼 수 있는 휴양 공간'),
 ('쇠소깍','강의 민물이 바닷물과 만나는 곳에서 현무암 계곡 풍경을 보고 싶어'),
 ('국립 제주 박물관','땅속에서 나온 유물과 동북아 문화 교류로 제주 역사를 알아보고 싶어'),
 ('테디베어 뮤지엄','곰 인형을 활용해 역사와 예술을 보여주는 박물관의 안내가 궁금해'),
 ('쇠소깍','나무와 검은 바위로 둘러싸인 깊은 하구를 둘러보고 싶어'),
]
holdout=[
 ('검멀레 해수욕장','검은 모래와 바다 동굴이 함께 있는 절벽 아래 작은 해변'),
 ('검멀레 해수욕장','절벽 사이의 검은 모래사장에서 해안 동굴 풍경을 볼 수 있는 곳'),
 ('스누피가든','만화 속 장면들을 실내 전시와 바깥 정원에서 이어 보는 곳'),
 ('스누피가든','피너츠에 등장하는 캐릭터와 자연 풍경이 어우러진 정원을 찾아줘'),
 ('궷물오름','샘에서 이름을 따온 말발굽형 분화구와 억새가 있는 오름'),
 ('궷물오름','동쪽 분화구에서 솟는 샘의 이름을 딴 애월의 오름을 소개해줘'),
 ('제주민속촌','조선 말기의 제주 집과 생활자료를 전시로 살펴보는 곳'),
 ('제주민속촌','조선 말기 기준으로 꾸민 집들을 보며 제주 생활문화를 배우고 싶어'),
 ('보롬왓','메밀을 기르는 밭과 계절 꽃, 농장 동물을 함께 볼 수 있는 곳'),
 ('보롬왓','표선의 농장에서 화원을 걷고 동물도 살펴보고 싶어'),
 ('수목원테마파크','실내에서 얼음으로 만든 작품과 착시 미술, 입체 영상을 보는 곳'),
 ('수목원테마파크','얼음 조형물과 3차원 영상이 소개된 체험 공간을 찾아줘'),
 ('거문오름','용암동굴들을 만든 화산의 흔적과 숲을 함께 관찰하는 오름'),
 ('거문오름','용암동굴계의 형성과 관련된 오름에서 분화구 주변 지형과 숲을 보고 싶어'),
 ('한라수목원','도심 가까이에서 제주 토종 식물과 아열대 나무를 관찰할 수 있는 곳'),
 ('한라수목원','제주에서 자라는 나무와 풀을 전시 구역과 산책길을 따라 살펴보는 수목원'),
 ('다이나믹메이즈','실내 미로에서 동행자와 문제를 풀고 장애물에 도전하는 체험'),
 ('다이나믹메이즈','함께 길을 찾으며 미션을 해결하는 실내 체험 공간'),
 ('주상절리','용암이 식어 갈라지면서 기둥처럼 된 바위를 바닷가에서 보고 싶어'),
 ('주상절리','바다와 맞닿은 검은 돌기둥을 전망 공간에서 감상할 수 있는 지형'),
 ('따라비오름','봉우리 여러 개와 분화구가 포개진 능선에서 가을 억새 풍경을 보고 싶어'),
 ('따라비오름','부드러운 곡선을 이룬 여러 봉우리와 초지, 억새가 소개된 오름'),
 ('탐라승마장','처음 말을 접하는 사람도 알아볼 수 있는 승마 체험 공간의 소개가 궁금해'),
 ('탐라승마장','말과 교감하는 활동을 중심으로 안내하는 승마 장소를 찾아줘'),
]
dev_negative=[
 ('current_operation','지금 문 연 해변 근처 박물관 찾아줘'),
 ('accessibility','휠체어로 모든 구간을 혼자 이동할 수 있는 숲길'),
 ('food_menu','갈치조림을 파는 식당 소개해줘'),
 ('outside_jeju','서울에서 조선 왕궁을 구경할 곳'),
 ('absent_topic','실내 스키 슬로프와 눈썰매 체험을 소개해줘'),
 ('underspecified','좋은 곳 추천'),
]
holdout_negative=[
 ('current_booking','오늘 예약 가능한 승마 체험장'),
 ('current_fee','성산일출봉 입장료 얼마야'),
 ('pet_permission','반려동물 데리고 들어갈 수 있는 박물관'),
 ('live_parking_distance','협재해수욕장 근처 빈 주차장 알려줘'),
 ('outside_jeju','부산에서 광안대교 야경 볼 곳'),
 ('food_menu','흑돼지 구이를 먹을 식당을 찾아줘'),
 ('absent_topic','실제 우주선 발사를 관람하는 제주 관광지'),
 ('absent_topic','눈 덮인 빙하 동굴을 탐험할 수 있는 곳'),
 ('absent_topic','판다가 사는 동물원 관람 안내'),
 ('absent_topic','깊은 바다에서 잠수함을 타는 관광지'),
 ('underspecified','아무거나'),
 ('nonsensical','12345'),
]

def supported(group,rows):
    cases=[]
    for i,(name,query) in enumerate(rows,1):
        anchor=by_name[name]
        assert anchor['partition']==group,(name,anchor['partition'])
        assert name.replace(' ','') not in query.replace(' ',''),(name,query)
        cases.append({'id':f'{group}_supported_{i:02d}','partition':group,
                      'kind':'supported','query':query,'anchor_id':anchor['id'],
                      'anchor_name':name,'relevant_ids':[anchor['id']],
                      'evidence':[{'id':anchor['id'],'text':anchor['summary'],
                                   'source_url':anchor['source_url']}],
                      'relevance_rule':'The saved guide explicitly supports all requested identifying facts; current availability is not asserted.'})
    return cases

def negative(group,rows):
    return [{'id':f'{group}_unsupported_{i:02d}','partition':group,'kind':'unsupported',
             'category':category,'query':query,'relevant_ids':[],
             'evidence':[],'expected':'empty_or_explicit_unsupported_without_place_recommendation',
             'scope_note':'Unsupported by this verified-guide corpus/endpoint; not a claim that the activity does not exist elsewhere.'}
            for i,(category,query) in enumerate(rows,1)]

def write(name,data):
    path=OUT/name
    assert not path.exists(),('never silently replace frozen evaluation',name)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()

dev_cases=supported('dev',dev)+negative('dev',dev_negative)
hold_cases=supported('holdout',holdout)+negative('holdout',holdout_negative)
source_digest=hashlib.sha256((OUT/'source_partitions.json').read_bytes()).hexdigest()
header={'schema_version':1,'as_of':'2026-11-07','source_partitions_sha256':source_digest,
        'origin':'Developer-authored, source-grounded evaluation questions before viewing candidate scores.',
        'not_training_data':True,'not_observed_user_queries':True,
        'field_accuracy_proven':False,'candidate_scores_viewed_before_freeze':False,
        'judgement_scope':'Saved verified guide text only, with all requested identifying facts required. Displayed guide source remains mandatory.'}
hashes={'source_partitions.json':source_digest}
hashes['dev_queries.json']=write('dev_queries.json',dict(header,cases=dev_cases))
hashes['holdout_queries.json']=write('holdout_queries.json',dict(header,cases=hold_cases))
protocol={
 'schema_version':1,'protocol_id':'jeju_semantic_gpu_eval_20261107_v1','as_of':'2026-11-07',
 'score_blind_freeze':True,'fine_tuning':{'allowed_places':40,'natural_pairs':'Train place original name and source-grounded saved summary only. No authored evaluation query as training data.',
   'exclude_source_partitions':['dev','holdout'],'index_all_verified_sources_at_inference':True},
 'splits':{'train_sources':40,'dev_sources':10,'holdout_sources':12,
   'dev_supported':12,'dev_unsupported':6,'holdout_supported':24,'holdout_unsupported':12},
 'candidates':'Parent predeclared E5 small/base zero-shot and source40 adapted variants; any unavailable candidate is recorded, not replaced after holdout.',
 'selection':'Use dev labels only to choose candidate and thresholds. Freeze candidate hash, threshold, source digest, settings and dev results before one holdout evaluation.',
 'test_reuse':'Any repeated holdout-driven adjustment is exploratory and cannot be reported as the same independent holdout. Do not tune against legacy 25 either.',
 'metrics':{
   'hit_at_1':'Fraction of supported cases with any relevant ID at rank1.',
   'hit_at_3':'Fraction of supported cases with any relevant ID in first3.',
   'recall_at_3':'Mean retrieved relevant IDs in first3 divided by number of relevant IDs. With one relevant ID this equals hit_at_3.',
   'mrr_at_3':'Mean reciprocal rank of first relevant ID within first3; zero if absent.',
   'unsupported_false_response_count':'Unsupported cases returning any place recommendation. Explicit unsupported/help without place recommendations is safe.',
   'latency':'Report cold and warm CPU/GPU latency, tested threads and exact hardware separately; not center field latency.'},
 'comparison':'Run incumbent TF-IDF on identical dev/holdout queries, corpus, purpose and region; include_route_restricted=True for guide introductions, never interpret as automatic course eligibility.',
 'adoption_gate':{
   'dev_unsupported_false_response_count':0,'holdout_unsupported_false_response_count':0,
   'holdout_supported_hit_at_3_absolute_gain_min':0.10,'holdout_mrr_at_3_not_below_baseline':True,
   'legacy_exact_source_scope_and_unsupported_cases_no_regression':True,
   'source_and_policy_checks_preserved':True,'local_offline_execution_or_existing_safe_fallback_required':True,
   'note':'Accuracy gate is a developer-written functional benchmark, not evidence of real-user or future-period accuracy.'},
 'scope_limits':['Queries are authored from saved editorial summaries, not collected user behaviour.',
   'Two holdout questions per anchor place are correlated; report place count and query count separately.',
   'Every label was checked against all62 summaries. Full compound identifying facts are required, not broad shared topic alone.',
   'An empty label means unsupported by this corpus/endpoint, not proof that no such Jeju business/activity exists.',
   'Guide introduction remains separate from automatic-route eligibility; restricted source places may be described without adding to a route.',
   'Cosine/re-ranking scores are ranking scores, not calibrated confidence or current opening guarantees.'],
 'frozen_files_sha256':hashes}
hashes['protocol.json']=write('protocol.json',protocol)
write('freeze_receipt.json',{'protocol_id':protocol['protocol_id'],'files_sha256':hashes,
 'source_guides_sha256':parts['source_sha256'],'model_outputs_viewed':False,
 'total_supported_questions':36,'total_unsupported_questions':18,
 'total_places':62,'train_dev_holdout_places':[40,10,12]})
print(json.dumps({'pass':True,'files_sha256':hashes,'dev_cases':len(dev_cases),'holdout_cases':len(hold_cases)},ensure_ascii=True))
