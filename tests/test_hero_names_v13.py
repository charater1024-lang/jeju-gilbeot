"""Hero names follow the approved catalogue; photo identity is retained."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jeju_agent.server import hero_slides


class HeroNameTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/'.test_tmp';scratch.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=scratch);self.root=Path(self.tmp.name)
        (self.root/'config').mkdir()
        self.slide={'id':'osulloc','name':'오설록 티 뮤지엄','caption':'오설록 티 뮤지엄의 풍경','title':'오늘의 오설록 티 뮤지엄','image':'/assets/osulloc.jpg','source_id':'visitjeju_CONT_000000000500457'}
        self.data={'schema_version':1,'interval_ms':5000,'autoplay':True,'slides':[self.slide]}
        self.path=self.root/'config/hero_slides.json'
    def tearDown(self):self.tmp.cleanup()
    def render(self,approved):
        self.path.write_text(json.dumps(self.data,ensure_ascii=False),encoding='utf-8')
        with patch('jeju_agent.tourism_access.approved_places',return_value=approved):return hero_slides(self.root)
    def test_approved_name_updates_caption_and_title_without_changing_photo_identity(self):
        before=copy.deepcopy(self.data)
        result=self.render([{'id':'osulloc','name':'오설록 티뮤지엄'}])['slides'][0]
        self.assertEqual(result['name'],'오설록 티뮤지엄')
        self.assertEqual(result['caption'],'오설록 티뮤지엄의 풍경')
        self.assertEqual(result['title'],'오늘의 오설록 티뮤지엄')
        for key in ['id','image','source_id']:self.assertEqual(result[key],self.slide[key])
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')),before)
    def test_unapproved_or_empty_named_places_are_not_slides(self):
        for approved in [[],[{'id':'different','name':'오설록 티뮤지엄'}],[{'id':'osulloc','name':' '}]]:
            with self.subTest(approved=approved):self.assertEqual(self.render(approved)['slides'],[])
    def test_editorial_caption_without_old_name_is_preserved(self):
        self.slide['caption']='차밭을 바라보는 오후'
        self.assertEqual(self.render([{'id':'osulloc','name':'오설록 티뮤지엄'}])['slides'][0]['caption'],self.slide['caption'])


if __name__=='__main__':unittest.main()
