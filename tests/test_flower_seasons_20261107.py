import calendar,hashlib,json,shutil,tempfile,unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
from jeju_agent import flower_seasons as service
from jeju_agent.climate_guide import climate_reference
ROOT=Path(__file__).resolve().parents[1]

class FlowerSeasonsTests(unittest.TestCase):
    def test_source_scope_and_no_flower_prediction(self):
        data=service.flower_status(ROOT)
        self.assertEqual(len(data['flowers']),6)
        self.assertEqual(sum(r['event_count'] for r in data['flowers']),28)
        self.assertFalse(data['flower_prediction']['available'])
        self.assertFalse(data['flower_ml_trained'])
        self.assertEqual(data['event_period'],['2018-05-12','2025-03-23'])
        self.assertTrue(any(r['url']=='https://www.jejudatahub.net/data/view/data/761' for r in data['sources']))
        self.assertAlmostEqual(data['temperature_model']['test_mae_c'],1.9199917311305275)

    def test_all_flower_preferences_and_actual_months(self):
        source=json.loads((ROOT/service.DATA_PATH).read_text(encoding='utf-8'))
        for flower in source['flowers']:
            expected={m:0 for m in range(1,13)}
            rows=[r for r in source['events'] if flower['id'] in r['flowers']]
            for row in rows:
                start,end=date.fromisoformat(row['start_date']),date.fromisoformat(row['end_date'])
                months={ (start+timedelta(days=i)).month for i in range((end-start).days+1)}
                for m in months:expected[m]+=1
            for pref in service.PREFERENCES:
                with self.subTest(flower=flower['id'],pref=pref['id']):
                    result=service.flower_seasons(ROOT,flower['id'],'seogwipo',pref['id'])
                    self.assertEqual(len(result['month_comparisons']),12)
                    self.assertEqual({r['month']:r['event_count'] for r in result['month_comparisons']},expected)
                    self.assertTrue(all(r['event_count']>0 and r['reference_day']==15 for r in result['suggestions']))
                    middle=(pref['min_c']+pref['max_c'])/2
                    ranked=sorted([r for r in result['month_comparisons'] if r['event_count']],key=lambda r:(abs(r['point_c']-middle),r['month']))
                    self.assertEqual(result['suggestions'],ranked[:3])
                    for row in result['events']:
                        self.assertTrue(row['reference_only'])
                        self.assertFalse(row['bloom_observation'])
                        self.assertFalse(row['current_event_verified'])
                        self.assertFalse(row['automatic_route_eligible'])

    def test_temperature_values_are_existing_learned_model(self):
        for station in ['jeju','gosan','seongsan','seogwipo']:
            result=service.flower_seasons(ROOT,station=station)
            climate=climate_reference(ROOT,6,15,station)
            for actual,expected in zip(result['month_comparisons'],climate['seasonality']):
                self.assertEqual([actual[k] for k in ['point_c','lower_c','upper_c']],[expected[k] for k in ['point_c','lower_c','upper_c']])

    def test_actual_cherry_observation_scope(self):
        result=service.flower_seasons(ROOT,'cherry')
        self.assertEqual(len(result['observations']),3)
        row=next(r for r in result['observations'] if r['year']==2026)
        self.assertEqual((row['station_id'],row['phase'],row['observed_date']),('184','개화','2026-03-28'))
        self.assertIn('기준목',row['scope'].replace('표준목','기준목'))
        self.assertFalse(row['future_prediction'])
        self.assertEqual(service.flower_seasons(ROOT,'hydrangea')['observations'],[])

    def test_bad_conditions(self):
        for kwargs in [{'flower':'unverified'},{'flower':True},{'preference':'hot'},{'station':'unknown'}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):service.flower_seasons(ROOT,**kwargs)

    def test_reference_requests_do_not_fetch_external_weather(self):
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('External network not allowed')):
            self.assertTrue(service.flower_seasons(ROOT)['available'])
            with patch.dict('os.environ',{'JEJU_FLOWER_WEATHER_API':' 0 '}):
                self.assertFalse(service.flower_status(ROOT)['weather']['available'])

    def test_changed_and_missing_sources_fail_after_cache(self):
        original=json.loads((ROOT/service.DATA_PATH).read_text(encoding='utf-8'))
        names=[service.DATA_PATH]+[r['path'] for r in original['source_files']]
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            for name in names:
                dst=base/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dst)
            self.assertEqual(len(service._assets(base)['events']),28)
            for name in names:
                path=base/name;raw=path.read_bytes();mutated=bytearray(raw);mutated[-1]^=1
                path.write_bytes(mutated)
                with self.subTest(name=name,kind='changed'),self.assertRaises(service.FlowerDataError):service._assets(base)
                path.write_bytes(raw);path.unlink()
                with self.subTest(name=name,kind='missing'),self.assertRaises(service.FlowerDataError):service._assets(base)
                path.write_bytes(raw)

if __name__=='__main__':unittest.main()
