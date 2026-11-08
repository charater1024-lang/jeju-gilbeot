"""Request snapshots stay fresh across calls and never relax source checks."""
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from jeju_agent import place_trust as trust
from jeju_agent.assistant_search import search_assistant
from jeju_agent.tourism_access import approved_places

ROOT=Path(__file__).resolve().parents[1]
AS_OF=date(2026,11,7)


class TrustRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ('data_reference/tourism.sqlite',trust.GUIDE_PATH,
                     trust.GUIDE_PROOFS_PATH,'config/place_trust_policy_v15.json'):
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,target)
        self.places={p['id']:p for p in approved_places(self.root)}

    def search(self,query='성산일출봉',**options):
        original=trust._reference_day
        with patch.object(trust,'_reference_day',side_effect=lambda value: original(AS_OF if value is None else value)):
            return search_assistant(self.root,query,include_route_restricted=True,**options)

    def change_same_stamp(self,relative,old,new):
        path=self.root/relative;info=path.stat();raw=path.read_bytes()
        changed=raw.replace(old,new,1)
        self.assertNotEqual(raw,changed);self.assertEqual(len(raw),len(changed))
        path.write_bytes(changed);os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
        self.assertEqual(path.stat().st_size,info.st_size)
        self.assertEqual(path.stat().st_mtime_ns,info.st_mtime_ns)

    def test_candidate_checks_match_standalone_and_explicit_other_day_wins(self):
        ferry=next(p['id'] for p in self.places.values() if p.get('requires_ferry'))
        ids=('seongsan','hamdeok',ferry)
        expected=[trust.place_trust(self.root,self.places[i],as_of=AS_OF) for i in ids]
        with trust.trust_request(self.root,as_of=AS_OF):
            actual=[trust.place_trust(self.root,self.places[i]) for i in ids]
            expired=trust.place_trust(self.root,self.places['hamdeok'],as_of=AS_OF+timedelta(days=365))
        self.assertEqual(actual,expected)
        self.assertEqual(expired['checks']['official_guide']['status'],'review_overdue')
        self.assertFalse(expired['automatic_eligible'])

    def test_request_day_is_fixed_and_next_request_checks_a_new_day(self):
        future=AS_OF+timedelta(days=365)
        with trust.trust_request(self.root,as_of=AS_OF):
            before=trust.place_trust(self.root,self.places['hamdeok'])
            with patch.object(trust,'_reference_day',return_value=future):
                same=trust.place_trust(self.root,self.places['hamdeok'])
        self.assertEqual(before,same)
        with trust.trust_request(self.root,as_of=future):
            expired=trust.place_trust(self.root,self.places['hamdeok'])
        self.assertTrue(before['automatic_eligible'])
        self.assertFalse(expired['automatic_eligible'])

    def test_returned_results_and_verified_guides_cannot_poison_later_calls(self):
        expected=self.search()
        result=self.search();result[0]['name']='changed';result[0]['official_intro']['text']='changed'
        result[0]['sources'][0]['url']='https://invalid.example/'
        self.assertEqual(self.search(),expected)
        with trust.trust_request(self.root,as_of=AS_OF):
            guide=trust._verified_request_guide(self.root,'seongsan')
            original=guide['summary'];guide['summary']='changed'
            self.assertEqual(trust._verified_request_guide(self.root,'seongsan')['summary'],original)

    def test_display_guide_text_must_match_the_authenticated_source_record(self):
        item=deepcopy(self.places['seongsan'])
        item['tourism_guide']['summary']='원문과 연결되지 않은 설명으로 바뀐 관광지 소개입니다.'
        with patch('jeju_agent.assistant_search.approved_places',return_value=[item]):
            self.assertEqual(self.search(),[])

    def test_same_size_and_mtime_catalog_tampering_is_detected_after_warmup(self):
        self.assertTrue(self.search())
        self.change_same_stamp(trust.GUIDE_PATH,'분화구'.encode(),'화분구'.encode())
        self.assertEqual(self.search(),[])

    def test_same_size_and_mtime_compact_proof_tampering_is_detected(self):
        self.assertTrue(self.search())
        path=self.root/trust.GUIDE_PROOFS_PATH
        raw=path.read_bytes();old=b'"http_status": 200'
        if old not in raw:old=b'"http_status":200'
        self.change_same_stamp(trust.GUIDE_PROOFS_PATH,old,old.replace(b'200',b'201'))
        self.assertEqual(self.search(),[])

    def test_policy_future_date_with_same_stamp_stops_new_request(self):
        self.assertTrue(self.search())
        relative='config/place_trust_policy_v15.json'
        policy=json.loads((self.root/relative).read_text('utf-8'))
        old=policy['reviewed_at'];new=str(int(old[:4])+1)+old[4:]
        self.change_same_stamp(relative,old.encode(),new.encode())
        with self.assertRaises(trust.TrustPolicyError):self.search()

    def test_materialized_bad_receipt_is_seen_on_the_next_request(self):
        self.assertTrue(self.search())
        policy=json.loads((self.root/'config/place_trust_policy_v15.json').read_text('utf-8'))
        path=self.root/policy['guide_records']['seongsan']['source_cache']
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}',encoding='utf-8')
        self.assertEqual(self.search(),[])

    def test_context_is_internal_and_cannot_accept_arbitrary_dictionary(self):
        with self.assertRaises(trust.TrustPolicyError):trust._TrustRequest(self.root,AS_OF,object())
        token=trust._REQUEST.set({'root':self.root,'policy':{}})
        try:
            with self.assertRaises(trust.TrustPolicyError):
                trust.place_trust(self.root,self.places['seongsan'],as_of=AS_OF)
        finally:trust._REQUEST.reset(token)

    def test_a_context_for_one_root_does_not_supply_another_roots_sources(self):
        with tempfile.TemporaryDirectory() as other:
            other_root=Path(other)
            with trust.trust_request(self.root,as_of=AS_OF):
                with self.assertRaises(trust.TrustPolicyError):
                    trust.place_trust(other_root,self.places['seongsan'],as_of=AS_OF)

    def test_nested_context_and_exception_cleanup_do_not_leak_a_scope(self):
        with trust.trust_request(self.root,as_of=AS_OF):
            original=trust.place_trust(self.root,self.places['hamdeok'])
            with self.assertRaisesRegex(RuntimeError,'stop'):
                with trust.trust_request(self.root,as_of=AS_OF+timedelta(days=365)):
                    self.assertFalse(trust.place_trust(self.root,self.places['hamdeok'])['automatic_eligible'])
                    raise RuntimeError('stop')
            self.assertEqual(trust.place_trust(self.root,self.places['hamdeok']),original)
        self.assertIsNone(trust._REQUEST.get())

    def test_concurrent_requests_keep_different_review_days_separate(self):
        barrier=threading.Barrier(2)
        def inspect(day):
            with trust.trust_request(self.root,as_of=day):
                barrier.wait(timeout=5)
                return trust.place_trust(self.root,self.places['hamdeok'])['automatic_eligible']
        with ThreadPoolExecutor(max_workers=2) as executor:
            live=executor.submit(inspect,AS_OF)
            expired=executor.submit(inspect,AS_OF+timedelta(days=365))
            self.assertTrue(live.result(timeout=10))
            self.assertFalse(expired.result(timeout=10))


if __name__=='__main__':unittest.main()

