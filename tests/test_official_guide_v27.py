"""Verify the public guide independently of automatic itinerary eligibility."""
from pathlib import Path
import unittest
from unittest.mock import patch

from jeju_agent.assistant_search import search_assistant
from jeju_agent.place_trust import place_trust


ROOT = Path(__file__).resolve().parents[1]


class OfficialGuideV27Tests(unittest.TestCase):
    def test_exact_public_title_stays_on_the_requested_place(self):
        for query in ('성산일출봉', '성산 일출봉', '성산일출봉 공식 소개 알려줘'):
            with self.subTest(query=query):
                item, = search_assistant(ROOT, query, include_route_restricted=True)
                self.assertEqual(item['id'], 'seongsan')
                self.assertEqual(item['name'], '성산일출봉')
                self.assertEqual(item['match_type'], 'exact_name')
                self.assertFalse(item['automatic_eligible'])
                self.assertFalse(item['current_opening_verified'])
                self.assertIn('entrance_required', {reason['code'] for reason in item['visit_restrictions']})
                self.assertEqual(item['official_intro']['date_kind'], 'guide_review')
                self.assertIn('분화구', item['official_intro']['text'])

    def test_official_alias_and_attached_request_suffix(self):
        alias, = search_assistant(ROOT, '넥슨뮤지엄', include_route_restricted=True)
        self.assertEqual(alias['name'], '넥슨컴퓨터박물관')
        self.assertEqual(alias['matched_evidence']['text'], '넥슨뮤지엄')
        self.assertEqual(alias['matched_evidence']['date_kind'], 'guide_review')
        exact, = search_assistant(ROOT, '용두암소개', include_route_restricted=True)
        self.assertEqual(exact['name'], '용두암')
        self.assertTrue(exact['automatic_eligible'])
        self.assertEqual(exact['visit_restrictions'], [])

    def test_restricted_places_only_appear_in_public_information_mode(self):
        for query, code in (('용머리해안', 'daily_coastal_control_unavailable'), ('우도', 'ferry_not_supported')):
            with self.subTest(query=query):
                self.assertEqual(search_assistant(ROOT, query), [])
                result, = search_assistant(ROOT, query, include_route_restricted=True)
                self.assertEqual(result['name'], query)
                self.assertFalse(result['automatic_eligible'])
                self.assertIn(code, {reason['code'] for reason in result['visit_restrictions']})

    def test_exact_place_with_unusable_guide_does_not_return_a_mention(self):
        for status in ('not_verified', 'review_overdue'):
            def trust_with_unusable_guide(root, item, **options):
                result = place_trust(root, item, **options)
                if item['id'] == 'seongsan':
                    result['checks']['official_guide']['status'] = status
                return result

            with self.subTest(status=status), patch('jeju_agent.assistant_search.place_trust', trust_with_unusable_guide):
                self.assertEqual(search_assistant(ROOT, '성산일출봉', include_route_restricted=True), [])

    def test_unverifiable_conditions_and_similar_but_distinct_titles(self):
        for query in ('성산일출봉 영업시간', '용두암 근처', '우도 빼고 바다 풍경'):
            with self.subTest(query=query):
                self.assertEqual(search_assistant(ROOT, query, include_route_restricted=True), [])
        results = search_assistant(ROOT, '사려니숲길', include_route_restricted=True)
        self.assertFalse(any(item['match_type'] == 'exact_name' and '입구' in item['name'] for item in results))


if __name__ == '__main__':
    unittest.main()
