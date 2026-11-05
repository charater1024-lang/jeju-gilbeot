"""Real public-place orchestration fixtures; no device GPS or external network."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jeju_agent import orchestrator
from jeju_agent.tourism_access import approved_places

ROOT = Path(__file__).resolve().parents[1]


def request(**updates):
    body = {'date': '2026-11-01', 'transport': 'car', 'start_lat': 33.506,
            'start_lon': 126.492, 'end_lat': 33.506, 'end_lon': 126.492,
            'start_minute': 540, 'end_minute': 1080, 'budget_krw': 80000,
            'max_stops': 3, 'query': '', 'region': 'all', 'excluded_ids': [],
            'origin_confirmed': True, 'origin_source': 'landmark',
            'origin_label': '공개 기준점 제주공항', 'include_geometry': False}
    body.update(updates)
    return body


class OrchestratorTests(unittest.TestCase):
    def test_origin_must_be_explicitly_confirmed_and_inside_jeju(self):
        cases = [dict(origin_confirmed=False), dict(origin_confirmed=1),
                 dict(origin_source='unknown'), dict(start_lat=float('nan')),
                 dict(end_lon=float('inf')), dict(start_lat=37.5), dict(start_lat=True)]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                orchestrator.run_agent(ROOT, request(**changes))
        body=request();body.pop('start_lat')
        with self.assertRaises(ValueError):orchestrator.run_agent(ROOT, body)

    def test_invalid_filters_do_not_reach_search(self):
        for changes in [dict(query='x'*101), dict(region='seoul'), dict(excluded_ids='seongsan'),
                        dict(excluded_ids=[1]), dict(include_geometry='true')]:
            with self.subTest(changes=changes), patch.object(orchestrator,'search_tourism') as search:
                with self.assertRaises(ValueError):orchestrator.run_agent(ROOT,request(**changes))
                search.assert_not_called()

    def test_unsupported_bus_returns_clear_reason_before_retrieval(self):
        with patch.object(orchestrator,'search_tourism') as search:
            result=orchestrator.run_agent(ROOT,request(transport='bus'))
        self.assertEqual(result['status'],'unsupported');self.assertEqual(result['stops'],[])
        self.assertTrue(result['suggestions']);search.assert_not_called()

    def test_actual_auto_route_is_verified_and_satisfies_constraints(self):
        result=orchestrator.run_agent(ROOT,request())
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['data_mode'],'reference')
        self.assertEqual(result['selection_mode'],'automatic')
        self.assertTrue(1<=len(result['stops'])<=3)
        self.assertEqual(len({p['poi_id'] for p in result['stops']}),len(result['stops']))
        self.assertLessEqual(result['totals']['end_arrival_minute'],1080)
        self.assertLessEqual(result['totals']['travel_cost_krw'],80000)
        self.assertFalse(result['totals']['budget_verified'])
        self.assertFalse(result['orchestrator']['runtime_llm'])
        self.assertFalse(result['orchestrator']['popularity_or_personal_preference_model_used'])
        self.assertFalse(result['privacy']['precise_location_persisted'])
        for stop,evidence in zip(result['stops'],result['selected_place_evidence']):
            self.assertTrue(stop['source_overlap_verified'])
            self.assertTrue(stop['trust']['eligible'])
            self.assertTrue(stop['tourism_guide_available'])
            self.assertIsNone(stop['predicted_visits'])
            self.assertEqual(stop['poi_id'],evidence['id'])
        names=[step['agent'] for step in result['trace']]
        self.assertIn('출처와 방문 조건 검사',names)
        self.assertIn('일정과 복귀 재검사',names)
        self.assertIn('로컬 지도 연결',names)

    def test_repeated_requests_stable_and_user_exclusion_replans(self):
        first=orchestrator.run_agent(ROOT,request())
        repeat=orchestrator.run_agent(ROOT,request())
        self.assertEqual([p['poi_id'] for p in first['stops']],[p['poi_id'] for p in repeat['stops']])
        excluded=first['stops'][0]['poi_id']
        next_result=orchestrator.run_agent(ROOT,request(excluded_ids=[excluded]))
        self.assertEqual(next_result['status'],'ok')
        self.assertNotIn(excluded,[p['poi_id'] for p in next_result['stops']])
        self.assertTrue(any(item['id']==excluded and item['reasons'][0]['code']=='user_excluded'
                            for item in next_result['exclusions']))

    def test_unmatched_query_never_silently_falls_back(self):
        result=orchestrator.run_agent(ROOT,request(query='zxqv987654'))
        self.assertEqual(result['status'],'infeasible')
        self.assertEqual(result['stops'],[])
        self.assertEqual(result['selection_statistics']['matched_candidates'],0)
        self.assertTrue(result['suggestions'])

    def test_character_overlap_does_not_manufacture_a_semantic_theme(self):
        result=orchestrator.run_agent(ROOT,request(query='존재하지않는관광지xyz987'))
        self.assertEqual(result['status'],'infeasible')
        self.assertEqual(result['selection_statistics']['policy_eligible'],0)
        self.assertTrue(any(p['reasons'][0]['code']=='query_not_grounded' for p in result['exclusions']))

    def test_budget_and_time_failures_are_not_successful_routes(self):
        for changes in [dict(end_minute=545),dict(budget_krw=0)]:
            with self.subTest(changes=changes):
                result=orchestrator.run_agent(ROOT,request(**changes))
                self.assertEqual(result['status'],'infeasible')
                self.assertEqual(result['stops'],[])
                self.assertTrue(result['suggestions'])

    def test_policy_denials_are_preserved_not_bypassed(self):
        from jeju_agent import place_trust
        denied={'eligible':False,'reasons':[{'code':'fixture_denial','message':'test-only denial'}]}
        with patch.object(place_trust,'place_trust',return_value=denied):
            result=orchestrator.run_agent(ROOT,request())
        self.assertEqual(result['status'],'infeasible')
        self.assertEqual(result['selection_statistics']['policy_eligible'],0)
        self.assertTrue(result['exclusions'])
        self.assertTrue(all(p['reasons'][0]['code']=='fixture_denial' for p in result['exclusions']))

    def test_policy_loading_failure_fails_closed(self):
        from jeju_agent import place_trust
        with patch.object(place_trust,'place_trust',side_effect=place_trust.TrustPolicyError('unavailable policy')):
            with self.assertRaises(place_trust.TrustPolicyError):
                orchestrator.run_agent(ROOT,request())

    def test_trace_never_contains_coordinates_or_private_origin_label(self):
        result=orchestrator.run_agent(ROOT,request(origin_label='PRIVATE ORIGIN DO NOT LOG',unused_secret='not reflected'))
        encoded=' '.join(step['agent']+' '+step['detail'] for step in result['trace'])
        for secret in ['33.506','126.492','PRIVATE ORIGIN','not reflected']:
            self.assertNotIn(secret,encoded)
        self.assertNotIn('unused_secret',result['request'])
        self.assertFalse(result['privacy']['trace_contains_precise_location'])

    def test_real_regions_return_only_requested_region(self):
        fixtures=[('west',33.394,126.239),('south',33.247,126.554),('east',33.425,126.929)]
        actual={p['id']:p for p in approved_places(ROOT)}
        for region,lat,lon in fixtures:
            with self.subTest(region=region):
                result=orchestrator.run_agent(ROOT,request(region=region,start_lat=lat,start_lon=lon,end_lat=lat,end_lon=lon))
                self.assertEqual(result['status'],'ok')
                self.assertTrue(all(actual[stop['poi_id']]['region']==region for stop in result['stops']))

    def test_missing_road_graph_leaves_explicit_schedule_only(self):
        from jeju_agent import roads
        with patch.object(roads,'route_geometry',side_effect=FileNotFoundError('missing local graph')):
            result=orchestrator.run_agent(ROOT,request(include_geometry=True))
        self.assertEqual(result['status'],'ok')
        self.assertIsNone(result['route_geometry'])
        self.assertTrue(any('도로 연결' in warning for warning in result['warnings']))
        self.assertEqual(next(t['status'] for t in result['trace'] if t['agent']=='로컬 지도 연결'),'unavailable')


if __name__=='__main__':unittest.main()
