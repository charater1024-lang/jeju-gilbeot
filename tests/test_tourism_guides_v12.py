import hashlib,json,tempfile,unittest
from pathlib import Path
from jeju_agent.tourism_guides import guide_for,enrich_tourism

class TourismGuideTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).parents[1]/'.test_tmp';scratch.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=scratch)
        self.root=Path(self.tmp.name);(self.root/'data_reference').mkdir()
        self.place={'id':'approved','name':'검증 관광지','source_overlap_verified':True,'latitude':33.5,'longitude':126.5,'source_url':'https://www.openstreetmap.org/node/42','description':'지도에 기록된 짧은 메모','cross_source':{'policy_id':'test'}}
        self.record={'id':'approved','name':'검증 관광지','summary':'바다와 화산 지형을 함께 살펴보는 관광 장소입니다. 전시와 주변 경관에 대한 공식 관광 안내를 참고할 수 있습니다.','source_url':'https://www.visitjeju.net/kr/detail/view?contentsid=TEST','source_name':'제주관광공사 비짓제주','source_content_id':'TEST','summary_method':'source_based_editorial_paraphrase'}
        self.path=self.root/'data_reference/tourism_guides_v12.json'
    def tearDown(self):self.tmp.cleanup()
    def write(self,record):self.path.write_text(json.dumps({'guides':[record]},ensure_ascii=False),encoding='utf-8')
    def test_missing_guide_never_generates_a_tourism_story(self):
        self.assertIsNone(guide_for(self.root,self.place))
        p=enrich_tourism(self.root,self.place);self.assertFalse(p['tourism_guide_available']);self.assertEqual(p['description'],self.place['description'])
    def test_source_backed_guide_is_separate_from_map_and_does_not_change_coordinates(self):
        self.write(self.record);before=dict(self.place);p=enrich_tourism(self.root,self.place)
        self.assertEqual(p['description'],self.record['summary']);self.assertEqual(p['map_description'],before['description'])
        self.assertEqual(p['source_url'],before['source_url']);self.assertEqual(p['cross_source'],before['cross_source']);self.assertEqual(p['latitude'],before['latitude']);self.assertEqual(self.place,before)
    def test_repeated_enrichment_preserves_original_map_note(self):
        self.write(self.record);p=enrich_tourism(self.root,enrich_tourism(self.root,self.place))
        self.assertEqual(p['map_description'],self.place['description']);self.assertEqual(p['tourism_guide']['source_content_id'],'TEST')
    def test_unapproved_or_wrong_id_cannot_acquire_guide(self):
        self.write(self.record)
        self.assertIsNone(guide_for(self.root,dict(self.place,source_overlap_verified=False)))
        self.assertIsNone(guide_for(self.root,dict(self.place,id='other')))
    def test_map_and_unofficial_and_unsafe_links_are_not_tourism_guide_sources(self):
        for url in ['https://www.openstreetmap.org/node/42','https://not-official.example/','javascript:alert(1)','https://user:pass@www.visitjeju.net/','http://www.visitjeju.net/']:
            with self.subTest(url=url):
                self.write(dict(self.record,source_url=url));self.assertIsNone(guide_for(self.root,self.place))
    def test_script_or_incomplete_summaries_fail_closed(self):
        for summary in ['짧은 글','<script>alert(1)</script>'+'가'*40]:
            self.write(dict(self.record,summary=summary));self.assertIsNone(guide_for(self.root,self.place))
    def test_reading_guide_does_not_mutate_its_cached_source(self):
        self.write(self.record);before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        first=guide_for(self.root,self.place);first['summary']='changed'
        self.assertEqual(guide_for(self.root,self.place)['summary'],self.record['summary']);self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

if __name__=='__main__':unittest.main()
