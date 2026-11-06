"""Public real-place records and temporary metadata copies only; never GPS."""
import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from jeju_agent.place_trust import GUIDE_PROOFS_PATH, place_trust, load_policy, TrustPolicyError
from jeju_agent.tourism_access import approved_places

ROOT=Path(__file__).resolve().parents[1]
AS_OF=date(2026,11,1)


class PlaceTrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.places={p['id']:p for p in approved_places(ROOT)}

    def trust(self,ident='hamdeok',**kwargs):
        return place_trust(ROOT,self.places[ident],as_of=AS_OF,**kwargs)

    def test_public_place_passes_with_unverified_fields_disclosed(self):
        result=self.trust()
        self.assertTrue(result['eligible']);self.assertTrue(result['automatic_eligible'])
        self.assertFalse(result['current_operation_verified'])
        for key in ['current_operation','entrance','opening_hours','fees']:
            self.assertEqual(result['checks'][key]['status'],'not_verified')
        self.assertEqual(result['checks']['official_guide']['retrieved_at'],'2026-10-29')
        self.assertEqual(result['policy_reviewed_at'],'2026-11-01')
        self.assertNotIn('confidence_percent',result)
        self.assertEqual({s['kind'] for s in result['sources']},{'map_record','hub_registry','tourism_guide'})
        self.assertTrue(any('수영' in warning for warning in result['warnings']))

    def test_known_controlled_place_is_conservatively_excluded(self):
        result=self.trust('osm_tourism_node_4832613086')
        self.assertFalse(result['automatic_eligible'])
        self.assertIn('recorded_access_control',{r['code'] for r in result['reasons']})
        self.assertIn('해제 여부',result['checks']['specific_review']['label'])

    def test_missing_official_guide_is_not_invented(self):
        result=self.trust('osm_tourism_way_597287359')
        self.assertFalse(result['eligible'])
        self.assertIn('official_guide_missing',{r['code'] for r in result['reasons']})

    def test_entrance_and_ferry_places_are_not_auto_selected(self):
        self.assertIn('entrance_required',{r['code'] for r in self.trust('seongsan')['reasons']})
        self.assertIn('ferry_not_supported',{r['code'] for r in self.trust('osm_tourism_relation_9742044')['reasons']})

    def test_verified_renaming_is_a_notice_not_an_identity_claim(self):
        result=self.trust('osm_tourism_way_375341085')
        self.assertTrue(result['automatic_eligible'])
        self.assertTrue(any('넥슨뮤지엄' in warning for warning in result['warnings']))

    def test_unverified_identity_and_coordinates_cannot_pass(self):
        item=copy.deepcopy(self.places['hamdeok']);item['latitude']+=0.01
        result=place_trust(ROOT,item,as_of=AS_OF)
        self.assertFalse(result['eligible'])
        item=copy.deepcopy(self.places['hamdeok']);item['latitude']=float('nan')
        self.assertFalse(place_trust(ROOT,item,as_of=AS_OF)['eligible'])

    def test_food_and_unapproved_map_records_never_become_attractions(self):
        for changed in [{'kind':'food'},{'source_overlap_verified':False},{'cross_source':None}]:
            item=dict(self.places['hamdeok'],**changed)
            self.assertFalse(place_trust(ROOT,item,as_of=AS_OF)['eligible'])

    def test_stale_and_future_source_dates_exclude(self):
        stale=place_trust(ROOT,self.places['hamdeok'],as_of=date(2027,12,1))
        self.assertFalse(stale['eligible'])
        self.assertEqual(stale['checks']['official_guide']['status'],'review_overdue')
        # The v16 contract rejects an entire policy reviewed after the as_of day.
        # A future guide with a valid policy date is covered separately in v16.
        with self.assertRaises(TrustPolicyError):
            place_trust(ROOT,self.places['hamdeok'],as_of=date(2026,10,1))

    def fixture(self,folder):
        root=Path(folder);(root/'config').mkdir();(root/'data_reference').mkdir()
        shutil.copy2(ROOT/'config/place_trust_policy_v15.json',root/'config/place_trust_policy_v15.json')
        shutil.copy2(ROOT/'data_reference/tourism_guides_v12.json',root/'data_reference/tourism_guides_v12.json')
        shutil.copy2(ROOT/GUIDE_PROOFS_PATH,root/GUIDE_PROOFS_PATH)
        return root

    def test_missing_or_corrupt_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(TrustPolicyError):load_policy(Path(temp))
            root=self.fixture(temp);path=root/'config/place_trust_policy_v15.json'
            path.write_text('{broken',encoding='utf-8')
            with self.assertRaises(TrustPolicyError):place_trust(root,self.places['hamdeok'],as_of=AS_OF)

    def test_unsupported_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=self.fixture(temp);path=root/'config/place_trust_policy_v15.json'
            data=json.loads(path.read_text(encoding='utf-8'));data['policy_id']='looser_unknown_policy'
            path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(TrustPolicyError):place_trust(root,self.places['hamdeok'],as_of=AS_OF)

    def test_compact_proof_supports_a_checkout_without_source_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root=self.fixture(temp)
            self.assertTrue(place_trust(root,self.places['hamdeok'],as_of=AS_OF)['eligible'])
            (root/GUIDE_PROOFS_PATH).write_text('{}',encoding='utf-8')
            result=place_trust(root,self.places['hamdeok'],as_of=AS_OF)
            self.assertFalse(result['eligible'])
            self.assertIn('source_receipt_changed',{r['code'] for r in result['reasons']})

    def test_changed_catalog_and_receipt_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=self.fixture(temp);cache=root/'data_raw/tourism/v12/official_fields/hamdeok.json'
            cache.parent.mkdir(parents=True)
            proof=json.loads((root/GUIDE_PROOFS_PATH).read_text(encoding='utf-8'))['hamdeok']
            original=json.dumps(proof).encode('utf-8')
            cache.write_bytes(original)
            policy_path=root/'config/place_trust_policy_v15.json'
            policy=json.loads(policy_path.read_text(encoding='utf-8'))
            policy['guide_records']['hamdeok']['cache_file_sha256']=hashlib.sha256(original).hexdigest()
            policy_path.write_text(json.dumps(policy),encoding='utf-8')
            self.assertTrue(place_trust(root,self.places['hamdeok'],as_of=AS_OF)['eligible'])
            cache.write_text('{}',encoding='utf-8')
            result=place_trust(root,self.places['hamdeok'],as_of=AS_OF)
            self.assertFalse(result['eligible'])
            self.assertIn('source_receipt_changed',{r['code'] for r in result['reasons']})
            catalog=root/'data_reference/tourism_guides_v12.json';catalog.write_text('{}',encoding='utf-8')
            result=place_trust(root,self.places['hamdeok'],as_of=AS_OF)
            self.assertIn('guide_catalog_changed',{r['code'] for r in result['reasons']})

    def test_manual_inspection_does_not_change_automatic_policy(self):
        result=self.trust('osm_tourism_node_4832613086',purpose='manual')
        self.assertTrue(result['eligible']);self.assertFalse(result['automatic_eligible'])
        with self.assertRaises(ValueError):self.trust(purpose='typo')


if __name__=='__main__':unittest.main()
