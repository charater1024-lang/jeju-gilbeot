import csv,json,tempfile,unittest
from pathlib import Path
from jeju_agent.audience_model import train_audience,predict_audience,read_panels,CATEGORIES,GROUPS

class AudienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent);self.root=Path(self.tmp.name);self.csv=self.root/'observed.csv'
        self.rows=[]
        for n in range(36):
            month=f'{2022+n//12}{n%12+1:02d}'
            for audience,group in GROUPS.items():
                for i,name in enumerate(CATEGORIES):
                    for sex in ['남성','여성','알수없음']:
                        self.rows.append({'base_year_month':month,'biz_nm':name,'user_type':group,'sex':sex,'use_count':100+i*7+(30 if audience=='resident' else 5)})
        self.write()
    def tearDown(self):self.tmp.cleanup()
    def write(self):
        with self.csv.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['base_year_month','biz_nm','user_type','sex','use_count']);w.writeheader();w.writerows(self.rows)
    def test_observed_sex_cells_aggregate_and_probabilities_sum_to_one(self):
        panels,profile=read_panels(self.csv);self.assertEqual(profile['aggregate_cells'],36*2*8)
        self.assertEqual(len(panels),72)
        m=train_audience(self.csv,self.root/'models');r=predict_audience(self.root/'models'/'audience_model.json','resident',10)
        self.assertAlmostEqual(sum(p['share'] for p in r['categories']),1,places=5)
        self.assertEqual(r['status'],'historical_pattern')
        self.assertLess(m['split']['validation_end'],m['split']['test_start'])
    def test_test_changes_do_not_tune_selection(self):
        first=train_audience(self.csv,self.root/'first')
        for row in self.rows:
            if row['base_year_month']>='202405':row['use_count']=int(row['use_count'])*(20 if row['biz_nm']==CATEGORIES[0] else 1)
        self.write();second=train_audience(self.csv,self.root/'second')
        self.assertEqual(first['selection'],second['selection'])
        self.assertEqual(first['validation'],second['validation'])
    def test_missing_or_duplicate_observations_are_not_zero_imputed(self):
        self.rows.pop(0);self.write()
        with self.assertRaisesRegex(ValueError,'성별'):read_panels(self.csv)
        self.rows.append(self.rows[0]);self.write()
        with self.assertRaisesRegex(ValueError,'중복'):read_panels(self.csv)
    def test_bad_requests_and_corrupt_models_are_rejected(self):
        train_audience(self.csv,self.root/'models');path=self.root/'models'/'audience_model.json'
        for month in [0,13,True,'bad']:
            with self.assertRaises(ValueError):predict_audience(path,'resident',month)
        with self.assertRaises(ValueError):predict_audience(path,'unknown',1)
        m=json.loads(path.read_text(encoding='utf-8'));m['profiles']['resident']['global'][0]=123
        path.write_text(json.dumps(m),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'해시'):predict_audience(path,'resident',1)

if __name__=='__main__':unittest.main()
