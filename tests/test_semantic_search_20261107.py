"""Neural retrieval cannot widen trusted data, source claims, or API permissions."""
import contextlib
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from jeju_agent import place_trust as trust
from jeju_agent import semantic_search as semantic
from jeju_agent import server
from jeju_agent.assistant_search import search_assistant
from jeju_agent.tourism_access import approved_places

ROOT=Path(__file__).resolve().parents[1]
AS_OF=date(2026,11,7)
DIMENSION=32


def digest(raw):return hashlib.sha256(raw).hexdigest()


class SemanticSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ('data_reference/tourism.sqlite',trust.GUIDE_PATH,
                     trust.GUIDE_PROOFS_PATH,'config/place_trust_policy_v15.json'):
            dest=self.root/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,dest)
        self.places={p['name']:p for p in approved_places(self.root)}
        self.primary=self.places['제주목관아'];self.secondary=self.places['용두암']
        self.restricted=self.places['성산일출봉']
        self.modeldir=self.root/'models_semantic';self.modeldir.mkdir()
        (self.modeldir/'encoder.int8.onnx').write_bytes(b'authenticated-test-onnx')
        (self.modeldir/'tokenizer.json').write_bytes(b'{}')
        self.config={'schema_version':1,'enabled':True,'model_id':'fixture-semantic-model',
                     'revision':'fixed-fixture','embedding_dimension':DIMENSION,'max_length':256,
                     'query_prefix':'query: ','score_threshold':.75,
                     'model_sha256':digest((self.modeldir/'encoder.int8.onnx').read_bytes()),
                     'tokenizer_sha256':digest(b'{}')}
        self.corpus={'schema_version':1,'model_id':self.config['model_id'],
                     'embedding_dimension':DIMENSION,'items':[
                         self.row(self.primary,[1.,0.]),
                         self.row(self.secondary,[.6,.8]),
                         self.row(self.restricted,[-1.,0.])
                     ]}
        self.write_assets()
        original=trust._reference_day
        self.clock=patch.object(trust,'_reference_day',side_effect=lambda v:original(AS_OF if v is None else v))
        self.clock.start();self.addCleanup(self.clock.stop)
        self.encoder=patch.object(semantic,'_encode',return_value=[1.]+[0.]*(DIMENSION-1))
        self.mock_encode=self.encoder.start();self.addCleanup(self.encoder.stop)

    def row(self,place,vector):
        guide=place['tourism_guide']
        return {'id':place['id'],'name':place['cross_source']['hub']['name'].strip(),
                'summary_sha256':digest(guide['summary'].encode('utf-8')),
                'source_url':guide['source_url'],'retrieved_at':guide['retrieved_at'],
                'vector':vector+[0.]*(DIMENSION-len(vector))}

    def write_assets(self):
        raw=json.dumps(self.corpus,ensure_ascii=False,indent=2).encode('utf-8')
        (self.modeldir/'corpus.json').write_bytes(raw)
        self.config['corpus_sha256']=digest(raw)
        (self.modeldir/'config.json').write_text(json.dumps(self.config,ensure_ascii=False,indent=2),encoding='utf-8')

    def search(self,query='옛 행정의 흔적이 남은 공간',**options):
        return semantic.search_semantic(self.root,query,**options)

    def test_ranked_result_retains_exact_authenticated_intro_sources_and_hub_name(self):
        result,=self.search()
        self.assertEqual(result['id'],self.primary['id'])
        self.assertEqual(result['name'],self.primary['cross_source']['hub']['name'])
        self.assertEqual(result['official_intro']['text'],self.primary['tourism_guide']['summary'])
        self.assertEqual(result['matched_evidence']['source_url'],self.primary['tourism_guide']['source_url'])
        self.assertEqual(result['ranking_method'],'verified_guide_neural_embedding')
        self.assertEqual(result['score_kind'],'cosine_similarity_not_probability')
        self.assertTrue(result['automatic_eligible'])
        self.assertFalse(result['current_opening_verified'])
        self.assertNotIn('latitude',result)
        self.mock_encode.assert_called_once()

    def test_exact_name_and_official_alias_reuse_existing_lookup_without_encoder(self):
        for query in ('성산 일출봉','성산일출봉 공식 소개 알려줘','넥슨뮤지엄','용두암소개'):
            with self.subTest(query=query):
                expected=search_assistant(self.root,query,include_route_restricted=True)
                self.assertEqual(self.search(query),expected)
        self.mock_encode.assert_not_called()

    def test_unusable_exact_name_never_falls_back_to_another_places_intro(self):
        def missing(root,item,**kwargs):
            result=trust.place_trust(root,item,**kwargs)
            if item['id']==self.restricted['id']:
                result['checks']['official_guide']['status']='not_verified'
            return result
        with patch.object(semantic,'place_trust',side_effect=missing):
            self.assertEqual(self.search('성산일출봉'),[])
        self.mock_encode.assert_not_called()

    def test_unverifiable_or_other_task_conditions_do_not_reach_model(self):
        for query in ('지금 영업중인 박물관','용두암 근처','성산일출봉 입장료',
                      '우도 빼고 바다 풍경','서울 박물관','제주 갈치 맛집',
                      '호텔 추천','오늘 날씨','무료 주차장','제주도 추천',''):
            with self.subTest(query=query):
                self.assertFalse(semantic.semantic_query_supported(query))
                self.assertEqual(self.search(query),[])
        self.mock_encode.assert_not_called()

    def test_threshold_limit_region_and_restricted_policy_are_not_silently_dropped(self):
        self.config['score_threshold']=.5;self.write_assets()
        self.assertEqual([p['id'] for p in self.search(limit=1)],[self.primary['id']])
        self.assertEqual(len(self.search()),2)
        self.assertEqual(self.search(region='east'),[])
        self.mock_encode.return_value=[-1.]+[0.]*(DIMENSION-1)
        item,=self.search()
        self.assertEqual(item['id'],self.restricted['id'])
        self.assertFalse(item['automatic_eligible'])
        self.assertTrue(item['visit_restrictions'])
        self.assertEqual(self.search(include_route_restricted=False),[])

    def test_low_or_invalid_encoder_outputs_are_not_presented_as_recommendations(self):
        self.mock_encode.return_value=[0.,1.]+[0.]*(DIMENSION-2)
        self.config['score_threshold']=.9;self.write_assets()
        self.assertEqual(self.search(),[])
        for value in ([0.]*DIMENSION,[float('nan')]+[0.]*(DIMENSION-1),[1.,2.]):
            with self.subTest(value=str(value[:2])):
                self.mock_encode.return_value=value
                with self.assertRaises(semantic.SemanticModelUnavailable):self.search()

    def test_changed_index_summary_name_url_or_date_cannot_be_attached_to_verified_record(self):
        for key,value in [('summary_sha256','0'*64),('name','다른 장소'),
                          ('source_url','https://invalid.example/'),('retrieved_at','2025-01-01')]:
            with self.subTest(key=key):
                original=deepcopy(self.corpus)
                self.corpus['items'][0][key]=value;self.write_assets()
                self.assertEqual(self.search(),[])
                self.corpus=original;self.write_assets()

    def test_missing_disabled_or_unverified_optional_assets_raise_clear_unavailable(self):
        for change in ('disabled','missing','corpus_changed'):
            with self.subTest(change=change):
                self.config['enabled']=change!='disabled';self.write_assets()
                if change=='missing':(self.modeldir/'encoder.int8.onnx').unlink()
                if change=='corpus_changed':
                    with (self.modeldir/'corpus.json').open('ab') as output:output.write(b' ')
                with self.assertRaises(semantic.SemanticModelUnavailable):self.search()
                (self.modeldir/'encoder.int8.onnx').write_bytes(b'authenticated-test-onnx')
                self.config['enabled']=True;self.write_assets()

    def test_same_size_and_stamp_corpus_tamper_is_seen_after_successful_warm_request(self):
        self.assertTrue(self.search())
        path=self.modeldir/'corpus.json';stamp=path.stat();raw=path.read_bytes()
        changed=raw.replace(b'"vector"',b'"vectoR"',1)
        self.assertNotEqual(raw,changed);self.assertEqual(len(raw),len(changed))
        path.write_bytes(changed);os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        with self.assertRaises(semantic.SemanticModelUnavailable):self.search()

    def test_current_source_expiry_and_display_mismatch_are_rechecked_after_warm_request(self):
        self.assertTrue(self.search())
        with patch.object(trust,'_reference_day',return_value=AS_OF+timedelta(days=365)):
            self.assertEqual(self.search(),[])
        changed=deepcopy(self.primary)
        changed['tourism_guide']['summary']='공식 원문과 연결되지 않은 새로운 설명문으로 바뀌었습니다.'
        with patch.object(semantic,'approved_places',return_value=[changed]):
            self.assertEqual(self.search(),[])

    def test_model_hash_is_checked_before_any_optional_native_package_is_loaded(self):
        with patch.object(semantic,'_dependencies') as packages:
            with self.assertRaises(semantic.SemanticModelUnavailable):
                semantic._engine(str(self.root),'fixture-unique',(), '0'*64,
                                 self.config['tokenizer_sha256'],256)
        packages.assert_not_called()

    def test_caller_mutation_cannot_poison_a_later_response(self):
        expected=self.search();changed=self.search()
        changed[0]['name']='변경됨';changed[0]['official_intro']['text']='변경됨'
        changed[0]['visit_restrictions'].append({'code':'fake'})
        self.assertEqual(self.search(),expected)

    def test_invalid_user_arguments_remain_validation_errors(self):
        for kwargs in ({'query':False},{'query':'a'*161},{'limit':True},{'limit':13},
                       {'region':'elsewhere'},{'include_route_restricted':'yes'}):
            with self.subTest(kwargs=kwargs):
                args={'query':'관아의 흔적'};args.update(kwargs)
                with self.assertRaises(ValueError):semantic.search_semantic(self.root,**args)


class SemanticApiTests(unittest.TestCase):
    def handler(self,body=None):
        captured=[]
        class FakeServer:
            def __init__(self,address,handler):captured.append((self,handler))
            def serve_forever(self):pass
            def server_close(self):pass
        with patch.object(server,'ThreadingHTTPServer',FakeServer),patch.object(server,'service_status',return_value={}),contextlib.redirect_stdout(io.StringIO()):
            server.serve(port=8765)
        instance,handler_type=captured[0];handler=object.__new__(handler_type)
        raw=json.dumps(body if body is not None else {'query':'옛 관아의 흔적'}).encode('utf-8')
        handler.connection=Mock();handler.server=instance;handler.path='/api/semantic-guide-search'
        handler.headers={'Origin':'http://127.0.0.1:8765','Content-Length':str(len(raw))}
        handler.rfile=io.BytesIO(raw);handler.responses=[]
        handler.json_response=lambda value,status=200:handler.responses.append((status,value))
        return handler

    def test_explicit_new_endpoint_dispatches_and_old_endpoint_is_unchanged(self):
        handler=self.handler()
        with patch.object(server,'search_semantic',return_value=[]) as neural,patch.object(server,'search_assistant') as old:
            handler.do_POST()
        self.assertEqual(handler.responses,[(200,[])])
        neural.assert_called_once();old.assert_not_called()

    def test_missing_model_uses_503_without_private_runtime_details_or_fake_fallback(self):
        handler=self.handler()
        with patch.object(server,'search_semantic',side_effect=semantic.SemanticModelUnavailable('private path GPS=33.123456')),patch.object(server,'search_assistant') as old:
            handler.do_POST()
        status,body=handler.responses[0]
        self.assertEqual(status,503);self.assertEqual(body['code'],'semantic_model_unavailable')
        self.assertNotIn('33.123456',str(body));self.assertNotIn('private path',str(body))
        old.assert_not_called()

    def test_unknown_private_location_fields_or_other_region_are_rejected(self):
        for body in ({'query':'소개','latitude':33.5},{'query':'소개','region':'north'}):
            handler=self.handler(body)
            with patch.object(server,'search_semantic') as neural:handler.do_POST()
            self.assertEqual(handler.responses[0][0],400);neural.assert_not_called()

    def test_other_origins_cannot_call_optional_neural_endpoint(self):
        handler=self.handler();handler.headers['Origin']='https://unrelated.example'
        with patch.object(server,'search_semantic') as neural:handler.do_POST()
        self.assertEqual(handler.responses[0][0],403);neural.assert_not_called()


if __name__=='__main__':unittest.main()
