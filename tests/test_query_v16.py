"""Regression cases for grounded place-name requests, not an accuracy benchmark."""
from pathlib import Path
import unittest
from unittest.mock import patch

from jeju_agent import orchestrator

ROOT = Path(__file__).resolve().parents[1]


def request(query):
    return {'date': '2026-11-03', 'transport': 'car', 'start_lat': 33.506,
            'start_lon': 126.492, 'end_lat': 33.506, 'end_lon': 126.492,
            'start_minute': 540, 'end_minute': 1200, 'budget_krw': 100000,
            'max_stops': 3, 'query': query, 'region': 'all', 'excluded_ids': [],
            'origin_confirmed': True, 'origin_source': 'landmark',
            'origin_label': '공개 기준점 제주공항', 'include_geometry': False}


class GroundedQueryTests(unittest.TestCase):
    def test_real_names_with_supported_request_endings_keep_the_same_place(self):
        for name, phrase in [('섭지코지', '섭지코지 추천'),
                             ('제주목관아', '제주목관아 추천해 주세요'),
                             ('협재해수욕장', '협재해수욕장에 가고 싶어'),
                             ('오설록티뮤지엄', '오설록티뮤지엄을 추천해줘')]:
            for learned_search in (True, False):
                with self.subTest(phrase=phrase, learned_search=learned_search):
                    direct = orchestrator.run_agent(ROOT, request(name), learned_search=learned_search)
                    polite = orchestrator.run_agent(ROOT, request(phrase), learned_search=learned_search)
                    self.assertEqual(direct['status'], 'ok')
                    self.assertEqual(polite['status'], 'ok')
                    self.assertEqual(polite['request']['query'], phrase)
                    self.assertEqual([p['poi_id'] for p in direct['stops']],
                                     [p['poi_id'] for p in polite['stops']])
                    self.assertTrue(all(p['trust']['automatic_eligible'] for p in polite['stops']))

    def test_reference_search_keeps_visit_restrictions_and_extra_conditions(self):
        phrase = '성산일출봉 추천'
        restricted = orchestrator.run_agent(ROOT, request(phrase), learned_search=False)
        self.assertEqual(restricted['status'], 'infeasible')
        self.assertEqual(restricted['stops'], [])
        self.assertEqual(restricted['request']['query'], phrase)
        self.assertTrue(any(item['id'] == 'seongsan' for item in restricted['exclusions']))

        for query in ['섭지코지 실시간 개방 확인', '섭지코지와 성산일출봉 추천']:
            with self.subTest(query=query):
                result = orchestrator.run_agent(ROOT, request(query), learned_search=False)
                self.assertEqual(result['stops'], [])
                self.assertEqual(result['request']['query'], query)

    def test_negative_requests_are_not_silently_changed_to_positive_queries(self):
        for phrase in ['해변 빼고 박물관', '섭지코지 제외하고 추천', '협재해수욕장 말고',
                       '해변은 싫어', '해변 아닌 곳', '해변 안 가고 싶어',
                       '박물관을 원하지 않아', '해변은 가지 않는 코스', '해변 빼줘']:
            with self.subTest(phrase=phrase), patch.object(orchestrator, 'search_tourism') as search:
                result = orchestrator.run_agent(ROOT, request(phrase))
                self.assertEqual(result['status'], 'needs_clarification')
                self.assertEqual(result['stops'], [])
                self.assertTrue(result['suggestions'])
                search.assert_not_called()

    def test_unknown_extra_constraints_do_not_become_a_grounded_name_match(self):
        item = {'name': '섭지코지', 'map_name': '섭지코지'}
        for query in ['섭지코지 실시간 개방 확인', '섭지코지xyz987 추천',
                      '섭지코지 아니면 다른곳', '섭지코지휠체어입구']:
            with self.subTest(query=query):
                self.assertFalse(orchestrator._named_query_match(query, item))
        self.assertTrue(orchestrator._named_query_match('섭지', item))

    def test_theme_search_and_no_fallback_behavior_remain(self):
        theme = orchestrator.run_agent(ROOT, request('박물관'))
        self.assertEqual(theme['status'], 'ok')
        self.assertTrue(all(p['trust']['automatic_eligible'] for p in theme['stops']))
        unknown = orchestrator.run_agent(ROOT, request('없는관광지zxqv987654'))
        self.assertEqual(unknown['status'], 'infeasible')
        self.assertEqual(unknown['stops'], [])


if __name__ == '__main__':
    unittest.main()
