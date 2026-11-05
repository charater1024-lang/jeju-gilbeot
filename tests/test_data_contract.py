import csv
import json
import tempfile
import unittest
from pathlib import Path
import shutil
from jeju_agent.data_contract import validate

ROOT=Path(__file__).resolve().parent.parent

class DataContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT)
        self.path=Path(self.tmp.name)
        for n in ['pois.csv','demand.csv','demo_metadata.json']:
            shutil.copyfile(ROOT/'data'/n,self.path/n)
    def tearDown(self): self.tmp.cleanup()
    def test_demo_validates(self):
        self.assertEqual(validate(self.path)['mode'],'synthetic')
    def test_synthetic_cannot_become_real_by_removing_metadata(self):
        (self.path/'demo_metadata.json').unlink()
        with self.assertRaisesRegex(ValueError,'합성'):
            validate(self.path,require_real=True)
    def test_invalid_cost_fails_before_training(self):
        p=self.path/'pois.csv'
        with p.open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f);fields=reader.fieldnames;rs=list(reader)
        rs[0]['cost_krw']='3.5'
        with p.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rs)
        with self.assertRaises(ValueError): validate(self.path)
    def use_registered_fixture_sources(self):
        (self.path/'demo_metadata.json').write_text('{"synthetic": false}',encoding='utf-8')
        for name,source_id in [('pois.csv','registered_poi'),('demand.csv','registered_visits')]:
            p=self.path/name
            with p.open(encoding='utf-8-sig',newline='') as f:
                reader=csv.DictReader(f); fields=reader.fieldnames; rs=list(reader)
            for row in rs: row['source_id']=source_id
            with p.open('w',encoding='utf-8',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(rs)
    def test_approved_source_missing_platform_has_validation_error(self):
        self.use_registered_fixture_sources()
        source={'source_id':'registered_poi','status':'approved','source_url':'https://example.org/poi',
                'license':'test_fixture','acquired_at':'2026-10-26','redistribution_allowed':True}
        (self.path/'source_manifest.json').write_text(json.dumps({'sources':[source]}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'platform'):
            validate(self.path,require_real=True)
    def test_same_original_from_two_platforms_is_not_independent_data(self):
        self.use_registered_fixture_sources()
        common={'status':'approved','license':'test_fixture','acquired_at':'2026-10-26',
                'redistribution_allowed':True}
        sources=[dict(common,source_id='registered_poi',platform='jeju_datahub',
                      source_url='https://example.org/poi',original_dataset_id='original_poi'),
                 dict(common,source_id='registered_visits',platform='jeju_bigdata_center',
                      source_url='https://example.org/visits',original_dataset_id='original_visits',
                      granularity='poi_day',measure='visits')]
        manifest=self.path/'source_manifest.json'
        manifest.write_text(json.dumps({'sources':sources}),encoding='utf-8')
        self.assertEqual(validate(self.path,require_real=True)['mode'],'real_validated')
        sources[1]['original_dataset_id']=sources[0]['original_dataset_id']
        manifest.write_text(json.dumps({'sources':sources}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'같은 원본 데이터셋'):
            validate(self.path,require_real=True)

if __name__=='__main__': unittest.main()
