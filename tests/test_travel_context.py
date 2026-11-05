import json
from pathlib import Path
import unittest

from jeju_agent.travel_context import search_travel_context

ROOT = Path(__file__).resolve().parent.parent


class TravelContextTests(unittest.TestCase):
    def test_real_sources_and_all_results_are_reference_only(self):
        result = search_travel_context(ROOT, kind='walk', limit=20)
        self.assertEqual(result['available_counts']['walk'], 69)
        self.assertEqual(result['available_counts']['beach'], 11)
        self.assertGreater(result['model']['training_documents'], 2000)
        self.assertFalse(result['model']['runtime_llm'])
        self.assertFalse(result['model']['relevance_accuracy_evaluated'])
        self.assertTrue(all(item['route_eligible'] is False for item in result['items']))
        self.assertEqual(next(s for s in result['sources'] if s['id'] == 'hub871')['row_count'], 19)
        self.assertTrue(next(s for s in result['sources'] if s['id'] == 'hub871')['partial'])

    def test_provided_upper_duration_gate_does_not_guess_forest_times(self):
        result = search_travel_context(ROOT, kind='walk', query='2시간 안에 걷기 코스', max_minutes=120)
        self.assertGreater(len(result['items']), 0)
        self.assertTrue(all(item['source_id'] == 'hub871' and item['max_minutes'] <= 120 for item in result['items']))
        self.assertTrue(any('가파도' in item['name'] for item in result['items']))
        self.assertEqual(search_travel_context(ROOT, kind='walk', max_minutes=30)['items'], [])

    def test_forest_source_is_latest_original_not_old_hub_preview(self):
        result = search_travel_context(ROOT, kind='walk', query='송악산')
        self.assertEqual(result['items'][0]['source_date'], '2025-02-19')
        self.assertEqual(result['items'][0]['known']['거리(km)'], 1.2)
        self.assertNotIn('coordinates', result['items'][0])

    def test_beach_facilities_are_source_counts_not_live_availability(self):
        result = search_travel_context(ROOT, kind='beach', query='화장실 주차장 있는 해수욕장')
        self.assertTrue(result['items'])
        self.assertTrue(all(item['known']['화장실(동)'] > 0 and item['known']['주차규모(대)'] > 0 for item in result['items']))
        self.assertTrue(all(item['source_date'] == '2023-12-31' and not item['current_opening_verified'] for item in result['items']))
        self.assertEqual(search_travel_context(ROOT, kind='beach', query='실시간 주차가능')['status'], 'unsupported')
        self.assertEqual(search_travel_context(ROOT, kind='beach', query='주차장 없는 해변')['status'], 'unsupported')
        self.assertEqual(search_travel_context(ROOT, kind='walk', query='3시간 이상 올레')['status'], 'unsupported')
        self.assertEqual([s['id'] for s in result['sources']], ['hub784'])
        self.assertFalse(any('올레' in note for note in result['limitations']))

    def test_accessibility_is_listing_only_and_names_are_not_merged(self):
        result = search_travel_context(ROOT, kind='accessible', query='한림공원')
        self.assertGreaterEqual(len(result['items']), 2)
        self.assertTrue(all(item['source_date'] == '2021-09-30' for item in result['items']))
        self.assertTrue(all('현재 접근성 미확인' in item['known']['명부'] for item in result['items']))

    def test_village_amenities_remain_separate_public_source(self):
        result = search_travel_context(ROOT, kind='amenity', query='전기차충전소')
        self.assertTrue(result['items'])
        self.assertTrue(all(item['source_id'] == 'public15109369' for item in result['items']))
        self.assertTrue(all(item['source_date'] == '2022-09-30' for item in result['items']))
        self.assertTrue(all('운영시간' not in item['known'] for item in result['items']))
        self.assertEqual(search_travel_context(ROOT, kind='amenity', query='지금 충전가능')['status'], 'unsupported')
        self.assertTrue(all(item['name'].strip() for item in search_travel_context(ROOT, kind='amenity', limit=20)['items']))
        self.assertEqual([s['id'] for s in result['sources']], ['public15109369'])

    def test_unknown_query_and_input_validation(self):
        self.assertEqual(search_travel_context(ROOT, query='존재하지않는장소이름')['items'], [])
        for kwargs in ({'kind': 'fake'}, {'max_minutes': True}, {'max_minutes': float('nan')}, {'limit': True}, {'query': 'x'*161}, {'kind': 'beach', 'max_minutes': 30}):
            with self.assertRaises(ValueError):
                search_travel_context(ROOT, **kwargs)
        # Returned records are detached from the cached corpus.
        result = search_travel_context(ROOT, kind='beach', query='협재')
        result['items'][0]['name'] = 'changed'
        self.assertEqual(search_travel_context(ROOT, kind='beach', query='협재')['items'][0]['name'], '협재')


if __name__ == '__main__':
    unittest.main()
