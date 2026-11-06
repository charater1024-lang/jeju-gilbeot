"""Exercise source lookup with retired scoring paths unavailable."""
from pathlib import Path
import unittest
from unittest.mock import patch

from jeju_agent import discovery, tourism, travel_context


ROOT = Path(__file__).resolve().parents[1]


class ReferenceSearchV23Tests(unittest.TestCase):
    def test_tourism_keeps_verified_records_and_paginates_filtered_lookup(self):
        location = {'latitude': 33.514, 'longitude': 126.53}
        query = {'query': '해변', 'region': 'north', 'location': location,
                 'radius_km': 15, 'limit': 1}
        with patch.object(tourism, '_load_model', side_effect=AssertionError('retired TF-IDF')):
            result = tourism.search_tourism(ROOT, query, learned=False)
            second = tourism.search_tourism(ROOT, dict(query, cursor=result['next_cursor']), learned=False)
            exact = tourism.search_tourism(ROOT, {'query': '제주 민속촌'}, learned=False)
            no_match = tourism.search_tourism(ROOT, {'query': '해변 존재하지않는표식'}, learned=False)
        self.assertEqual('제주민속촌', exact['items'][0]['name'])
        self.assertEqual([], no_match['items'])
        self.assertTrue(result['radius_applied'])
        self.assertEqual(1, len(result['items']))
        self.assertEqual(1, len(second['items']))
        self.assertNotEqual(result['items'][0]['id'], second['items'][0]['id'])
        for item in result['items'] + second['items']:
            self.assertEqual('north', item['region'])
            self.assertLessEqual(item['distance_km'], 15)
            self.assertTrue(item['source_overlap_verified'])
            self.assertIsNone(item['similarity_score'])

    def test_food_keeps_position_and_address_separate(self):
        query = {'query': '갈치', 'region': 'north', 'radius_km': 12,
                 'location': {'latitude': 33.514, 'longitude': 126.53}}
        with patch.object(discovery, '_load_model', side_effect=AssertionError('retired TF-IDF')):
            result = discovery.discovery_recommend(ROOT, query, learned=False)
            no_match = discovery.discovery_recommend(
                ROOT, dict(query, query='갈치 존재하지않는표식'), learned=False)
        self.assertTrue(result['restaurants'])
        self.assertTrue(result['unmapped_restaurants'])
        self.assertFalse(no_match['restaurants'] or no_match['unmapped_restaurants'])
        for item in result['restaurants']:
            self.assertEqual('north', item['region'])
            self.assertTrue(item['within_radius'])
            self.assertIsNone(item['similarity_score'])
            self.assertFalse(item['menu_verified'] or item['current_opening_verified'])
        for item in result['unmapped_restaurants']:
            self.assertIsNone(item['distance_km'])
            self.assertIsNone(item['plan_place_id'])

    def test_travel_preserves_explicit_facilities_duration_and_limitations(self):
        with patch.object(travel_context, '_vector', side_effect=AssertionError('retired TF-IDF')):
            beach = travel_context.search_travel_context(ROOT, kind='beach', query='협재 화장실', learned=False)
            walk = travel_context.search_travel_context(ROOT, kind='walk', max_minutes=120, learned=False)
            unavailable = travel_context.search_travel_context(ROOT, kind='amenity', query='지금영업', learned=False)
        self.assertEqual(['화장실(동)'], beach['applied_facility_filters'])
        self.assertTrue(beach['items'] and walk['items'])
        self.assertTrue(all(row['max_minutes'] <= 120 for row in walk['items']))
        self.assertTrue(all(row['route_eligible'] is False for row in beach['items'] + walk['items']))
        self.assertEqual('unsupported', unavailable['status'])


if __name__ == '__main__':
    unittest.main()
