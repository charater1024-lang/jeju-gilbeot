"""Policy corruption fixtures use copies; observed source/model files stay intact."""
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from jeju_agent import place_trust as trust_module
from jeju_agent.place_trust import GUIDE_PROOFS_PATH, TrustPolicyError, load_policy, place_trust
from jeju_agent.tourism_access import approved_places

ROOT=Path(__file__).resolve().parents[1]
AS_OF=date(2026,11,3)


class PolicyValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.places={item['id']:item for item in approved_places(ROOT)}

    def fixture(self,mutate=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        for relative in ['config/place_trust_policy_v15.json',
                         'data_reference/tourism_guides_v12.json',
                         GUIDE_PROOFS_PATH]:
            target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/relative,target)
        if mutate:self.mutate(root,mutate)
        return root

    def mutate(self,root,change):
        path=root/'config/place_trust_policy_v15.json'
        data=json.loads(path.read_text(encoding='utf-8'));change(data)
        path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

    def assert_bad_policy(self,change):
        root=self.fixture(change)
        with self.assertRaises(TrustPolicyError):load_policy(root,as_of=AS_OF)
        with self.assertRaises(TrustPolicyError):place_trust(root,self.places['hamdeok'],as_of=AS_OF)

    def test_current_policy_retains_all_40_automatic_places(self):
        eligible=[item for item in self.places.values()
                  if place_trust(ROOT,item,as_of=AS_OF)['automatic_eligible']]
        self.assertEqual(len(self.places),68)
        self.assertEqual(len(eligible),40)

    def test_malformed_notices_fail_closed_instead_of_user_error_or_boolean_warning(self):
        notice_id='osm_tourism_way_375341085'
        mutations=[
            lambda p:p['name_notices'].update({notice_id:True}),
            lambda p:p['name_notices'][notice_id].pop('message'),
            lambda p:p['name_notices'][notice_id].update(message=True),
            lambda p:p['name_notices'][notice_id].update(message='  '),
            lambda p:p['name_notices'].update({'unknown_place':copy.deepcopy(p['name_notices'][notice_id])}),
        ]
        for index,change in enumerate(mutations):
            with self.subTest(case=index):self.assert_bad_policy(change)

    def test_exception_schema_cannot_omit_or_mistype_evidence(self):
        ident='osm_tourism_node_4832613086'
        mutations=[
            lambda p:p['automatic_exclusions'].update({ident:[]}),
            lambda p:p['automatic_exclusions'][ident].pop('reason'),
            lambda p:p['automatic_exclusions'][ident].update(code=True),
            lambda p:p['automatic_exclusions'][ident].update(current_operation_verified=True),
            lambda p:p['automatic_exclusions'].update({'unknown_place':copy.deepcopy(p['automatic_exclusions'][ident])}),
        ]
        for index,change in enumerate(mutations):
            with self.subTest(case=index):self.assert_bad_policy(change)

    def test_official_urls_reject_spoofing_credentials_ports_and_non_https(self):
        urls=['http://www.visitjeju.net/', 'https://www.visitjeju.net.evil.invalid/',
              'https://user@www.visitjeju.net/', 'https://www.visitjeju.net:444/',
              'javascript:alert(1)', None]
        for section,ident in [('automatic_exclusions','osm_tourism_node_4832613086'),
                              ('name_notices','osm_tourism_way_375341085')]:
            for url in urls:
                with self.subTest(section=section,url=url):
                    self.assert_bad_policy(lambda p:p[section][ident].update(source_url=url))

    def test_every_digest_is_a_lowercase_sha256_value(self):
        changes=[
            lambda p:p.update(guide_catalog_sha256='g'*64),
            lambda p:p['approved_identity_sha256'].update(hamdeok='A'*64),
            lambda p:p['guide_records']['hamdeok'].update(guide_record_sha256='x'*64),
            lambda p:p['guide_records']['hamdeok'].update(cache_file_sha256=True),
            lambda p:p.update(guide_proofs_sha256=True),
            lambda p:p['guide_records']['hamdeok'].update(original_page_sha256='a'*63),
        ]
        for index,change in enumerate(changes):
            with self.subTest(case=index):self.assert_bad_policy(change)

    def test_receipt_schema_requires_known_id_canonical_path_and_hashes(self):
        changes=[
            lambda p:p.update(guide_records={}),
            lambda p:p['guide_records'].update(hamdeok=[]),
            lambda p:p['guide_records']['hamdeok'].pop('cache_file_sha256'),
            lambda p:p['guide_records']['hamdeok'].update(source_cache='../hamdeok.json'),
            lambda p:p['guide_records']['hamdeok'].update(source_cache='data_raw/tourism/v12/official_fields/osulloc.json'),
            lambda p:p['guide_records'].update(unknown=copy.deepcopy(p['guide_records']['hamdeok'])),
        ]
        for index,change in enumerate(changes):
            with self.subTest(case=index):self.assert_bad_policy(change)

    def test_dates_require_exact_calendar_iso_format(self):
        values=['20261101','2026-W44-7','2026-11-01T12:00:00','2026-02-30',True]
        locations=[(None,None,'reviewed_at'),('automatic_exclusions','osm_tourism_node_4832613086','source_reviewed_at'),
                   ('name_notices','osm_tourism_way_375341085','source_reviewed_at'),
                   ('guide_records','hamdeok','guide_reviewed_at')]
        for section,ident,key in locations:
            for value in values:
                with self.subTest(section=section,key=key,value=value):
                    def change(p):
                        target=p if section is None else p[section][ident]
                        target[key]=value
                    self.assert_bad_policy(change)

    def test_future_policy_exception_and_notice_reviews_stop_recommendation(self):
        changes=[lambda p:p.update(reviewed_at='2026-11-04')]
        for section,ident,keys in [
                ('automatic_exclusions','osm_tourism_node_4832613086',['reviewed_at','source_reviewed_at','public_page_rechecked_at']),
                ('name_notices','osm_tourism_way_375341085',['reviewed_at','source_reviewed_at','public_page_rechecked_at'])]:
            for key in keys:
                changes.append(lambda p,s=section,i=ident,k=key:p[s][i].update({k:'2026-11-04'}))
        for index,change in enumerate(changes):
            with self.subTest(case=index):self.assert_bad_policy(change)

    def test_as_of_is_checked_each_call_outside_the_file_cache(self):
        root=self.fixture()
        self.assertEqual(load_policy(root,as_of=AS_OF)['reviewed_at'],'2026-11-01')
        with self.assertRaises(TrustPolicyError):load_policy(root,as_of=date(2026,10,31))
        self.assertEqual(load_policy(root,as_of=AS_OF)['reviewed_at'],'2026-11-01')

    def test_missing_or_null_optional_rechecks_do_not_invent_dates(self):
        root=self.fixture()
        policy=load_policy(root,as_of=AS_OF)
        self.assertIsNone(policy['automatic_exclusions']['osm_tourism_way_375169007']['public_page_rechecked_at'])
        self.assertNotIn('reviewed_at',policy['name_notices']['osm_tourism_way_375341085'])
        self.assertTrue(place_trust(root,self.places['hamdeok'],as_of=AS_OF)['automatic_eligible'])

    def test_default_reference_day_uses_kst_and_explicit_as_of_takes_precedence(self):
        root=self.fixture()
        with patch.object(trust_module,'datetime') as clock:
            clock.now.return_value.date.return_value=AS_OF
            load_policy(root)
            clock.now.assert_called_once_with(timezone(timedelta(hours=9)))
            clock.now.reset_mock()
            load_policy(root,as_of=AS_OF)
            clock.now.assert_not_called()
        for value in ['2026-11-03',True,datetime(2026,11,3)]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                load_policy(root,as_of=value)

    def test_receipt_fields_must_match_the_bound_guide_record(self):
        changes=[lambda p:p['guide_records']['hamdeok'].update(guide_reviewed_at='2026-10-28'),
                 lambda p:p['guide_records']['hamdeok'].update(original_page_sha256='a'*64)]
        for index,change in enumerate(changes):
            with self.subTest(case=index):
                root=self.fixture(change)
                result=place_trust(root,self.places['hamdeok'],as_of=AS_OF)
                self.assertFalse(result['eligible'])
                self.assertIn('source_receipt_mismatch',{r['code'] for r in result['reasons']})

    def test_future_guide_remains_a_per_place_exclusion_with_a_valid_policy_date(self):
        root=self.fixture();catalog=root/'data_reference/tourism_guides_v12.json'
        data=json.loads(catalog.read_text(encoding='utf-8'))
        guide=next(g for g in data['guides'] if g['id']=='hamdeok')
        guide['retrieved_at']='2026-11-04'
        raw=json.dumps(data,ensure_ascii=False).encode('utf-8');catalog.write_bytes(raw)
        record_hash=hashlib.sha256(json.dumps(guide,ensure_ascii=False,sort_keys=True,
                                            separators=(',',':'),allow_nan=False).encode()).hexdigest()
        def change(p):
            p['guide_catalog_sha256']=hashlib.sha256(raw).hexdigest()
            p['guide_records']['hamdeok'].update(guide_reviewed_at='2026-11-04',guide_record_sha256=record_hash)
        self.mutate(root,change)
        result=place_trust(root,self.places['hamdeok'],as_of=AS_OF)
        self.assertFalse(result['automatic_eligible'])
        self.assertEqual(result['checks']['official_guide']['status'],'review_date_invalid')
        self.assertIn('guide_date_invalid',{r['code'] for r in result['reasons']})


if __name__=='__main__':unittest.main()
