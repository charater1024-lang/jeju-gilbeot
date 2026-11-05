"""Behavioural source-join tests with synthetic public-place fixtures only."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from jeju_agent.tourism_overlap import build_overlap_records, match_candidates, normalized_name

ROOT=Path(__file__).resolve().parents[1]
POLICY=json.loads((ROOT/'config/tourism_overlap_policy.json').read_text(encoding='utf-8'))

def mapped(ident=1,name='실제해변',lat=33.5,lon=126.5,tags=None):
    return {'id':f'osm_tourism_node_{ident}','name':name,'latitude':lat,'longitude':lon,'category':'해변','observed_tags':tags or {'natural':'beach','name':name},'source_date':'2026-10-28'}

def hub(ident='one',name='실제해변',lat=33.5001,lon=126.5001,address='오염 가능 주소'):
    return {'id':'hub1349_'+ident,'name':name,'latitude':lat,'longitude':lon,'address':address,'region':'north','source_url':'https://www.jejudatahub.net/data/view/data/1349'}

class TourismOverlapPolicyTests(unittest.TestCase):
    def match(self,maps=None,hubs=None,featured=None,foods=()):
        return match_candidates(maps if maps is not None else [mapped()],hubs if hubs is not None else [hub()],featured or [],copy.deepcopy(POLICY),foods)

    def test_normalization_does_not_drop_parenthetical_identity_or_apply_substring(self):
        self.assertEqual(normalized_name(' Ａ 해수욕장 '),normalized_name('a해수욕장'))
        self.assertNotEqual(normalized_name('공원 입구'),normalized_name('공원'))
        self.assertNotEqual(normalized_name('우도(해양도립공원)'),normalized_name('우도'))

    def test_requires_exact_name_and_nearby_coordinate_together(self):
        for row in [hub(name='실제해변입구'),hub(lat=33.6),hub(name='다른이름',lat=33.5,lon=126.5)]:
            with self.subTest(row=row):self.assertEqual(self.match(hubs=[row])[0],[])
        rows,aliases,audit=self.match()
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['source_overlap_verified'])
        self.assertEqual(rows[0]['cross_source']['match_method'],'normalized_exact_name_and_distance')
        self.assertLessEqual(rows[0]['cross_source']['distance_m'],250)
        self.assertEqual(aliases['hub1349_one'],rows[0]['id'])

    def test_no_single_source_or_curated_fallback(self):
        self.assertEqual(self.match(hubs=[])[0],[])
        self.assertEqual(self.match(maps=[],featured=[{'id':'official','name':'실제해변','latitude':33.5,'longitude':126.5}])[0],[])
        scratch=ROOT/'.test_tmp';scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            with self.assertRaises(ValueError):build_overlap_records(Path(temp))

    def test_food_lodging_shop_and_transport_tags_override_tourism_tag(self):
        cases=[{'tourism':'attraction','amenity':'restaurant'},{'tourism':'museum','amenity':'cafe'},{'tourism':'hotel','historic':'building'},{'natural':'beach','shop':'souvenir'},{'tourism':'viewpoint','highway':'bus_stop'},{'tourism':'attraction','man_made':'water_tower'},{'tourism':'attraction','office':'company'}]
        for tags in cases:
            with self.subTest(tags=tags):self.assertEqual(self.match(maps=[mapped(tags=tags)])[0],[])

    def test_ordinary_playground_golf_and_sports_are_not_attractions(self):
        for value in ['playground','golf_course','sports_centre','recreation_ground']:
            with self.subTest(value=value):self.assertEqual(self.match(maps=[mapped(tags={'leisure':value})])[0],[])

    def test_generic_attraction_conflicting_with_food_permit_is_held(self):
        rows,_,audit=self.match(maps=[mapped(name='식당명',tags={'tourism':'attraction'})],hubs=[hub(name='식당명')],foods=['식당명'])
        self.assertEqual(rows,[])
        self.assertEqual(audit['rejected'][0]['reason'],'generic_map_tag_conflicts_with_food_permit_name')

    def test_same_name_restaurant_does_not_erase_strong_peak_or_museum(self):
        for tags in [{'natural':'peak'},{'tourism':'museum'}]:
            with self.subTest(tags=tags):self.assertEqual(len(self.match(maps=[mapped(tags=tags)],foods=['실제해변'])[0]),1)

    def test_multiple_hub_rows_are_evidence_not_asserted_unique_identity(self):
        rows,aliases,_=self.match(hubs=[hub('one'),hub('two',lat=33.5002,address='다른 오염 주소')])
        proof=rows[0]['cross_source'];self.assertEqual(proof['supporting_hub_records'],2)
        self.assertFalse(proof['hub_address_verified']);self.assertFalse(proof['hub_unique_place_identity_verified'])
        self.assertEqual(rows[0]['address'],'')
        self.assertEqual(aliases['hub1349_one'],aliases['hub1349_two'])

    def test_same_name_nearby_map_duplicates_collapse_with_source_aliases(self):
        rows,aliases,audit=self.match(maps=[mapped(1),mapped(2,lat=33.5002)])
        self.assertEqual(len(rows),1);self.assertEqual(audit['accepted_map_records'],2)
        self.assertEqual(aliases['osm_tourism_node_1'],aliases['osm_tourism_node_2'])

    def test_separated_map_targets_sharing_hub_reference_are_ambiguous(self):
        rows,_,audit=self.match(maps=[mapped(1,lat=33.498),mapped(2,lat=33.502)],hubs=[hub(lat=33.5,lon=126.5)])
        self.assertEqual(rows,[])
        self.assertEqual(audit['rejection_counts']['ambiguous_separated_map_groups'],2)

    def test_map_grouping_does_not_chain_across_large_distance(self):
        rows,_,audit=self.match(maps=[mapped(1,lat=33.498),mapped(2,lat=33.5),mapped(3,lat=33.502)],hubs=[hub(lat=33.5,lon=126.5)])
        self.assertEqual(rows,[])
        self.assertEqual(audit['rejection_counts']['ambiguous_separated_map_groups'],3)

    def test_curated_metadata_only_enriches_after_independent_match(self):
        featured=[{'id':'official','name':'실제해변','latitude':33.5,'longitude':126.5,'address':'공식 참조 주소','image':'/assets/beach.jpg'}]
        rows,aliases,_=self.match(featured=featured)
        self.assertEqual(rows[0]['id'],'official');self.assertEqual(rows[0]['address'],'공식 참조 주소')
        self.assertEqual(aliases['osm_tourism_node_1'],'official')
        self.assertEqual(self.match(hubs=[],featured=featured)[0],[])

    def test_invalid_map_coordinate_and_id_never_join(self):
        for row in [mapped(lat=37.5),mapped(lat=True),mapped(lon=float('nan')),{**mapped(),'id':'food_1'}]:
            with self.subTest(row=row):self.assertEqual(self.match(maps=[row])[0],[])

    def test_missing_raw_tag_proof_has_explicit_rejection(self):
        row=mapped();row['_raw_evidence_error']='missing_raw_osm_element'
        rows,_,audit=self.match(maps=[row]);self.assertEqual(rows,[])
        self.assertEqual(audit['rejected'][0]['reason'],'missing_raw_osm_element')

if __name__=='__main__':unittest.main()
