from pathlib import Path
import unittest

from jeju_agent.extensions import data_guide, assistant_extension
from jeju_agent.assistant import run_assistant

ROOT = Path(__file__).resolve().parents[1]


class DataExtensionIntegrationTests(unittest.TestCase):
    def test_models_are_used_with_readable_errors_and_scopes(self):
        route = data_guide(ROOT, {'kind':'route', 'date':'2026-11-04'})
        dining = data_guide(ROOT, {'kind':'dining', 'month':'6', 'query':'한식'})
        self.assertTrue(route['rows'])
        self.assertTrue(dining['rows'])
        self.assertTrue(any('48.2%' == metric['value'] for metric in route['metrics']))
        self.assertTrue(any('상위 10' in metric['label'] for metric in dining['metrics']))
        self.assertTrue(any('최근 가중' in metric['label'] for metric in dining['metrics']))
        self.assertTrue(any('2024-01' in note for note in dining['notes']))
        self.assertTrue(any('현재' in note for note in route['notes']))
        for data in (route,dining):
            self.assertEqual({len(row) for row in data['rows']}, {len(data['columns'])})
            self.assertTrue(data['sources'])

    def test_each_actual_context_kind_has_sources_and_dated_records(self):
        for kind in ('walk','beach','accessible','amenity'):
            with self.subTest(kind=kind):
                data = data_guide(ROOT, {'kind':kind})
                self.assertTrue(data['rows'])
                self.assertTrue(data['sources'])
                self.assertTrue(all(row[0] and row[2] for row in data['rows']))
                self.assertEqual(data['metrics'], [])
        timed = data_guide(ROOT, {'kind':'walk','max_minutes':'120'})
        self.assertTrue(timed['rows'])
        self.assertTrue(any('배편' in row[-1] for row in timed['rows']))
        self.assertTrue(any('19' in note for note in timed['notes']))

    def test_conditions_do_not_coerce_invalid_month_or_time(self):
        for params in ({'kind':'dining','month':'13'}, {'kind':'dining','month':True},
                       {'kind':'walk','max_minutes':'nan'}, {'kind':'route','date':'2026-02-31'},
                       {'kind':'beach','max_minutes':'120'}, {'kind':'unknown'}, {'query':'x'*81}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                data_guide(ROOT, params)

    def test_assistant_calls_real_extensions_and_keeps_existing_trip_state(self):
        draft = run_assistant(ROOT, {'message':'오전 10시에 제주공항에서 차로 출발해서 3시간 안에 돌아오는 코스 짜줘.'})
        self.assertEqual(draft['status'], 'needs_confirmation')
        for message in ('6월 세부 외식업종 비교', '노선별 하루 승차 수요 비교', '해수욕장 편의시설 비교'):
            result = run_assistant(ROOT, {'message':message,'state':draft['state']})
            self.assertEqual(result['status'],'ok',result)
            self.assertTrue(result['analysis']['rows'])
            self.assertEqual(result['state'],draft['state'])
        confirmed = run_assistant(ROOT, {'action':'confirm','state':draft['state'],'origin_choice':'candidate'})
        self.assertEqual(confirmed['status'],'ok')

    def test_requests_for_unsupported_conditions_are_not_silently_answered(self):
        self.assertIsNone(assistant_extension(ROOT,'실시간 노선 수요 알려줘'))
        result = assistant_extension(ROOT,'관광객 6월 세부 외식업종 비교')
        self.assertEqual(result['status'],'needs_input')
        result = assistant_extension(ROOT,'협재 해수욕장 편의시설 비교')
        self.assertEqual(result['status'],'needs_input')
        for text in ('6월 말고 7월 세부 외식업종 비교', '2023년 6월 세부 외식업종 비교',
                     '6월 세부 외식업종 비교하고 제주공항에서 3시간 코스 짜줘',
                     '토요일과 일요일 노선 수요 비교'):
            self.assertEqual(assistant_extension(ROOT,text)['status'],'needs_input',text)
        filtered = assistant_extension(ROOT,'6월 한식 세부 외식업종 비교')
        self.assertEqual(filtered['status'],'ok',filtered)
        self.assertTrue(all('한식' in row[0] or '한식' in row[1] for row in filtered['analysis']['rows']))


if __name__=='__main__':
    unittest.main()
