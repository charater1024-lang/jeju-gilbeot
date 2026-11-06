"""Extreme itinerary inputs and reproducible cases from the preserved Jeju road data."""

from datetime import date
from math import ceil
from pathlib import Path
import unittest
from unittest.mock import patch

from jeju_agent import place_trust, roads
from jeju_agent.orchestrator import run_agent
from jeju_agent.reference import plan_destinations
from jeju_agent.tourism_access import approved_places


ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 11, 6)
AIRPORT = (33.506, 126.492)
NEAR_AIRPORT = (
    'osm_tourism_way_1563942072',   # 어영공원
    'osm_tourism_node_538148519',   # 용두암
    'osm_tourism_way_1537196430',   # 제주목관아
    'osm_tourism_way_375341085',    # 넥슨컴퓨터박물관
    'osm_tourism_way_372701554',    # 수목원테마파크
    'osm_tourism_way_372948141',    # 탑동광장
    'osm_tourism_node_368866237',   # 한라수목원
    'osm_tourism_node_13931773845', # 제주 민속자연사박물관
    'osm_tourism_way_289861442',    # 이호테우해변
)
NINE_ROAD_WITNESS = (4, 6, 3, 8, 0, 1, 2, 5, 7)
CHECK_REAL_TRUST = place_trust.place_trust


def request(ids, **changes):
    body = {
        'date': AS_OF.isoformat(),
        'transport': 'car',
        'origin_confirmed': True,
        'origin_source': 'landmark',
        'origin_label': '제주공항',
        'start_lat': AIRPORT[0],
        'start_lon': AIRPORT[1],
        'end_lat': AIRPORT[0],
        'end_lon': AIRPORT[1],
        'start_minute': 360,
        'end_minute': 1440,
        'budget_krw': 100000,
        'max_stops': 'all',
        'destination_ids': list(ids),
    }
    return dict(body, **changes)


def road_request(ids, transport='car'):
    airport = {'latitude': AIRPORT[0], 'longitude': AIRPORT[1]}
    return {
        'destination_ids': list(ids),
        'transport': transport,
        'origin': airport,
        'destination': airport,
    }


def trust_at_snapshot(root, item, purpose='automatic'):
    return CHECK_REAL_TRUST(root, item, purpose=purpose, as_of=AS_OF)


class ItineraryStressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.places = {place['id']: place for place in approved_places(ROOT)}
        cls.eligible = [
            place_id for place_id, place in cls.places.items()
            if trust_at_snapshot(ROOT, place)['automatic_eligible']
        ]
        if not set(NEAR_AIRPORT).issubset(cls.eligible) or len(cls.eligible) < 25:
            raise AssertionError('The preserved real-place cohort is missing.')

    def setUp(self):
        guard = patch.object(place_trust, 'place_trust', side_effect=trust_at_snapshot)
        guard.start()
        self.addCleanup(guard.stop)

    def road_requirements(self, ordered_ids):
        geometry = roads.route_geometry(ROOT, road_request(ordered_ids))
        self.assertEqual(geometry['kind'], 'road')
        distances = geometry['leg_distances_km']
        self.assertEqual(len(distances), len(ordered_ids) + 1)
        travel_minutes = sum(ceil(distance / 35 * 60) for distance in distances)
        budget = sum(ceil(distance * 250) for distance in distances)
        stay_minutes = sum(self.places[place_id].get('planning_stay_minutes', 90) for place_id in ordered_ids)
        return 360 + stay_minutes + travel_minutes, budget

    def test_manual_validates_zero_eight_nine_twenty_four_and_twenty_five_stops(self):
        with self.assertRaises(ValueError):
            plan_destinations(ROOT, request([]))
        for count, limit in ((1, 1), (8, 8), (9, 'all')):
            with self.subTest(count=count, limit=limit):
                ids = NEAR_AIRPORT[:count]
                plan = plan_destinations(ROOT, request(ids, max_stops=limit))
                self.assertEqual(plan['status'], 'ok')
                self.assertEqual(plan['request']['destination_ids'], list(ids))
                self.assertCountEqual([stop['poi_id'] for stop in plan['stops']], ids)
                self.assertEqual(len(plan['route_geometry']['leg_distances_km']), count + 1)
        with self.assertRaises(ValueError):
            plan_destinations(ROOT, request(NEAR_AIRPORT, max_stops=8))

        ids = self.eligible[:24]
        result = plan_destinations(ROOT, request(ids, start_minute=0, budget_krw=10_000_000))
        self.assertEqual(result['status'], 'infeasible')
        self.assertEqual(result['request']['destination_ids'], ids)
        self.assertEqual(len(result['selected_place_evidence']), 24)
        self.assertEqual(result['stops'], [])
        self.assertIsNone(result['route_geometry'])
        with self.assertRaises(ValueError):
            plan_destinations(ROOT, request(self.eligible[:25]))

    def test_route_geometry_handles_24_places_and_rejects_the_25th(self):
        ids = self.eligible[:24]
        geometry = roads.route_geometry(ROOT, road_request(ids, transport='walk'))
        self.assertEqual(geometry['kind'], 'straight_line')
        self.assertEqual([place['id'] for place in geometry['stops']], ids)
        self.assertEqual(len(geometry['coordinates']), 26)  # airport plus return
        with self.assertRaises(ValueError):
            roads.route_geometry(ROOT, road_request(self.eligible[:25], transport='walk'))

    def test_literal_and_source_alias_duplicates_are_rejected_in_both_endpoints(self):
        canonical = 'hamdeok'
        sources = self.places[canonical]['cross_source']
        for repeated in (canonical, sources['hub']['id'], sources['osm']['id']):
            with self.subTest(repeated=repeated):
                ids = (canonical, repeated)
                with self.assertRaises(ValueError):
                    plan_destinations(ROOT, request(ids))
                with self.assertRaises(ValueError):
                    roads.route_geometry(ROOT, road_request(ids))

    def test_unknown_last_id_and_non_list_selection_never_generate_a_partial_trip(self):
        for ids in ((None,), ({'id': NEAR_AIRPORT[0]},), ('not-a-jeju-place',)):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    plan_destinations(ROOT, request(NEAR_AIRPORT + ids))
                with self.assertRaises(ValueError):
                    roads.route_geometry(ROOT, road_request(NEAR_AIRPORT + ids))
        with self.assertRaises(ValueError):
            plan_destinations(ROOT, request([], destination_ids='hamdeok'))

    def test_review_required_places_at_the_end_block_all_24_selections(self):
        ids = self.eligible[:22] + ['seongsan', 'osm_tourism_node_4832613086']
        result = plan_destinations(ROOT, request(ids))
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['request']['destination_ids'], ids)
        self.assertEqual(len(result['selected_place_evidence']), 24)
        self.assertEqual(result['stops'], [])
        self.assertIsNone(result['route_geometry'])
        reasons = {item['id']: {r['code'] for r in item['reasons']} for item in result['exclusions']}
        self.assertIn('entrance_required', reasons['seongsan'])
        self.assertIn('recorded_access_control', reasons['osm_tourism_node_4832613086'])

    def test_deadline_and_budget_are_inclusive_and_rechecked_without_geometry(self):
        ids = NEAR_AIRPORT[:1]
        deadline, budget = self.road_requirements(ids)
        exact = request(ids, end_minute=deadline, budget_krw=budget, include_geometry=False)
        passed = plan_destinations(ROOT, exact)
        self.assertEqual(passed['status'], 'ok')
        self.assertIsNone(passed['route_geometry'])
        self.assertEqual(passed['constraint_check']['deadline_margin_minutes'], 0)
        self.assertEqual(passed['constraint_check']['budget_margin_krw'], 0)
        for change, margin in (
            ({'end_minute': deadline - 1}, 'deadline_margin_minutes'),
            ({'budget_krw': budget - 1}, 'budget_margin_krw'),
        ):
            with self.subTest(change=change):
                result = plan_destinations(ROOT, dict(exact, **change))
                self.assertEqual(result['status'], 'infeasible')
                self.assertEqual(result['constraint_check'][margin], -1)
                self.assertEqual(result['stops'], [])

    def test_walking_zero_budget_bus_unavailable_and_invalid_day_edges(self):
        ids = NEAR_AIRPORT[:1]
        walking = plan_destinations(ROOT, request(ids, transport='walk', budget_krw=0))
        self.assertEqual(walking['status'], 'ok')
        self.assertEqual(walking['totals']['travel_cost_krw'], 0)
        bus = plan_destinations(ROOT, request(ids, transport='bus'))
        self.assertEqual(bus['status'], 'unsupported')
        self.assertEqual(bus['stops'], [])
        for change in (
            {'start_minute': -1}, {'end_minute': 1441}, {'start_minute': 720, 'end_minute': 720},
            {'budget_krw': -1}, {'budget_krw': 10_000_001}, {'budget_krw': 1.1},
            {'date': '2026-02-29'}, {'origin_confirmed': False}, {'start_lat': float('nan')},
            {'end_lon': 127.06}, {'include_geometry': 1},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    plan_destinations(ROOT, request(ids, **change))

    def test_automatic_numeric_stop_cap_and_exclusion_do_not_reuse_manual_all(self):
        body = request([], query='용두암', region='north', max_stops=8)
        result = run_agent(ROOT, body, learned_search=False)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([stop['poi_id'] for stop in result['stops']], [NEAR_AIRPORT[1]])
        blocked = run_agent(ROOT, dict(body, excluded_ids=[NEAR_AIRPORT[1]]), learned_search=False)
        self.assertEqual(blocked['status'], 'infeasible')
        self.assertEqual(blocked['stops'], [])
        for limit in ('all', 0, 9):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    run_agent(ROOT, dict(body, max_stops=limit), learned_search=False)

    def test_one_stop_uses_road_budget_and_deadline_in_manual_and_automatic(self):
        ids = NEAR_AIRPORT[2:3]  # 제주목관아
        deadline, budget = self.road_requirements(ids)
        exact = request(ids, end_minute=deadline, budget_krw=budget, max_stops=1)
        automatic = dict(exact, query='제주목관아', region='north')
        for result in (plan_destinations(ROOT, exact), run_agent(ROOT, automatic, learned_search=False)):
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['constraint_check']['deadline_margin_minutes'], 0)
            self.assertEqual(result['constraint_check']['budget_margin_krw'], 0)
            self.assertEqual(result['stops'][0]['poi_id'], ids[0])

    def test_two_stop_feasibility_is_independent_of_saved_order(self):
        ids = NEAR_AIRPORT[:2]  # 어영공원, 용두암
        deadline, _ = self.road_requirements(ids[::-1])
        outcomes = [plan_destinations(ROOT, request(order, end_minute=deadline))
                    for order in (ids, ids[::-1])]
        for result in outcomes:
            self.assertEqual(result['status'], 'ok')
            self.assertLessEqual(result['totals']['end_arrival_minute'], deadline)
        self.assertEqual([stop['poi_id'] for stop in outcomes[0]['stops']],
                         [stop['poi_id'] for stop in outcomes[1]['stops']])

    def test_all_nine_use_a_road_verified_order_when_approximate_order_fails(self):
        witness = tuple(NEAR_AIRPORT[index] for index in NINE_ROAD_WITNESS)
        deadline, _ = self.road_requirements(witness)
        result = plan_destinations(ROOT, request(NEAR_AIRPORT, end_minute=deadline))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['travel_estimate']['basis'], 'osm_road_distance')
        self.assertCountEqual([stop['poi_id'] for stop in result['stops']], NEAR_AIRPORT)
        self.assertLessEqual(result['totals']['end_arrival_minute'], deadline)

    def test_extreme_manual_budget_fails_input_validation(self):
        with self.assertRaises(ValueError):
            plan_destinations(ROOT, request(NEAR_AIRPORT[:1], budget_krw=10**309))

    def test_map_reference_preserves_recorded_visit_review_and_source(self):
        ids = ('osm_tourism_node_4832613086', 'osm_tourism_way_583831951')
        result = roads.route_geometry(ROOT, road_request(ids, transport='walk'))
        self.assertEqual([place['id'] for place in result['stops']], list(ids))
        reviews = result['visit_reviews']
        self.assertEqual([item['code'] for item in reviews],
                         ['recorded_access_control', 'recorded_beach_closure'])
        for review in reviews:
            self.assertFalse(review['current_operation_verified'])
            self.assertTrue(review['source_url'].startswith('https://'))
            self.assertTrue(any(review['reason'] in warning for warning in result['warnings']))

    def test_extreme_map_coordinate_fails_input_validation(self):
        body = road_request(NEAR_AIRPORT[:1])
        body['origin'] = {'latitude': 10**309, 'longitude': AIRPORT[1]}
        with self.assertRaises(ValueError):
            roads.route_geometry(ROOT, body)


if __name__ == '__main__':
    unittest.main()

