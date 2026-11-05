"""The public service must never execute the historical synthetic demo."""
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from jeju_agent import server
from jeju_agent.tourism import get_model_info

ROOT=Path(__file__).resolve().parents[1]
REAL_MODELS={'tourism_tfidf','food_tfidf','audience_distribution','mobility_pattern'}


class RealOnlyServiceTests(unittest.TestCase):
    def handler(self):
        captured=[]
        class FakeServer:
            def __init__(self,address,handler):captured.append(handler)
            def serve_forever(self):pass
            def server_close(self):pass
        with patch.object(server,'ThreadingHTTPServer',FakeServer),contextlib.redirect_stdout(io.StringIO()):
            # Deliberately unusable legacy data/model arguments prove startup ignores them.
            server.serve(object(),object(),8765)
        handler=object.__new__(captured[0])
        handler.headers={'Origin':'http://127.0.0.1:8765','Content-Length':'2'}
        handler.rfile=io.BytesIO(b'{}')
        handler.responses=[]
        handler.json_response=lambda value,status=200:handler.responses.append((status,value))
        return handler

    def test_model_cards_include_only_real_service_models(self):
        result=get_model_info(ROOT)
        self.assertEqual({card['id'] for card in result['cards']},REAL_MODELS)
        self.assertEqual(len(result['cards']),4)
        self.assertFalse(any(card.get('data_mode')=='synthetic' for card in result['cards']))

    def test_status_has_real_source_counts_without_demo_metrics(self):
        result=server.service_status(ROOT)
        self.assertEqual(result['data']['data_mode'],'real_sources')
        self.assertEqual(result['data']['tourism_candidates'],68)
        self.assertEqual(result['data']['food_source_records'],27056)
        self.assertFalse(result['synthetic_service_enabled'])
        self.assertEqual({card['id'] for card in result['models']},REAL_MODELS)
        self.assertNotIn('request',result)

    def test_legacy_demo_endpoint_is_gone_even_without_body(self):
        handler=self.handler();handler.path='/api/recommend'
        handler.headers={'Origin':'http://127.0.0.1:8765'}
        handler.do_POST()
        self.assertEqual(handler.responses[0][0],410)
        self.assertEqual(handler.responses[0][1]['code'],'synthetic_service_removed')
        self.assertEqual(handler.rfile.tell(),0)

    def test_removed_endpoint_keeps_origin_protection(self):
        handler=self.handler();handler.path='/api/recommend'
        handler.headers={'Origin':'https://untrusted.example'}
        handler.do_POST()
        self.assertEqual(handler.responses[0][0],403)

    def test_real_planner_endpoint_remains_connected(self):
        handler=self.handler();handler.path='/api/plan-destinations'
        with patch.object(server,'plan_destinations',return_value={'status':'ok','data_mode':'reference'}) as planner:
            handler.do_POST()
        planner.assert_called_once_with(ROOT,{})
        self.assertEqual(handler.responses[0],(200,{'status':'ok','data_mode':'reference'}))


if __name__=='__main__':unittest.main()
