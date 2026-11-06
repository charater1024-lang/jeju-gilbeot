"""Trust-policy service failures are distinct from invalid public requests."""
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from jeju_agent import server
from jeju_agent.place_trust import TrustPolicyError

ROOT=Path(__file__).resolve().parents[1]


class AgentServerTests(unittest.TestCase):
    def handler(self):
        captured=[]
        class FakeServer:
            def __init__(self,address,handler):captured.append((self,handler))
            def serve_forever(self):pass
            def server_close(self):pass
        with patch.object(server,'ThreadingHTTPServer',FakeServer),patch.object(server,'service_status',return_value={}),contextlib.redirect_stdout(io.StringIO()):
            server.serve(port=8765)
        instance,handler_type=captured[0]
        handler=object.__new__(handler_type)
        handler.connection=Mock();handler.server=instance
        handler.path='/api/agent/plan'
        handler.headers={'Origin':'http://127.0.0.1:8765','Content-Length':'2'}
        handler.rfile=io.BytesIO(b'{}');handler.responses=[]
        handler.json_response=lambda value,status=200:handler.responses.append((status,value))
        return handler

    def test_trust_policy_failure_returns_503_without_exception_details(self):
        handler=self.handler()
        with patch.object(server,'run_agent',side_effect=TrustPolicyError('INTERNAL_POLICY_PATH private origin=33.50678123')):
            handler.do_POST()
        status,body=handler.responses[0]
        self.assertEqual(status,503)
        self.assertEqual(body['code'],'trust_policy_unavailable')
        self.assertIn('출처',body['error'])
        self.assertNotIn('INTERNAL_POLICY_PATH',str(body))
        self.assertNotIn('33.50678123',str(body))

    def test_invalid_user_condition_remains_400(self):
        handler=self.handler()
        with patch.object(server,'run_agent',side_effect=ValueError('출발지를 확인하세요.')):
            handler.do_POST()
        status,body=handler.responses[0]
        self.assertEqual(status,400)
        self.assertEqual(body,{'error':'출발지를 확인하세요.'})


if __name__=='__main__':unittest.main()
