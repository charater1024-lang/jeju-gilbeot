"""Cross-source policy must hold at every tourism serving boundary."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import unittest

from jeju_agent.chatbot import chat_reply
from jeju_agent.place_details import place_details
from jeju_agent.reference import catalogue,plan_destinations
from jeju_agent.roads import route_geometry
from jeju_agent.tourism import search_tourism
from jeju_agent.tourism_access import approved_places,approved_place,place_search,resolve_trip_place

ROOT=Path(__file__).resolve().parents[1]


class TourismServingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.approved=approved_places(ROOT)
        if not cls.approved:raise AssertionError('Build the production source-overlap tourism index before serving tests')
        with closing(sqlite3.connect(ROOT/'data_reference/tourism.sqlite')) as db:
            cls.aliases={row[0] for row in db.execute('SELECT source_id FROM aliases')}
        with closing(sqlite3.connect(ROOT/'data_reference/discovery.sqlite')) as db:
            cls.food_aliases={json.loads(row[0])['place_id'] for row in db.execute('SELECT coordinate_source FROM restaurants WHERE coordinate_source IS NOT NULL') if json.loads(row[0]).get('place_id')}
        with closing(sqlite3.connect(ROOT/'data_reference/catalog.sqlite')) as db:
            rows=db.execute('SELECT id,name FROM places ORDER BY id').fetchall()
        cls.bad_hub=next(ident for ident,name in rows if ident not in cls.aliases and ident not in cls.food_aliases and ('롯데마트' in name or '렌터카' in name))
        cls.bad_osm='osm_tourism_node_5783397753'  # 마구로쇼쿠도 incorrectly carried tourism=attraction.
        cls.walkable=next(p for p in cls.approved if not p.get('requires_ferry') and not p.get('requires_access_point'))

    def assert_approved(self,items):
        for point in items:
            proof=point.get('cross_source') or {}
            self.assertEqual(point.get('kind'),'attraction')
            self.assertIs(point.get('source_overlap_verified'),True)
            self.assertEqual(proof.get('match_method'),'normalized_exact_name_and_distance')
            self.assertTrue(proof.get('hub',{}).get('id'))
            self.assertTrue(proof.get('osm',{}).get('id'))
            self.assertGreaterEqual(proof.get('distance_m',-1),0)
            self.assertLessEqual(proof['distance_m'],250)

    def request(self,ids):
        return {'date':'2026-10-29','transport':'car','start_lat':33.506,'start_lon':126.492,'end_lat':33.506,'end_lon':126.492,'start_minute':540,'end_minute':1200,'budget_krw':100000,'max_stops':len(ids),'interests':[],'avoid_crowds':False,'destination_ids':ids,'origin_confirmed':True,'origin_source':'landmark','origin_label':'공개 기준점 제주공항'}

    def test_home_catalogue_only_serves_approved_curated_places(self):
        result=catalogue(ROOT)
        self.assertTrue(result['source_overlap_required']);self.assertTrue(result['items'])
        self.assert_approved(result['items'])
        self.assertTrue({p['id'] for p in result['items']}<={p['id'] for p in self.approved})
        self.assertNotIn('hallasan',{p['id'] for p in result['items']})

    def test_name_address_search_cannot_reintroduce_generic_registry(self):
        result=place_search(ROOT,'제주',limit=50)
        self.assertTrue(result['source_overlap_required']);self.assertTrue(result['items'])
        self.assert_approved(result['items'])
        self.assertEqual(place_search(ROOT,'마구로쇼쿠도')['items'],[])

    def test_all_and_reference_filters_do_not_bypass_policy(self):
        all_rows=search_tourism(ROOT,{'kind':'all','limit':100})
        self.assertEqual(all_rows['total'],len(self.approved));self.assert_approved(all_rows['items'])
        reference=search_tourism(ROOT,{'kind':'reference','limit':100})
        self.assertEqual(reference['total'],0);self.assertEqual(reference['items'],[])

    def test_unmatched_map_and_hub_identifiers_have_no_details_or_trip_resolution(self):
        for ident in [self.bad_osm,self.bad_hub,'hallasan','saryeoni','not_a_public_place']:
            with self.subTest(ident=ident):
                self.assertIsNone(approved_place(ROOT,ident))
                self.assertIsNone(resolve_trip_place(ROOT,ident))
                self.assertIsNone(place_details(ROOT,ident))

    def test_unmatched_legacy_ids_cannot_be_planned_or_routed(self):
        for ident in [self.bad_osm,self.bad_hub,'hallasan']:
            with self.subTest(ident=ident):
                with self.assertRaises(ValueError):plan_destinations(ROOT,self.request([ident]))
                with self.assertRaises(ValueError):route_geometry(ROOT,{'destination_ids':[ident],'transport':'walk'})

    def test_approved_source_aliases_and_details_resolve_to_same_canonical_place(self):
        point=self.walkable;proof=point['cross_source']
        for ident in [point['id'],proof['osm']['id'],proof['hub']['id']]:
            with self.subTest(ident=ident):
                resolved=approved_place(ROOT,ident);self.assertIsNotNone(resolved)
                self.assertEqual(resolved['id'],point['id']);self.assert_approved([resolved])
                details=place_details(ROOT,ident);self.assertTrue(details['available']);self.assert_approved([details['item']])
        route=route_geometry(ROOT,{'destination_ids':[point['id']],'transport':'walk'})
        self.assertEqual(route['kind'],'straight_line');self.assert_approved(route['stops'])
        planned=plan_destinations(ROOT,self.request([point['id']]))
        self.assertEqual(planned['status'],'ok');self.assertEqual(planned['stops'][0]['poi_id'],point['id'])

    def test_tourism_chat_cards_all_have_cross_source_evidence(self):
        for message in ['북부 관광지 추천','박물관 추천','해변 추천']:
            result=chat_reply(ROOT,{'message':message})
            self.assertEqual(result['intent'],'tourism_search');self.assertTrue(result['cards'])
            self.assert_approved(result['cards'])
        result=chat_reply(ROOT,{'message':'주소 알려줘','state':{'last_place_id':self.bad_osm,'topic':'tourism'}})
        self.assertEqual(result['cards'],[]);self.assertEqual(result['intent'],'ask_place')

    def test_mislabeled_restaurant_remains_food_record_without_attraction_claim(self):
        self.assertNotIn('마구로쇼쿠도',{p['name'] for p in self.approved})
        result=chat_reply(ROOT,{'message':'마구로쇼쿠도 정보'})
        self.assertTrue(result['cards'])
        self.assertTrue(all(p.get('kind')=='food' and not p.get('source_overlap_verified') for p in result['cards']))
        self.assertNotIn(self.bad_osm,{p['id'] for p in result['cards']})


if __name__=='__main__':unittest.main()
