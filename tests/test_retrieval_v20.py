"""Regression checks for source integrity and conservative candidate promotion."""
from pathlib import Path
import json
import math
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from jeju_agent import retrieval_v20 as rv

def read(relative):return json.loads((ROOT/relative).read_text('utf-8'))

class RetrievalV20Tests(unittest.TestCase):
    def test_frozen_benchmark_and_post_test_audit_links(self):
        benchmark=read('development_support/retrieval_v20/benchmark.json')
        freeze=read('development_support/retrieval_v20/benchmark_freeze.json')
        audit=read('development_support/retrieval_v20/quality_audit.json')
        promotion=read('models_candidates_v20/retrieval/promotion.json')
        self.assertEqual(rv.digest(benchmark),freeze['benchmark_sha256'])
        self.assertEqual(rv.digest(audit),promotion['quality_audit_sha256'])
        self.assertEqual(160,len(benchmark['cases']))
        for domain in rv.DOMAINS:
            groups={split:{c['group'] for c in benchmark['cases'] if c['domain']==domain and c['split']==split} for split in ('dev','test')}
            self.assertFalse(groups['dev']&groups['test'])
        self.assertEqual(132,audit['entity_overlap']['food']['dev_test_relevant_id_overlap'])
        self.assertTrue(all(audit['entity_overlap'][d]['dev_test_relevant_id_overlap']==0 for d in ('tourism','guide','travel')))
        self.assertEqual({'tourism'}, {d for d,row in promotion['domains'].items() if row['activate']})
        self.assertFalse(promotion['intent_activate'])

    def test_frozen_labels_reference_real_current_source_records(self):
        benchmark=read('development_support/retrieval_v20/benchmark.json')
        for domain in rv.DOMAINS:
            documents=rv.load_documents(ROOT,domain)
            self.assertEqual(benchmark['corpus_counts'][domain],len(documents))
            self.assertEqual(benchmark['corpus_sha256'][domain],rv.digest([{k:v for k,v in row.items() if k!='record'} for row in documents]))
            ids={row['id'] for row in documents}
            for case in benchmark['cases']:
                if case['domain']==domain:self.assertTrue(set(case['relevant_ids'])<=ids)

    def test_lexical_configurations_preserve_source_region_and_kind_filters(self):
        docs=[{'id':'real_a','name':'성산일출봉','category':'자연','text':'해안 경관','kind':'attraction','region':'east','source_platform':'jeju_datahub'},
              {'id':'real_b','name':'성산 해안','category':'관광','text':'해안 경관','kind':'attraction','region':'west','source_platform':'other'},
              {'id':'real_c','name':'성산 해안','category':'시설','text':'해안 경관','kind':'amenity','region':'east','source_platform':'jeju_datahub'}]
        # Minimal test doubles exercise filters; these records never enter a service index.
        index=rv.LexicalIndex(docs)
        self.assertEqual(48,len(rv.candidate_configs()))
        for config in rv.candidate_configs():
            rows=index.rank('성산',config,kind='attraction',region='east',hub_only=True)
            self.assertTrue(all(row['id']=='real_a' and math.isfinite(row['score']) for row in rows))
        self.assertEqual([],index.rank('실시간 성산',rv.candidate_configs()[0]))
        self.assertEqual([],index.rank('근처 성산',rv.candidate_configs()[0]))

    def test_production_rerank_matches_frozen_same_pool_and_preserves_tail_and_evidence(self):
        results=read('models_candidates_v20/retrieval/retrieval_metrics.json')['domains']['tourism']
        original=results['incumbent_service']['details']
        predicted=results['production_constrained_rerank']['details']
        before,after=next((a,b) for a,b in zip(original,predicted) if a['returned_ids']!=b['returned_ids'])
        records=[{'id':ident,'source_url':'unchanged','evidence':{'checked':True}} for ident in before['returned_ids']]
        records+=[{'id':'tail_6','distance_km':1.25},{'id':'tail_7','distance_km':3.5}]
        status={}
        output=rv.rerank_candidates(ROOT,before['query'],records,domain='tourism',status=status)
        self.assertEqual(after['returned_ids'],[row['id'] for row in output[:5]])
        self.assertEqual([row['id'] for row in records[5:]],[row['id'] for row in output[5:]])
        self.assertEqual({id(row) for row in records},{id(row) for row in output})
        self.assertTrue(status['applied'])
        self.assertEqual('verified_candidate_rerank',status['reason'])

    def test_unpromoted_scopes_and_unsupported_requests_return_original_objects(self):
        records=[{'id':'unchanged','evidence':{'source':'actual'}}]
        for domain in ('food','guide','travel'):
            status={}
            self.assertIs(records,rv.rerank_candidates(ROOT,'명소',records,domain=domain,status=status))
            self.assertEqual('domain_not_promoted',status['reason'])
        self.assertIs(records,rv.rerank_candidates(ROOT,'실시간 성산',records,domain='tourism'))

    def test_missing_corrupt_or_stale_artifacts_fail_closed(self):
        records=[{'id':'stay'}]
        with tempfile.TemporaryDirectory() as temp:
            status={}
            self.assertIs(records,rv.rerank_candidates(Path(temp),'관광',records,domain='tourism',status=status))
            self.assertEqual('receipt_or_source_validation_failed',status['reason'])
            folder=Path(temp)/'models_candidates_v20/retrieval';folder.mkdir(parents=True)
            (folder/'promotion.json').write_text('{"sha256":"invalid"}','utf-8')
            self.assertIs(records,rv.rerank_candidates(Path(temp),'관광',records,domain='tourism'))
        with mock.patch.object(rv,'_cached_index',side_effect=ValueError('changed source fingerprint')):
            status={}
            self.assertIs(records,rv.rerank_candidates(ROOT,'해안',records,domain='tourism',status=status))
            self.assertEqual('receipt_or_source_validation_failed',status['reason'])
        with mock.patch.object(rv,'load_documents',return_value=[{'id':'tampered'}]):
            with self.assertRaisesRegex(ValueError,'출처 지문'):
                rv._cached_index.__wrapped__(str(ROOT),'tourism',0,(),'wrong_sha')

    def test_source_file_changes_invalidate_cache_stamp(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('data_reference/tourism.sqlite','data_reference/tourism_guides_v12.json','config/place_trust_policy_v15.json'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('initial','utf-8')
            before=rv._source_stamp(root,'tourism')
            (root/'data_reference/tourism.sqlite').write_text('updated source bytes','utf-8')
            self.assertNotEqual(before,rv._source_stamp(root,'tourism'))

    def test_portable_intent_matches_fixed_selected_result_without_runtime_sklearn(self):
        benchmark=read('development_support/retrieval_v20/benchmark.json')
        cases=benchmark['intent']['test']
        correct=sum(rv.classify_intent(ROOT,row['text'])==row['label'] for row in cases)
        metric=read('models_candidates_v20/retrieval/intent_metrics.json')
        self.assertEqual(60,len(cases))
        self.assertEqual(metric['selected_test']['correct'],correct)
        self.assertEqual(52,correct)
        self.assertEqual('clarify',rv.classify_intent(ROOT,''))
        self.assertLess(correct,metric['incumbent_nb_test']['correct'])

if __name__=='__main__':unittest.main()
