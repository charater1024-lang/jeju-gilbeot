"""The public trip planners must never silently substitute airport coordinates."""
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from jeju_agent import orchestrator, reference, server
from jeju_agent.planning_input import validate_confirmed_origin

ROOT=Path(__file__).resolve().parents[1]


def request(**updates):
    body={'date':'2026-11-03','transport':'car','start_lat':33.506,'start_lon':126.492,
          'end_lat':33.506,'end_lon':126.492,'origin_confirmed':True,
          'origin_source':'landmark','origin_label':'  공개 기준점 제주공항  ',
          'destination_ids':['osulloc'],'include_geometry':False,'max_stops':1}
    body.update(updates)
    return body


def invalid_requests():
    for field in ['origin_confirmed','origin_source','start_lat','start_lon','end_lat','end_lon']:
        body=request();body.pop(field);yield 'missing_'+field,body
    for changes in [dict(origin_confirmed=False),dict(origin_confirmed=1),dict(origin_confirmed='true'),
                    dict(origin_source='unknown'),dict(start_lat=float('nan')),dict(end_lon=float('inf')),
                    dict(start_lat=True),dict(end_lon='126.492'),dict(start_lat=37.5),dict(end_lon=127.1),
                    dict(start_lat=10**400),
                    dict(origin_label=None),dict(origin_label='x'*101)]:
        yield str(changes),request(**changes)


class ConfirmedOriginTests(unittest.TestCase):
    def test_valid_public_origins_are_preserved_and_only_origin_fields_returned(self):
        for source in ['landmark','manual','device']:
            result=validate_confirmed_origin(request(origin_source=source,unused_secret='not preserved'))
            self.assertTrue(result['origin_confirmed'])
            self.assertEqual(result['origin_source'],source)
            self.assertEqual(result['origin_label'],'공개 기준점 제주공항')
            self.assertEqual((result['start_lat'],result['start_lon']),(33.506,126.492))
            self.assertEqual((result['end_lat'],result['end_lon']),(33.506,126.492))
            self.assertEqual(set(result),{'origin_confirmed','origin_source','origin_label',
                                         'start_lat','start_lon','end_lat','end_lon'})

    def test_both_planners_reject_invalid_origins_before_reading_any_places(self):
        for name,body in invalid_requests():
            with self.subTest(name=name),patch.object(reference,'catalogue') as catalogue,patch.object(orchestrator,'search_tourism') as search:
                with self.assertRaises(ValueError):reference.plan_destinations(ROOT,body)
                with self.assertRaises(ValueError):orchestrator.run_agent(ROOT,body)
                catalogue.assert_not_called();search.assert_not_called()

    def test_old_coordinate_free_request_cannot_produce_an_airport_route(self):
        with patch.object(reference,'catalogue') as catalogue:
            with self.assertRaisesRegex(ValueError,'출발·복귀 기준'):
                reference.plan_destinations(ROOT,{'date':'2026-11-03','destination_ids':['osulloc']})
            catalogue.assert_not_called()

    def test_valid_manual_and_automatic_routes_keep_confirmation_metadata(self):
        for planned in [reference.plan_destinations(ROOT,request()),orchestrator.run_agent(ROOT,request(query='오설록'))]:
            self.assertEqual(planned['status'],'ok')
            self.assertTrue(planned['request']['origin_confirmed'])
            self.assertEqual(planned['request']['origin_source'],'landmark')
            self.assertEqual(planned['request']['origin_label'],'공개 기준점 제주공항')


class PlanningOriginHttpTests(unittest.TestCase):
    def handler(self,path,body):
        captured=[]
        class FakeServer:
            def __init__(self,address,handler):captured.append((self,handler))
            def serve_forever(self):pass
            def server_close(self):pass
        with patch.object(server,'ThreadingHTTPServer',FakeServer),patch.object(server,'service_status',return_value={}),contextlib.redirect_stdout(io.StringIO()):
            server.serve(port=8765)
        payload=json.dumps(body).encode('utf-8')
        instance,handler_type=captured[0]
        handler=object.__new__(handler_type)
        handler.connection=Mock();handler.server=instance;handler.path=path
        handler.headers={'Origin':'http://127.0.0.1:8765','Content-Length':str(len(payload))}
        handler.rfile=io.BytesIO(payload);handler.responses=[]
        handler.json_response=lambda value,status=200:handler.responses.append((status,value))
        return handler

    def test_both_http_endpoints_return_400_for_invalid_explicit_origin(self):
        for path in ['/api/plan-destinations','/api/agent/plan']:
            for name,body in invalid_requests():
                with self.subTest(path=path,name=name):
                    handler=self.handler(path,body);handler.do_POST()
                    status,result=handler.responses[0]
                    self.assertEqual(status,400)
                    self.assertTrue(result.get('error'))
                    self.assertNotIn('start_lat',result)
                    self.assertNotIn('stops',result)


if __name__=='__main__':
    unittest.main()
