"""Hub display names must not change matching, coordinates, or source evidence."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from jeju_agent.chatbot import _facts, _read
from jeju_agent.tourism_names import prefer_hub_name
from jeju_agent.tourism_overlap import match_candidates
from jeju_agent.tourism import search_tourism, resolve_tourism_place
from jeju_agent.tourism_access import approved_places, place_search
from jeju_agent.place_details import place_details
from jeju_agent.reference import catalogue, plan_destinations
from jeju_agent.roads import route_geometry
from jeju_agent.chatbot import chat_reply

ROOT = Path(__file__).resolve().parents[1]


class HubNamePriorityTests(unittest.TestCase):
    def place(self):
        return {'id': 'approved', 'name': '지도 해수욕장', 'kind': 'attraction',
                'latitude': 33.5, 'longitude': 126.5, 'description': '원본 지도 메모',
                'source_url': 'https://www.openstreetmap.org/node/1',
                'source_overlap_verified': True,
                'cross_source': {'hub': {'id': 'hub1349_1', 'name': '지도해수욕장'},
                                 'osm': {'id': 'osm_tourism_node_1', 'name': '지도 해수욕장'}}}

    def test_hub_name_wins_and_original_evidence_stays_intact(self):
        original = self.place(); before = copy.deepcopy(original)
        result = prefer_hub_name(original)
        self.assertEqual(result['name'], '지도해수욕장')
        self.assertEqual(result['map_name'], before['name'])
        self.assertEqual(result['display_name_source'], 'jejudatahub')
        for key in ['id', 'latitude', 'longitude', 'description', 'source_url', 'cross_source']:
            self.assertEqual(result[key], before[key])
        self.assertEqual(original, before)
        self.assertEqual(prefer_hub_name(result), result)

    def test_unverified_or_empty_hub_name_keeps_existing_name(self):
        for name in [None, '', '  ', 123]:
            place = self.place(); place['cross_source']['hub']['name'] = name
            self.assertEqual(prefer_hub_name(place), place)
        for verified in [False, None]:
            place = dict(self.place(), source_overlap_verified=verified)
            self.assertEqual(prefer_hub_name(place), place)
        self.assertEqual(prefer_hub_name({'id': 'food_1', 'name': '식당'}), {'id': 'food_1', 'name': '식당'})

    def test_hub_priority_after_matching_does_not_relax_candidate_policy(self):
        policy = json.loads((ROOT/'config/tourism_overlap_policy.json').read_text(encoding='utf-8'))
        mapped = {'id': 'osm_tourism_node_1', 'name': 'Ａ 해수욕장', 'latitude': 33.5,
                  'longitude': 126.5, 'category': '해변', 'observed_tags': {'natural': 'beach'}}
        hub = {'id': 'hub1349_1', 'name': 'a해수욕장', 'latitude': 33.5001,
               'longitude': 126.5001, 'source_url': 'https://www.jejudatahub.net/data/view/data/1349'}
        rows, aliases, _ = match_candidates([mapped], [hub], [], policy)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], hub['name'])
        self.assertEqual(rows[0]['cross_source']['osm']['name'], mapped['name'])
        self.assertEqual(rows[0]['latitude'], mapped['latitude'])
        self.assertEqual(aliases[hub['id']], mapped['id'])
        self.assertEqual(match_candidates([mapped], [dict(hub, name='완전히다른장소')], [], policy)[0], [])
        self.assertEqual(match_candidates([mapped], [dict(hub, latitude=33.6)], [], policy)[0], [])

    def test_prepared_chat_text_uses_hub_name_but_keeps_source_field_values(self):
        scratch = ROOT/'.test_tmp'; scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            root = Path(temp); (root/'data_reference').mkdir()
            place = self.place(); place['address'] = '지도 해수욕장로 1'
            with closing(sqlite3.connect(root/'data_reference/chatbot.sqlite')) as db:
                db.execute('CREATE TABLE answers(id TEXT, data_json TEXT, prepared_text TEXT)')
                db.execute('INSERT INTO answers VALUES(?,?,?)', (place['id'], json.dumps(place, ensure_ascii=False), _facts(place)))
                db.commit()
            item, text = _read(root, place['id'])
            self.assertEqual(item['name'], '지도해수욕장')
            self.assertTrue(text.startswith('지도해수욕장의 원자료 분류는'))
            self.assertIn('기록 주소: 지도 해수욕장로 1', text)


class HubNameServingTests(unittest.TestCase):
    def assert_hub_names(self, items):
        self.assertTrue(items)
        for item in items:
            self.assertEqual(item['name'], item['cross_source']['hub']['name'].strip())
            self.assertEqual(item['map_name'], item['cross_source']['osm']['name'])

    def test_catalogue_and_all_search_results_use_hub_names(self):
        self.assert_hub_names(approved_places(ROOT))
        self.assert_hub_names(catalogue(ROOT)['items'])
        results = search_tourism(ROOT, {'limit': 100})
        self.assertEqual(results['total'], 68)
        self.assert_hub_names(results['items'])
        self.assertEqual(place_search(ROOT, '협재 해수욕장')['items'][0]['name'], '협재해수욕장')
        self.assertEqual(place_search(ROOT, '협재해수욕장')['items'][0]['name'], '협재해수욕장')

    def test_map_and_hub_alias_details_resolve_same_hub_name(self):
        for item in approved_places(ROOT):
            for ident in [item['id'], item['cross_source']['hub']['id'], item['cross_source']['osm']['id']]:
                result = resolve_tourism_place(ROOT, ident)
                self.assertEqual(result['id'], item['id'])
                self.assertEqual(result['name'], item['name'])
            self.assert_hub_names([place_details(ROOT, item['id'])['item']])

    def test_chat_cards_and_prepared_reply_use_same_hub_name(self):
        result = chat_reply(ROOT, {'message': '오설록 정보'})
        self.assert_hub_names(result['cards'])
        self.assertIn('오설록 티뮤지엄의 원자료 분류는', result['reply'])
        self.assertNotIn('오설록티뮤지엄의 원자료 분류는', result['reply'])

    def test_route_and_itinerary_use_hub_name(self):
        route = route_geometry(ROOT, {'destination_ids': ['osulloc'], 'transport': 'car', 'kind': 'straight_line'})
        self.assert_hub_names(route['stops'])
        planned = plan_destinations(ROOT, {'date': '2026-10-29', 'transport': 'car',
            'start_lat': 33.506, 'start_lon': 126.492, 'end_lat': 33.506, 'end_lon': 126.492,
            'start_minute': 540, 'end_minute': 1200, 'budget_krw': 100000, 'max_stops': 1,
            'interests': [], 'avoid_crowds': False, 'destination_ids': ['osulloc'],
            'origin_confirmed': True, 'origin_source': 'landmark', 'origin_label': '공개 기준점 제주공항'})
        self.assertEqual(planned['status'], 'ok')
        self.assertEqual(planned['stops'][0]['name'], '오설록 티뮤지엄')


if __name__ == '__main__':
    unittest.main()
