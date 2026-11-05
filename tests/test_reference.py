import json
import sqlite3
import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from jeju_agent.reference import plan_destinations, restaurants


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        # These fixtures test schedule arithmetic, not real-source eligibility.
        trust=patch('jeju_agent.place_trust.place_trust',return_value={
            'eligible':True,'automatic_eligible':True,'reasons':[],
            'sources':[],'warnings':[],'checks':{},'current_operation_verified':False})
        trust.start();self.addCleanup(trust.stop)
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent)
        self.root=Path(self.tmp.name)
        (self.root/'data_reference').mkdir()
        self.items=[{'id':'a','name':'참조 장소 A','category':'nature','latitude':33.51,'longitude':126.5,'source_url':'https://example.org/a','planning_stay_minutes':60},
                    {'id':'b','name':'참조 장소 B','category':'beach','latitude':33.52,'longitude':126.51,'source_url':'https://example.org/b','planning_stay_minutes':60}]
        self.save()
        self.request={'date':'2026-10-27','transport':'car','start_lat':33.506,'start_lon':126.492,'end_lat':33.506,'end_lon':126.492,
                      'start_minute':540,'end_minute':1080,'budget_krw':100000,'interests':[],'max_stops':5,'destination_ids':['a','b'],
                      'origin_confirmed':True,'origin_source':'landmark','origin_label':'공개 기준점 제주공항'}
    def save(self):
        (self.root/'data_reference'/'destinations.json').write_text(json.dumps({'items':self.items}),encoding='utf-8')
        with sqlite3.connect(self.root/'data_reference'/'tourism.sqlite') as db:
            db.execute('CREATE TABLE IF NOT EXISTS places(id TEXT,kind TEXT,data_json TEXT)')
            db.execute('DELETE FROM places')
            for p in self.items:
                from jeju_agent.tourism_overlap import POLICY_ID
                fixture=dict(p,kind='attraction',featured=True,source_overlap_verified=True,cross_source={'policy_id':POLICY_ID,'match_method':'normalized_exact_name_and_distance','distance_m':0,'hub':{'id':'hub_'+p['id']},'osm':{'id':'osm_'+p['id']}})
                db.execute('INSERT INTO places VALUES(?,?,?)',(p['id'],'attraction',json.dumps(fixture)))
        db.close()
    def tearDown(self):self.tmp.cleanup()
    def test_real_selection_is_used_and_unknown_prices_are_not_verified(self):
        r=plan_destinations(self.root,self.request)
        self.assertEqual(r['status'],'ok')
        self.assertEqual({p['poi_id'] for p in r['stops']},{'a','b'})
        self.assertFalse(r['totals']['budget_verified'])
        self.assertIsNone(r['totals']['visit_cost_krw'])
        self.assertTrue(all(p['predicted_visits'] is None for p in r['stops']))
        self.assertLessEqual(r['totals']['end_arrival_minute'],1080)
    def test_ferry_and_bus_require_operating_data(self):
        self.assertEqual(plan_destinations(self.root,dict(self.request,transport='bus'))['status'],'unsupported')
        path=self.root/'data_reference'/'destinations.json';stamp=path.stat()
        self.items[0]['requires_ferry']=True;self.save()
        os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertEqual(plan_destinations(self.root,self.request)['status'],'unsupported')
    def test_infeasible_does_not_silently_drop_places(self):
        r=plan_destinations(self.root,dict(self.request,end_minute=560))
        self.assertEqual(r['status'],'infeasible')
        self.assertEqual(r['stops'],[])
    def test_duplicates_unknown_and_invalid_region_rejected(self):
        for ids in [['a','a'],['unknown']]:
            with self.assertRaises(ValueError):plan_destinations(self.root,dict(self.request,destination_ids=ids))
        with self.assertRaises(ValueError):restaurants(self.root,region='unknown')
    def test_selected_places_respect_user_maximum(self):
        with self.assertRaisesRegex(ValueError,'최대 방문 수'):
            plan_destinations(self.root,dict(self.request,max_stops=1))

if __name__=='__main__':unittest.main()
