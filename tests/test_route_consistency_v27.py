"""Use preserved public Jeju records and the same road snapshot as the planner."""
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from jeju_agent import roads
from jeju_agent.engine import _travel
from jeju_agent.orchestrator import run_agent
from jeju_agent.reference import plan_destinations
from jeju_agent.tourism_access import approved_places


ROOT = Path(__file__).resolve().parents[1]
AIRPORT = (33.506, 126.492)


def request(**changes):
    body = {'date': '2026-11-06', 'transport': 'car', 'start_lat': AIRPORT[0], 'start_lon': AIRPORT[1],
            'end_lat': AIRPORT[0], 'end_lon': AIRPORT[1], 'origin_confirmed': True, 'origin_source': 'landmark',
            'start_minute': 540, 'end_minute': 960, 'budget_krw': 100000, 'max_stops': 1,
            'query': '천지연폭포', 'region': 'south', 'excluded_ids': [], 'include_geometry': True}
    return dict(body, **changes)


class RouteConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.place = next(place for place in approved_places(ROOT) if place['name'] == '천지연폭포')

    def test_airport_round_trip_uses_one_map_for_road_distance_and_schedule(self):
        with patch.object(roads, 'route_geometry', wraps=roads.route_geometry) as geometry_call:
            result = run_agent(ROOT, request(), learned_search=False)
        geometry_call.assert_called_once()
        self.assertEqual(result['status'], 'ok')
        geometry = result['route_geometry']
        total = result['totals']
        self.assertEqual(geometry['kind'], 'road')
        self.assertEqual(result['travel_estimate']['basis'], 'osm_road_distance')
        self.assertEqual(geometry['distance_km'], total['travel_distance_km'])
        outbound, back = geometry['leg_distances_km']
        self.assertEqual(result['stops'][0]['travel_km'], round(outbound, 3))
        self.assertEqual(total['return_travel_km'], round(back, 3))
        self.assertEqual(total['travel_minutes'], sum(math.ceil(leg / 35 * 60) for leg in (outbound, back)))
        self.assertEqual(total['travel_cost_krw'], sum(math.ceil(leg * 250) for leg in (outbound, back)))
        self.assertEqual(total['end_arrival_minute'], result['stops'][0]['departure_minute'] + total['return_travel_minutes'])

    def test_road_recheck_catches_optimistic_deadline_and_budget_even_without_map(self):
        point = (self.place['latitude'], self.place['longitude'])
        minutes, cost, _ = _travel(AIRPORT, point, 'car')
        old_end = 540 + 2 * minutes + int(self.place.get('planning_stay_minutes', 90))
        tight = request(end_minute=old_end, budget_krw=2 * cost, include_geometry=False)
        for result in (run_agent(ROOT, tight, learned_search=False),
                       plan_destinations(ROOT, dict(tight, destination_ids=[self.place['id']]))):
            self.assertEqual(result['status'], 'infeasible')
            self.assertEqual(result['stops'], [])
            self.assertIsNone(result['route_geometry'])
            self.assertEqual(result['travel_estimate']['basis'], 'osm_road_distance')
            self.assertLess(result['constraint_check']['deadline_margin_minutes'], 0)
            self.assertLess(result['constraint_check']['budget_margin_krw'], 0)

    def test_missing_graph_marks_straight_line_fallback_and_estimated_margin(self):
        with patch.object(roads, '_graph', return_value=None):
            result = run_agent(ROOT, request(), learned_search=False)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['route_geometry']['kind'], 'straight_line')
        self.assertEqual(result['travel_estimate']['basis'], 'adjusted_straight_line')
        self.assertEqual(result['travel_estimate']['fallback_reason'], 'graph_unavailable')
        self.assertGreater(result['totals']['deadline_margin_minutes'], 0)
        self.assertTrue(any('직선거리' in warning for warning in result['warnings']))

    def test_direct_return_requires_public_origin_and_explicit_action(self):
        origin_id = self.place['id']
        base = request(origin_place_id=origin_id)
        base.pop('start_lat')
        base.pop('start_lon')
        normal = run_agent(ROOT, base, learned_search=False)
        self.assertEqual(normal['status'], 'infeasible')
        self.assertEqual(normal['selection_mode'], 'automatic')
        direct = dict(base, return_only=True, max_stops=0)
        result = run_agent(ROOT, direct, learned_search=False)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['selection_mode'], 'direct_return')
        self.assertEqual(result['stops'], [])
        self.assertEqual(result['request']['origin_place_id'], origin_id)
        self.assertEqual((result['request']['end_lat'], result['request']['end_lon']), AIRPORT)
        self.assertEqual(result['totals']['travel_distance_km'], result['route_geometry']['distance_km'])
        self.assertEqual(result['totals']['duration_minutes'], result['totals']['return_travel_minutes'])
        self.assertTrue(result['route_geometry']['contains_private_location'])

        failed = run_agent(ROOT, dict(direct, budget_krw=0), learned_search=False)
        self.assertEqual(failed['status'], 'infeasible')
        self.assertFalse(failed['constraint_check']['within_budget'])
        self.assertIsNone(failed['route_geometry'])
        with self.assertRaises(ValueError):
            run_agent(ROOT, dict(direct, origin_place_id='unknown'), learned_search=False)
        missing_budget = {key: value for key, value in direct.items() if key != 'budget_krw'}
        with self.assertRaises(ValueError):
            run_agent(ROOT, missing_budget, learned_search=False)


if __name__ == '__main__':
    unittest.main()
