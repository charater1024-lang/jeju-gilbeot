"""Real-source manual schedule checks; no real GPS or runtime network access."""
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from jeju_agent import place_trust as trust_module
from jeju_agent.reference import plan_destinations
from jeju_agent.tourism_access import approved_places, resolve_trip_place

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 11, 3)
REAL_TRUST = trust_module.place_trust


def frozen_trust(root, item, purpose='automatic', **kwargs):
    return REAL_TRUST(root, item, purpose=purpose, as_of=AS_OF)


def request(ids, **updates):
    body = {'date':'2026-11-03','transport':'car','start_lat':33.506,
            'start_lon':126.492,'end_lat':33.506,'end_lon':126.492,
            'start_minute':540,'end_minute':1200,'budget_krw':100000,
            'max_stops':max(1,len(ids)),'destination_ids':ids,
            'origin_confirmed':True,'origin_source':'landmark','origin_label':'공개 기준점 제주공항'}
    body.update(updates)
    return body


class ManualTrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.places = {p['id']:p for p in approved_places(ROOT)}
        cls.policy = trust_module.load_policy(ROOT)
        cls.eligible = [p for p in cls.places.values()
                        if frozen_trust(ROOT,p)['automatic_eligible']]
        if len(cls.places) != 68 or len(cls.eligible) != 40:
            raise AssertionError('Expected preserved real v15 source cohort as of 2026-11-03')
        cls.safe = cls.eligible[0]
        with closing(sqlite3.connect((ROOT/'data_reference/discovery.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as db:
            food_ids = [row[0] for row in db.execute("SELECT id FROM restaurants WHERE id LIKE 'osm_%' AND latitude IS NOT NULL AND longitude IS NOT NULL ORDER BY id LIMIT 100")]
        cls.food = next(p for ident in food_ids
                        if (p:=resolve_trip_place(ROOT,ident)) and p.get('kind')=='food'
                        and not p.get('requires_ferry') and not p.get('requires_access_point'))

    def setUp(self):
        guard=patch.object(trust_module,'place_trust',side_effect=frozen_trust)
        guard.start();self.addCleanup(guard.stop)

    def test_all_ten_recorded_exceptions_require_review_and_keep_evidence(self):
        exceptions=self.policy['automatic_exclusions']
        self.assertEqual(len(exceptions),10)
        for ident, rule in exceptions.items():
            with self.subTest(place=self.places[ident]['name']):
                result=plan_destinations(ROOT,request([ident]))
                self.assertEqual(result['status'],'needs_review')
                self.assertIn(self.places[ident]['name'],result['message'])
                self.assertIn('출처·방문 조건을 먼저 확인',result['message'])
                self.assertEqual(result['stops'],[])
                self.assertEqual(result['totals'],{})
                self.assertEqual(result['request']['destination_ids'],[ident])
                exclusion=result['exclusions'][0]
                self.assertEqual(exclusion['id'],ident)
                self.assertIn(rule['code'],[r['code'] for r in exclusion['reasons']])
                self.assertTrue(exclusion['trust']['sources'])
                self.assertTrue(any(s.get('checked_at') for s in exclusion['trust']['sources']))
                self.assertEqual(result['selected_place_evidence'][0]['id'],ident)
                self.assertTrue(result['suggestions'])

    def test_access_control_coast_closure_and_construction_are_not_ok_routes(self):
        ids=['osm_tourism_node_4832613086','osm_tourism_node_3741616919',
             'osm_tourism_way_583831951','osm_tourism_way_375049062']
        for ident in ids:
            with self.subTest(ident=ident):
                result=plan_destinations(ROOT,request([ident]))
                self.assertEqual(result['status'],'needs_review')
                self.assertEqual(result['stops'],[])
                self.assertTrue(result['exclusions'][0]['reasons'])

    def test_every_eligible_real_place_keeps_trust_in_a_normal_schedule(self):
        for place in self.eligible:
            with self.subTest(place=place['name']):
                result=plan_destinations(ROOT,request([place['id']]))
                self.assertEqual(result['status'],'ok')
                self.assertEqual(len(result['stops']),1)
                stop=result['stops'][0]
                self.assertEqual(stop['poi_id'],place['id'])
                self.assertTrue(stop['trust']['eligible'])
                self.assertTrue(stop['trust']['automatic_eligible'])
                self.assertEqual(stop['trust']['purpose'],'manual')
                self.assertFalse(stop['trust']['current_operation_verified'])
                self.assertTrue(stop['trust']['sources'])
                self.assertEqual(stop['trust_scope'],'tourism_source_and_access_policy')
                self.assertFalse(result['totals']['budget_verified'])

    def test_a_blocked_place_stops_whole_request_without_silent_drop(self):
        ids=[self.safe['id'],'osm_tourism_node_4832613086']
        result=plan_destinations(ROOT,request(ids))
        self.assertEqual(result['status'],'needs_review')
        self.assertEqual(result['stops'],[])
        self.assertEqual(result['request']['destination_ids'],ids)
        self.assertEqual({p['id'] for p in result['selected_place_evidence']},set(ids))
        self.assertEqual([p['id'] for p in result['exclusions']],[ids[1]])

    def test_invalid_source_receipt_cannot_become_a_successful_manual_schedule(self):
        with patch.object(trust_module,'_guide',return_value=(None,'source_receipt_changed')):
            result=plan_destinations(ROOT,request([self.safe['id']]))
        self.assertEqual(result['status'],'needs_review')
        self.assertEqual(result['stops'],[])
        self.assertIn('source_receipt_changed',[r['code'] for r in result['exclusions'][0]['reasons']])
        self.assertEqual(result['exclusions'][0]['trust']['checks']['official_guide']['status'],'not_verified')

    def test_missing_and_corrupt_policy_raise_instead_of_generating_a_schedule(self):
        # Use an actual real place with an isolated unavailable policy root.
        with tempfile.TemporaryDirectory(prefix='jeju_reference_v16_') as directory:
            root=Path(directory)
            with patch('jeju_agent.reference.catalogue',return_value={'items':[self.safe]}):
                with self.assertRaises(trust_module.TrustPolicyError):
                    plan_destinations(root,request([self.safe['id']]))
                (root/'config').mkdir()
                (root/'config/place_trust_policy_v15.json').write_text('{',encoding='utf-8')
                with self.assertRaises(trust_module.TrustPolicyError):
                    plan_destinations(root,request([self.safe['id']]))

    def test_real_food_reference_remains_available_without_tourism_claim(self):
        with patch.object(trust_module,'place_trust',side_effect=AssertionError('Food must not use tourism policy')):
            result=plan_destinations(ROOT,request([self.food['id']]))
        self.assertEqual(result['status'],'ok')
        stop=result['stops'][0]
        self.assertEqual(stop['kind'],'food')
        self.assertFalse(stop['source_overlap_verified'])
        self.assertFalse(stop['tourism_policy_applied'])
        self.assertEqual(stop['trust_scope'],'food_reference_not_tourism_policy')
        self.assertNotIn('trust',stop)
        self.assertIn('관광지 신뢰정책 검사 대상이 아닙니다',stop['source_scope_note'])
        evidence=result['selected_place_evidence'][0]
        self.assertFalse(evidence['tourism_policy_applied'])
        self.assertFalse(evidence['current_operation_verified'])
        self.assertEqual(evidence['sources'][0]['url'],self.food['source_url'])
        self.assertTrue(any('음식점' in warning for warning in result['warnings']))

    def test_mixed_food_and_tourism_schedule_retains_both_source_scopes(self):
        ids=[self.safe['id'],self.food['id']]
        result=plan_destinations(ROOT,request(ids))
        self.assertEqual(result['status'],'ok')
        self.assertEqual({p['poi_id'] for p in result['stops']},set(ids))
        self.assertEqual({p['trust_scope'] for p in result['stops']},
                         {'tourism_source_and_access_policy','food_reference_not_tourism_policy'})
        self.assertEqual(len(result['selected_place_evidence']),2)


if __name__=='__main__':
    unittest.main()
