"""Source-backed nearby dialogue using public landmark fixtures, never device GPS."""
import hashlib
import json
import math
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from jeju_agent.chatbot import chat_reply, chat_status
from jeju_agent.discovery import _distance

ROOT=Path(__file__).resolve().parents[1]
AIRPORT={'latitude':33.5104142,'longitude':126.4913534}


class NearbyChatTests(unittest.TestCase):
    def ask(self,message,location=None,state=None,declined=False):
        return chat_reply(ROOT,{'message':message,'state':state or {},'location':location,'location_declined':declined})

    def assert_nearby(self,result):
        self.assertTrue(result['location_used'])
        self.assertFalse(result['needs_location'])
        self.assertEqual(result['radius_km'],20)
        self.assertEqual(result['distance_basis'],'provided_location_straight_line')
        self.assertLessEqual(len(result['reply']),180)
        self.assertTrue(result['cards'])
        for card in result['cards']:
            self.assertIsInstance(card['latitude'],(int,float))
            self.assertIsInstance(card['longitude'],(int,float))
            self.assertTrue(math.isfinite(card['distance_km']))
            expected=_distance((AIRPORT['latitude'],AIRPORT['longitude']),(card['latitude'],card['longitude']))
            self.assertLessEqual(expected,20)
            self.assertAlmostEqual(card['distance_km'],expected,places=2)

    def test_nearby_question_requests_consent_without_search(self):
        for message in ['내 근처 추천','내 위치로 관광지 추천','주변 카페','가까운 관광지','지금 내 근처 맛집']:
            with self.subTest(message=message):
                result=self.ask(message)
                self.assertTrue(result['needs_location'])
                self.assertFalse(result['location_used'])
                self.assertEqual(result['cards'],[])
                self.assertEqual(result['intent'],'location_consent')

    def test_valid_origin_uses_real_tourism_model_and_straight_line_distances(self):
        result=self.ask('내 근처 관광지 추천',AIRPORT)
        self.assert_nearby(result)
        self.assertEqual(result['intent'],'tourism_search')
        self.assertEqual(result['answer_source'],'model_search')
        distances=[card['distance_km'] for card in result['cards']]
        self.assertEqual(distances,sorted(distances))

    def test_plain_menus_and_explicit_regions_do_not_use_shared_location(self):
        for message, intent in [('관광지 추천','tourism_menu'), ('맛집 추천','food_menu'),
                                ('먹거리 찾기','food_menu'), ('음식 추천','food_menu'),
                                ('남부 해변 추천','tourism_search')]:
            with self.subTest(message=message):
                result = self.ask(message, AIRPORT)
                self.assertFalse(result['location_used'])
                self.assertFalse(result['needs_location'])
                self.assertEqual(result['intent'], intent)
                self.assertTrue(all(card.get('distance_km') is None for card in result['cards']))
                if intent == 'tourism_search':
                    self.assertTrue(result['cards'])

    def test_nearby_food_never_appends_unmapped_permits(self):
        result=self.ask('내 근처 고기국수 추천',AIRPORT)
        self.assert_nearby(result)
        self.assertEqual(result['state']['last_query'],'고기국수')
        self.assertTrue(all(card['within_radius'] is True for card in result['cards']))
        self.assertIn('실제 메뉴',result['reply'])
        self.assertIn('관련도 분류',result['reply'])

    def test_tourism_theme_is_retained_and_not_ignored_by_location(self):
        result=self.ask('주변 해변 추천',AIRPORT)
        self.assert_nearby(result)
        self.assertEqual(result['state']['last_query'],'해변')
        self.assertTrue(all(card.get('theme_classification_match') or '해변' in card['name'] or '해수욕' in card['name'] for card in result['cards']))

    def test_stale_region_does_not_hide_local_candidates(self):
        result=self.ask('내 근처 관광지 추천',AIRPORT,{'region':'east','topic':'tourism'})
        self.assert_nearby(result)
        self.assertEqual(result['state']['region'],'all')
        explicit=self.ask('북부 주변 해변 추천',AIRPORT)
        self.assertEqual(explicit['state']['region'],'north')
        self.assertTrue(all(card['region']=='north' for card in explicit['cards']))

    def test_declining_keeps_region_search_without_distance_claims(self):
        result=self.ask('북부 내 근처 해변 추천',declined=True)
        self.assertFalse(result['needs_location'])
        self.assertFalse(result['location_used'])
        self.assertEqual(result['location_status'],'declined')
        self.assertTrue(result['cards'])
        self.assertTrue(all(card['region']=='north' and card['distance_km'] is None for card in result['cards']))
        self.assertIn('적용하지 않았습니다',result['reply'])

    def test_explicit_decline_overrides_accidentally_supplied_coordinates(self):
        result=self.ask('내 근처 맛집 추천',AIRPORT,declined=True)
        self.assertFalse(result['location_used'])
        self.assertEqual(result['location_status'],'declined')
        self.assertTrue(all(card['distance_km'] is None for card in result['cards']))

    def test_outside_jeju_is_not_presented_as_nearby(self):
        for location in [{'latitude':37.5665,'longitude':126.978},{'latitude':0,'longitude':0}]:
            with self.subTest(location=location):
                result=self.ask('내 근처 관광지 추천',location)
                self.assertEqual(result['location_status'],'outside_jeju')
                self.assertFalse(result['location_used'])
                self.assertFalse(result['needs_location'])
                self.assertEqual(result['cards'],[])
                self.assertIn('제주 범위 밖',result['reply'])

    def test_invalid_locations_and_flags_are_rejected(self):
        invalid=[[],{}, {'latitude':True,'longitude':126.5},{'latitude':'33.5','longitude':126.5},{'latitude':float('nan'),'longitude':126.5},{'latitude':33.5,'longitude':float('inf')},{'latitude':91,'longitude':126.5},{'latitude':33.5,'longitude':-181},{**AIRPORT,'accuracy_m':-1},{**AIRPORT,'accuracy_m':float('inf')},{**AIRPORT,'latitude':10**400},{**AIRPORT,'accuracy_m':10**400}]
        for location in invalid:
            with self.subTest(location=location):
                with self.assertRaises(ValueError):self.ask('관광지 추천',location)
        with self.assertRaises(ValueError):chat_reply(ROOT,{'message':'관광지 추천','location_declined':'true'})

    def test_low_accuracy_is_explicit(self):
        result=self.ask('주변 관광지 추천',{**AIRPORT,'accuracy_m':6000})
        self.assert_nearby(result)
        self.assertEqual(result['location_status'],'low_accuracy')
        self.assertIn('5km',result['reply'])

    def test_manual_landmark_is_not_described_as_device_gps(self):
        result=self.ask('근처 관광지 추천',{**AIRPORT,'source':'manual','label':'제주국제공항'})
        self.assert_nearby(result)
        self.assertEqual(result['location_source'],'manual')
        self.assertIn('선택한 기준 장소',result['reply'])
        self.assertNotIn('기기 위치',result['reply'])
        self.assertNotIn('label',result['state'])
        device=self.ask('근처 관광지 추천',AIRPORT)
        self.assertEqual(device['location_source'],'device')
        self.assertIn('동의한 기기 위치',device['reply'])
        for location in [{**AIRPORT,'source':'unsupported'},{**AIRPORT,'source':[]},{**AIRPORT,'label':'가'*101},{**AIRPORT,'label':True}]:
            with self.assertRaises(ValueError):self.ask('관광지 추천',location)

    def test_next_page_uses_fresh_origin_and_never_saves_it_in_state(self):
        first=self.ask('내 근처 관광지 추천',AIRPORT)
        second=self.ask('다른 곳 추천',AIRPORT,first['state'])
        self.assert_nearby(second)
        self.assertFalse({p['id'] for p in first['cards']}&{p['id'] for p in second['cards']})
        self.assertNotIn('latitude',json.dumps(second['state']))
        self.assertNotIn('longitude',json.dumps(second['state']))
        no_origin=self.ask('다른 곳 추천',state=first['state'])
        self.assertTrue(no_origin['needs_location'])
        self.assertEqual(no_origin['cards'],[])

    def test_user_coordinates_in_state_or_text_are_not_an_origin(self):
        result=self.ask('주변 관광지 추천',state={'location':AIRPORT,'latitude':AIRPORT['latitude'],'longitude':AIRPORT['longitude']})
        self.assertTrue(result['needs_location'])
        self.assertNotIn('latitude',json.dumps(result['state']))
        typed=self.ask('33.5104,126.4913 근처 관광지')
        self.assertFalse(typed['location_used'])
        self.assertEqual(typed['cards'],[])
        self.assertEqual(typed['intent'],'location_help')

    def test_named_landmark_nearby_is_not_confused_with_device_origin(self):
        result=self.ask('함덕 근처 카페 주소',AIRPORT)
        self.assertEqual(result['intent'],'nearby_help')
        self.assertFalse(result['location_used'])
        self.assertFalse(result['needs_location'])
        self.assertEqual(result['cards'],[])
        self.assertIn('이름으로 적은 장소',result['reply'])

    def test_landmark_name_and_vicinity_words_do_not_request_a_device_origin(self):
        for question in ['제주공항 근처 카페 추천', '함덕해수욕장 가까운 카페 추천',
                         '제주공항 부근 카페 추천', '그곳 주위 카페 추천']:
            for location in (None, AIRPORT):
                with self.subTest(question=question, location=location):
                    result = self.ask(question, location)
                    self.assertEqual(result['intent'], 'nearby_help')
                    self.assertFalse(result['needs_location'])
                    self.assertFalse(result['location_used'])
                    self.assertEqual(result['cards'], [])

    def test_explicit_radius_and_count_are_applied_to_followups_and_restart(self):
        question = '내 근처 반경 1km 카페 2곳 추천'
        consent = self.ask(question)
        self.assertTrue(consent['needs_location'])
        self.assertEqual(consent['radius_km'], 1)
        first = self.ask(question, AIRPORT)
        self.assertEqual(len(first['cards']), 2)
        self.assertEqual(first['radius_km'], 1)
        self.assertTrue(all(card['distance_km'] <= 1 for card in first['cards']))
        second = self.ask('다른 곳 추천', AIRPORT, first['state'])
        self.assertEqual(second['state']['offset'], 2)
        self.assertEqual(second['radius_km'], 1)
        self.assertFalse({card['id'] for card in first['cards']} & {card['id'] for card in second['cards']})
        restarted = chat_reply(ROOT, {'message':'다른 곳 추천', 'state':first['state'],
                                     'location':AIRPORT, 'restart_page':True})
        self.assertEqual(restarted['state']['offset'], 0)
        self.assertEqual(restarted['state']['choice_ids'], first['state']['choice_ids'])
        declined = self.ask(question, declined=True)
        self.assertEqual(declined['cards'], [])
        self.assertIn('기준 위치가 필요', declined['reply'])

    def test_refining_proximity_preserves_previous_theme_and_region(self):
        first = self.ask('북부 해변 추천')
        closer = self.ask('더 가까운 곳', AIRPORT, first['state'])
        self.assertTrue(closer['location_used'])
        self.assertEqual(closer['state']['region'], 'north')
        self.assertEqual(closer['state']['last_query'], '해변')

    def test_live_and_negative_questions_keep_existing_boundaries(self):
        for message,intent in [('내 근처 현재 영업하는 식당','realtime_unavailable'),('해변 말고 주변 박물관','clarify_negation')]:
            result=self.ask(message,AIRPORT)
            self.assertEqual(result['intent'],intent)
            self.assertEqual(result['cards'],[])

    def test_status_explains_consent_and_privacy(self):
        status=chat_status(ROOT)
        self.assertTrue(status['location_recommendation']['available'])
        self.assertTrue(status['location_recommendation']['consent_required'])
        self.assertFalse(status['privacy']['precise_location_persisted'])
        self.assertFalse(status['privacy']['precise_location_echoed'])

    def test_nearby_requests_leave_models_and_source_databases_unchanged(self):
        paths=[ROOT/'data_reference/chatbot.sqlite',ROOT/'data_reference/discovery.sqlite',ROOT/'data_reference/tourism.sqlite',ROOT/'models_tourism/tourism_tfidf.json',ROOT/'models_discovery/tfidf_model.json']
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        with patch.object(socket,'create_connection',side_effect=AssertionError('external network forbidden')):
            self.ask('내 근처 관광지 추천',AIRPORT)
            self.ask('주변 고기국수 추천',AIRPORT)
        self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


if __name__=='__main__':unittest.main()
