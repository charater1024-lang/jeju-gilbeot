from pathlib import Path
import unittest

from jeju_agent.assistant_search import HUB_FOOD, HUB_PLACES, search_assistant
from jeju_agent.tourism_access import approved_places


ROOT = Path(__file__).resolve().parents[1]


class AssistantSearchTests(unittest.TestCase):
    def test_old_jeju_query_cites_reviewed_source_passages(self):
        candidates = {item['id']: item for item in approved_places(ROOT)}
        results = search_assistant(ROOT, '옛 제주 모습을 볼 만한 곳')
        self.assertTrue({'제주목관아', '제주민속촌', '성읍민속마을'} <= {item['name'] for item in results})
        for item in results:
            candidate = candidates[item['id']]
            self.assertEqual(item['name'], candidate['cross_source']['hub']['name'])
            self.assertEqual(item['primary_source']['url'], HUB_PLACES)
            self.assertTrue(item['automatic_eligible'])
            evidence = item['matched_evidence']
            self.assertIn(evidence['text'], candidate['tourism_guide']['summary'])
            self.assertEqual(evidence['source_url'], candidate['tourism_guide']['source_url'])
            self.assertEqual(evidence['retrieved_at'], candidate['tourism_guide']['retrieved_at'])
            self.assertTrue(evidence['matched_terms'])

    def test_tourism_search_respects_trust_and_region(self):
        self.assertEqual(search_assistant(ROOT, '우도'), [])
        self.assertEqual(search_assistant(ROOT, 'zxq장소없음'), [])
        self.assertEqual(search_assistant(ROOT, '제주목관아', region='east'), [])
        item, = search_assistant(ROOT, '제주목관아')
        self.assertEqual(item['matched_evidence']['source_url'], HUB_PLACES)

    def test_food_uses_only_the_hub_permit_source_and_labels_address_only(self):
        results = search_assistant(ROOT, '애월 카페 추천', kind='food', region='west')
        self.assertEqual(len(results), 5)
        for item in results:
            self.assertEqual(item['kind'], 'food')
            self.assertEqual(item['region'], 'west')
            self.assertEqual(item['primary_source']['url'], HUB_FOOD)
            self.assertEqual(item['matched_evidence']['source_url'], HUB_FOOD)
            self.assertIn('애월', item['address'])
            self.assertEqual(item['location_basis'], 'address_only')
            self.assertNotIn('latitude', item)
            self.assertFalse(item['automatic_eligible'])
            self.assertFalse(item['current_opening_verified'])

    def test_unsupported_conditions_are_not_silently_dropped(self):
        self.assertEqual(search_assistant(ROOT, '우도 빼고 바다 풍경'), [])
        self.assertEqual(search_assistant(ROOT, '지금 영업 중인 갈치 식당', kind='food'), [])

    def test_region_alias_does_not_become_a_literal_food_name_requirement(self):
        results = search_assistant(ROOT, '제주 서쪽 한식 식당 찾아줘', kind='food', region='west')
        self.assertEqual(len(results), 5)
        self.assertTrue(all(item['category'] == '한식' and item['region'] == 'west' for item in results))
        self.assertTrue(any('서쪽' not in item['name'] for item in results))
        exact, = search_assistant(ROOT, '서쪽밤', kind='food', region='west')
        self.assertEqual(exact['name'], '서쪽밤')

    def test_region_alias_and_natural_viewing_phrase_retrieve_grounded_places(self):
        results = search_assistant(ROOT, '제주 서쪽 박물관 찾아줘', region='west')
        self.assertIn('본태박물관', {item['name'] for item in results})
        self.assertTrue(all(item['region'] == 'west' for item in results))
        results = search_assistant(ROOT, '바다를 바라볼 수 있는 관광 명소 추천해줘')
        self.assertTrue(results)
        self.assertTrue(all('바다' in item['matched_evidence']['text'] for item in results))


if __name__ == '__main__':
    unittest.main()
