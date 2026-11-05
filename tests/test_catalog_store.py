import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from jeju_agent.catalog_store import build_store,food_search,place_search,resolve_place,affinity_food,access_flags,generic_itinerary_label

SOURCE=Path(__file__).resolve().parent.parent
class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=SOURCE);self.root=Path(self.tmp.name)
        (self.root/'data_reference').mkdir();(self.root/'data_raw'/'hub').mkdir(parents=True)
        (self.root/'data_reference'/'restaurants.json').write_text(json.dumps({'source_date':'2025-09-02','items':[{'id':'f1','name':'시험 식당','category':'한식','address':'제주시 조천읍 함덕리','region':'north','status':'영업/정상','source_date':'2025-09-02','source_url':'https://example.org'}]}),encoding='utf-8')
        (self.root/'data_raw'/'hub'/'hub_1349_5802.csv').write_text('장소명,도로명주소,위도,경도,수정일시,지번주소\n해변입구,제주시 조천읍,33.5,126.6,2025-09-18,\n해변입구,제주시 조천읍,33.5,126.6,2025-09-18,\n범위밖,서울시,37.5,127.5,2025-09-18,\n',encoding='utf-8')
        self.report=build_store(self.root)
    def tearDown(self):self.tmp.cleanup()
    def test_deduplication_and_scope_filter(self):
        self.assertEqual(self.report['place_indexed_rows'],1);self.assertEqual(self.report['duplicate_rows_removed'],1)
        self.assertEqual(self.report['excluded_missing_or_outside_main_island'],1)
    def test_search_is_read_only_and_literal_wildcards_are_not_injection(self):
        self.assertEqual(food_search(self.root,'함덕')['total'],1)
        self.assertEqual(food_search(self.root,'%')['total'],0)
        self.assertEqual(place_search(self.root,"' OR 1=1")['total'],0)
        self.assertEqual(place_search(self.root,'해')['items'],[])
    def test_place_identity_and_actual_category_examples(self):
        p=place_search(self.root,'해변')['items'][0]
        self.assertEqual(resolve_place(self.root,p['id'])['name'],'해변입구')
        self.assertFalse(p['featured'])
        foods=affinity_food(self.root,[{'name':'한식 음식점업','share':.4}])
        self.assertEqual(foods[0]['id'],'f1');self.assertEqual(foods[0]['affinity_category'],'한식 음식점업')
    def test_island_and_summit_aliases_do_not_bypass_geographic_access_check(self):
        self.assertTrue(access_flags('마라도홍보관','마라로 113',33.1144625,126.2678253)[0])
        self.assertTrue(access_flags('백록담','제주시',33.3596532,126.5350249)[1])
        self.assertTrue(access_flags('선착장','',33.172,126.27)[0])
        self.assertTrue(access_flags('가파도','대한민국',33.1584059,126.2734988)[0])
        self.assertTrue(access_flags('차귀도','대한민국',33.2995823,126.1582)[0])
        self.assertTrue(access_flags('명칭 없는 섬 좌표','',33.3077414,126.1697614)[0])
        self.assertEqual(access_flags('해변 입구','조천읍',33.542,126.669),(False,False))
        self.assertFalse(access_flags('백록담제주특산품','제주시',33.4874315,126.6003005)[1])
        self.assertFalse(access_flags('한라산CC리조트','제주시',33.44,126.546)[1])
        self.assertFalse(access_flags('한라산아래첫마을','제주시',33.3286178,126.3803724)[1])
        self.assertTrue(generic_itinerary_label('3일차 점심'))
        self.assertFalse(generic_itinerary_label('함덕 해변'))

if __name__=='__main__':unittest.main()
