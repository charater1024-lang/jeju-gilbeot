import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import unittest
from unittest.mock import patch

from jeju_agent.chatbot import chat_reply,chat_status,_dedupe_candidates

ROOT=Path(__file__).resolve().parents[1]

class ChatbotTests(unittest.TestCase):
    def ask(self,message,state=None):return chat_reply(ROOT,{'message':message,'state':state})

    def anchor(self):
        with sqlite3.connect(ROOT/'data_reference/chatbot.sqlite') as db:
            rows=db.execute("SELECT data_json FROM answers WHERE kind='attraction' ORDER BY featured DESC,id").fetchall()
        places=[json.loads(row[0]) for row in rows]
        self.assertTrue(places,'Approved source-overlap attractions must be materialized')
        self.assertTrue(all(p.get('source_overlap_verified') is True for p in places))
        return next((p for p in places if p['id']=='hamdeok'),places[0])

    def anchor_dialogue(self):
        point=self.anchor();result=self.ask('주소 알려줘',{'last_place_id':point['id']})
        self.assertEqual(result['cards'][0]['id'],point['id'])
        return point,result

    def test_source_counts_match_materialized_records(self):
        status=chat_status(ROOT)
        with sqlite3.connect(ROOT/'data_reference/chatbot.sqlite') as db:
            counts=dict(db.execute('SELECT kind,COUNT(*) FROM answers GROUP BY kind'))
            total=db.execute('SELECT COUNT(*) FROM answers').fetchone()[0]
        self.assertEqual(counts,status['data_counts']);self.assertEqual(total,status['prepared_answers'])
        with sqlite3.connect(ROOT/'data_reference/discovery.sqlite') as db:
            food_count=db.execute('SELECT COUNT(*) FROM restaurants').fetchone()[0]
        with sqlite3.connect(ROOT/'data_reference/tourism.sqlite') as db:
            tourism=[json.loads(row[0]) for row in db.execute('SELECT data_json FROM places')]
        self.assertGreater(len(tourism),0)
        self.assertTrue(all(p['kind']=='attraction' and p.get('source_overlap_verified') is True for p in tourism))
        self.assertEqual(counts.get('reference',0),0)
        self.assertEqual(counts.get('attraction'),len(tourism));self.assertEqual(counts.get('food'),food_count)
        self.assertEqual(total,food_count+len(tourism));self.assertEqual(status['faq_count'],26);self.assertTrue(status['ready']);self.assertFalse(status['llm_used'])
        with sqlite3.connect(ROOT/'data_reference/chatbot.sqlite') as db:
            answers=[json.loads(row[0]) for row in db.execute("SELECT data_json FROM answers WHERE kind<>'food'")]
        self.assertEqual({p['id'] for p in answers},{p['id'] for p in tourism})
        self.assertTrue(all(p.get('source_overlap_verified') is True and p['kind']=='attraction' for p in answers))

    def test_greeting_and_initial_menu(self):
        for q in ['', '안녕하세요!','처음으로']:
            r=self.ask(q);self.assertEqual(r['intent'],'welcome');self.assertGreaterEqual(len(r['quick_replies']),5);self.assertFalse(r['llm_used'])

    def test_menu_buttons_are_ready_scenarios(self):
        for message,intent in [('관광지 추천','tourism_menu'),('먹거리 추천','food_menu'),('장소 정보 안내','place_help'),('여행 일정 사용법','itinerary_help'),('데이터와 모델 안내','data_help')]:
            self.assertEqual(self.ask(message)['intent'],intent)

    def test_real_tourism_model_region_and_theme(self):
        r=self.ask('북부 해변 추천해줘')
        self.assertEqual(r['intent'],'tourism_search');self.assertEqual(r['state']['region'],'north');self.assertEqual(r['answer_source'],'model_search')
        self.assertGreaterEqual(len(r['cards']),2);self.assertTrue(all(p['region']=='north' for p in r['cards']));self.assertIn('인기도 순위는 아닙니다',r['reply'])
        from jeju_agent.tourism_access import approved_place
        hamdeok=approved_place(ROOT,'hamdeok')
        self.assertEqual(len([p for p in r['cards'] if p['name']=='함덕해수욕장']),1 if hamdeok else 0)
        self.assertEqual('hamdeok' in [p['id'] for p in r['cards']],hamdeok is not None)
        self.assertTrue(all(p.get('source_overlap_verified') is True for p in r['cards']))

    def test_exact_ordinal_sentence_and_field_followup(self):
        r=self.ask('북부 해변 추천해줘');chosen=r['cards'][1]['id']
        r=self.ask('두 번째 장소 알려줘',r['state'])
        self.assertEqual(r['intent'],'place_details');self.assertEqual(r['cards'][0]['id'],chosen)
        r=self.ask('주소 알려줘',r['state']);self.assertEqual(r['intent'],'place_address');self.assertEqual(r['cards'][0]['id'],chosen)
        self.assertNotIn('없습니다입니다',r['reply'])
        r=self.ask('영업시간은?',r['state']);self.assertEqual(r['intent'],'place_hours');self.assertIn('원자료',r['reply'])

    def test_region_followup_after_detail_keeps_theme(self):
        r=self.ask('북부 해변 추천');r=self.ask('두번째',r['state']);r=self.ask('서부로',r['state'])
        self.assertEqual(r['intent'],'tourism_search');self.assertEqual(r['state']['region'],'west');self.assertEqual(r['state']['last_query'],'해변');self.assertTrue(all(p['region']=='west' for p in r['cards']))

    def test_other_places_change_page_without_repeat(self):
        a=self.ask('박물관 추천');b=self.ask('다른 곳 추천',a['state'])
        self.assertEqual(b['intent'],'tourism_search');self.assertEqual(b['state']['offset'],5)
        self.assertFalse(set(p['id'] for p in a['cards'])&set(p['id'] for p in b['cards']))

    def test_food_desire_uses_food_model_not_generic_name(self):
        r=self.ask('고기국수 먹고 싶어')
        self.assertEqual(r['intent'],'food_search');self.assertGreater(len(r['cards']),0);self.assertIn('실제 메뉴',r['reply'])
        self.assertEqual(r['state']['last_query'],'고기국수')

    def test_food_pagination_never_exceeds_existing_limit(self):
        r=self.ask('고기국수 추천')
        ids=set()
        for i in range(6):
            fresh={p['id'] for p in r['cards']};self.assertFalse(fresh&ids);ids|=fresh
            r=self.ask('다른 곳 추천',r['state']);self.assertEqual(r['intent'],'food_search')

    def test_entity_alias_selects_curated_source(self):
        from jeju_agent.tourism_access import approved_place
        expected=approved_place(ROOT,'hamdeok');r=self.ask('함덕 주소 알려줘')
        if expected is None:
            self.assertEqual(r['intent'],'ask_place');self.assertEqual(r['cards'],[]);return
        self.assertEqual(r['cards'][0]['id'],'hamdeok');self.assertIn('조함해안로',r['reply'])
        self.assertEqual(r['answer_source'],'prepared_text');self.assertTrue(r['cards'][0]['source_overlap_verified'])
        self.assertTrue(r['cards'][0]['cross_source']['osm']['source_url'].startswith('https://www.openstreetmap.org/'))
        self.assertTrue(r['cards'][0]['official_source_url'].startswith('https://www.visitjeju.net'))

    def test_unknown_hours_and_fee_are_not_invented(self):
        with sqlite3.connect(ROOT/'data_reference/chatbot.sqlite') as db:
            places=[json.loads(row[0]) for row in db.execute("SELECT data_json FROM answers WHERE kind='attraction'")]
        for q,keys in [('영업시간 알려줘',['opening_hours']),('입장료 알려줘',['charge','fee']),('주차 정보 알려줘',['parking']),('휠체어 알려줘',['wheelchair'])]:
            point=next(p for p in places if not any((p.get('observed_tags') or {}).get(key) for key in keys))
            r=self.ask(q,{'last_place_id':point['id']});self.assertIn('원자료에 없습니다',r['reply']);self.assertNotIn('무료입니다',r['reply']);self.assertNotIn('24시간',r['reply'])

    def test_observed_hours_come_from_raw_source(self):
        with sqlite3.connect(ROOT/'data_reference/chatbot.sqlite') as db:
            rows=db.execute("SELECT id,data_json FROM answers WHERE kind='food' AND data_json LIKE '%opening_hours%' LIMIT 50").fetchall()
        p=next(json.loads(row[1]) for row in rows if json.loads(row[1]).get('observed_tags',{}).get('opening_hours'))
        r=self.ask('영업시간 알려줘',{'last_place_id':p['id']})
        self.assertEqual(r['cards'][0]['id'],p['id']);self.assertIn(str(p['observed_tags']['opening_hours']),r['reply']);self.assertIn('현재 상태를 확인한 안내가 아니',r['reply'])

    def test_ambiguous_names_require_selection(self):
        # Broad unclassified tourism rows used to create the old 고기국수 ambiguity.
        # Exercise a real surviving food-name collision with distinct source places.
        with sqlite3.connect(ROOT/'data_reference/chatbot.sqlite') as db:
            names=db.execute("SELECT name_norm,COUNT(*) AS n FROM answers WHERE kind='food' AND length(name_norm)>=3 GROUP BY name_norm HAVING COUNT(*)>1 ORDER BY n DESC,name_norm").fetchall()
            for name,_ in names:
                rows=[json.loads(row[0]) for row in db.execute("SELECT data_json FROM answers WHERE kind='food' AND name_norm=?",(name,))]
                if len({(p.get('address'),p.get('latitude'),p.get('longitude')) for p in rows})>1:
                    query=rows[0]['name']+' 정보';break
            else:self.fail('The public food corpus must contain a source-name ambiguity fixture')
        r=self.ask(query)
        self.assertEqual(r['intent'],'clarify_entity');self.assertGreater(len(r['cards']),1)
        chosen=r['cards'][1]['id'];r=self.ask('2번',r['state']);self.assertEqual(r['cards'][0]['id'],chosen)

    def test_unknown_topic_is_not_forced_into_tourism(self):
        r=self.ask('양자역학의 파동함수를 설명해줘')
        self.assertEqual(r['intent'],'fallback');self.assertEqual(r['cards'],[])

    def test_realtime_and_nearby_limits(self):
        for q in ['오늘 날씨 어때','현재 영업하는 식당','지금 버스 시간']:
            r=self.ask(q);self.assertEqual(r['intent'],'realtime_unavailable');self.assertEqual(r['cards'],[])
        for q in ['내 근처 추천','가까운 곳 추천','33.51,126.52 근처 관광지']:
            r=self.ask(q);self.assertIn('위치',r['reply']);self.assertEqual(r['cards'],[])

    def test_unknown_and_unhashable_state_values_are_dropped(self):
        r=self.ask('안내?',{'region':[],'topic':{},'last_place_id':"';DROP TABLE answers;--",'choice_ids':[{},'not_a_place'],'offset':True,'gps':{'latitude':33.51},'private_secret':'secret'})
        self.assertEqual(r['state']['region'],'all');self.assertEqual(r['state']['topic'],'menu');self.assertIsNone(r['state']['last_place_id']);self.assertEqual(r['state']['choice_ids'],[])
        self.assertNotIn('gps',r['state']);self.assertNotIn('private_secret',r['state'])

    def test_length_and_type_validation(self):
        for body in [None,[],{'message':123},{'message':'가'*301},{'message':'hi','state':[]}]:
            with self.assertRaises(ValueError):chat_reply(ROOT,body)

    def test_reset_removes_selected_context(self):
        _,r=self.anchor_dialogue();r=self.ask('처음으로',r['state'])
        self.assertIsNone(r['state']['last_place_id']);self.assertEqual(r['state']['choice_ids'],[]);self.assertEqual(r['state']['region'],'all')

    def test_duplicate_candidates_require_both_name_and_distance(self):
        rows=[{'id':'a','name':'함덕','latitude':33.5,'longitude':126.5},{'id':'b','name':'함덕','latitude':33.501,'longitude':126.501,'featured':True},{'id':'c','name':'함덕','latitude':33.6,'longitude':126.6},{'id':'d','name':'함덕','latitude':None,'longitude':None},{'id':'e','name':'다른명칭','latitude':33.501,'longitude':126.501}]
        out=_dedupe_candidates(rows);self.assertEqual([p['id'] for p in out],['b','c','d','e'])

    def test_readonly_and_no_external_connections(self):
        paths=[ROOT/'data_reference/chatbot.sqlite',ROOT/'models_tourism/tourism_tfidf.json',ROOT/'data_reference/discovery.sqlite']
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        with patch.object(socket,'create_connection',side_effect=AssertionError('external network forbidden')):
            self.ask('북부 해변 추천');self.ask('고기국수 추천');self.ask('함덕 주소')
        after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths};self.assertEqual(before,after)

    def test_named_place_current_question_precedes_record_details(self):
        for q in ['함덕 지금 비 와?','함덕해수욕장 오늘 영업시간','성산일출봉 현재 운영하니']:
            r=self.ask(q);self.assertEqual(r['intent'],'realtime_unavailable');self.assertEqual(r['cards'],[])

    def test_negative_conditions_request_positive_clarification(self):
        a=self.ask('북부 해변 추천')
        for q in ['북부 관광지는 싫어','해변 말고 박물관 추천','서부는 빼고 추천해']:
            b=self.ask(q,a['state']);self.assertEqual(b['intent'],'clarify_negation');self.assertEqual(b['state'],a['state']);self.assertEqual(b['cards'],[])

    def test_off_topic_named_place_does_not_claim_to_answer(self):
        for q in ['함덕 대통령은 누구야?','함덕 미분방정식 설명','함덕 은하의 질량 알려줘']:
            self.assertEqual(self.ask(q)['intent'],'fallback')

    def test_new_unknown_place_does_not_inherit_previous_place(self):
        point,a=self.anchor_dialogue()
        for q in ['서울역 주소 알려줘','존재하지않는제주장소 주소 알려줘','알수없는카페 영업시간 알려줘']:
            b=self.ask(q,a['state']);self.assertEqual(b['intent'],'ask_place');self.assertEqual(b['cards'],[]);self.assertNotIn('조함해안로',b['reply'])
        for q in ['주소 알려줘','그곳 주소는?','거기 영업시간은?']:
            b=self.ask(q,a['state']);self.assertTrue(b['intent'].startswith('place_'));self.assertEqual(b['cards'][0]['id'],point['id'])

    def test_service_data_faq_precedes_last_place_source(self):
        _,a=self.anchor_dialogue()
        self.assertEqual(self.ask('데이터 출처',a['state'])['intent'],'data_help')
        self.assertEqual(self.ask('출처 알려줘',a['state'])['intent'],'place_source')

    def test_fallback_does_not_pollute_region_or_next_page(self):
        a=self.ask('북부 해변 추천')
        b=self.ask('서부 삼성전자 주가 알려줘',a['state']);self.assertEqual(b['intent'],'fallback');self.assertEqual(b['state'],a['state'])
        b=self.ask('다른 곳 추천',b['state']);self.assertEqual(b['state']['region'],'north');self.assertEqual(b['state']['last_query'],'해변')

    def test_nearby_relation_and_compound_alias_do_not_change_subject(self):
        for q in ['함덕 근처 카페 주소','함덕 주변 식당','성산일출봉 근처 맛집']:
            r=self.ask(q);self.assertEqual(r['intent'],'nearby_help');self.assertEqual(r['cards'],[])
        for q in ['함덕없는카페 주소 알려줘','함덕우리집 주소 알려줘']:
            r=self.ask(q);self.assertEqual(r['intent'],'ask_place');self.assertEqual(r['cards'],[])

if __name__=='__main__':unittest.main()
