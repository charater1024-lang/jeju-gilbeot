import json
from pathlib import Path
import unittest

from jeju_agent.assistant import run_assistant


ROOT = Path(__file__).resolve().parents[1]


class AssistantIntegrationTests(unittest.TestCase):
    def message(self, text, state=None):
        return run_assistant(ROOT, {'message': text, 'state': state})

    def confirm(self, draft, action='confirm'):
        return run_assistant(ROOT, {'action': action, 'state': draft['state'], 'origin_choice': 'candidate'})

    def test_trip_confirmation_revision_and_comparison(self):
        draft = self.message('오전 10시에 제주공항에서 차로 출발해서 3시간 안에 돌아오게 짜줘. 용두암은 빼줘.')
        self.assertEqual(draft['status'], 'needs_confirmation', draft)
        self.assertNotIn('route', draft)
        self.assertEqual(draft['conditions']['여행 시간'], '10:00 출발 · 13:00까지 복귀')
        self.assertEqual(draft['conditions']['제외할 장소'], '용두암')
        self.assertEqual(run_assistant(ROOT, {'action':'confirm','state':draft['state']})['status'], 'needs_input')
        result = self.confirm(draft)
        self.assertEqual(result['status'], 'ok', result)
        self.assertTrue(result['route']['stops'])
        self.assertNotIn('용두암', [p['name'] for p in result['route']['stops']])
        self.assertNotIn('request', result['route'])
        self.assertNotIn('start_lat', json.dumps(result))
        comparison = self.confirm(result, 'alternatives')
        self.assertTrue(comparison['alternatives'])
        self.assertEqual(comparison['conditions']['여행 시간'], draft['conditions']['여행 시간'])
        for option in comparison['alternatives']:
            self.assertNotIn('용두암', [p['name'] for p in option['route']['stops']])

    def test_followup_reduces_actual_count_and_preserves_other_conditions(self):
        result = self.confirm(self.message('제주공항에서 오전 9시에 차로 출발해서 9시간 안에 돌아오는 관광지 3곳 코스 짜줘.'))
        self.assertEqual(len(result['route']['stops']), 3)
        revised = self.message('한 곳만 줄여줘', result['state'])
        self.assertEqual(revised['status'], 'needs_confirmation', revised)
        self.assertEqual(revised['conditions']['방문 수'], '최대 2곳')
        self.assertEqual(revised['conditions']['여행 시간'], result['conditions']['여행 시간'])
        self.assertEqual(len(self.confirm(revised)['route']['stops']), 2)

    def test_time_revision_preserves_duration_or_explicit_deadline(self):
        timed = self.message('오전 10시에 제주공항에서 차로 출발해서 3시간 안에 돌아오는 코스 짜줘.')
        moved = self.message('출발을 오전 11시로 바꿔줘.', timed['state'])
        self.assertEqual(moved['conditions']['여행 시간'], '11:00 출발 · 14:00까지 복귀')
        deadline = self.message('오후 3시까지 복귀하게 바꿔줘.', moved['state'])
        moved_again = self.message('출발을 12:00으로 바꿔줘.', deadline['state'])
        self.assertEqual(moved_again['conditions']['여행 시간'], '12:00 출발 · 15:00까지 복귀')

    def test_actual_consumption_and_mobility_sources(self):
        food = self.message('도민과 내국인 참고 집단의 6월 외식 업종 비중을 비교해줘.')
        self.assertEqual(food['status'], 'ok', food)
        self.assertEqual(len(food['analysis']['rows']), 8)
        self.assertEqual(len(food['analysis']['columns']), 3)
        self.assertTrue(food['analysis']['sources'][0]['url'].endswith('/1048'))
        bus = self.message('토요일 오전과 오후 버스 승차를 비교해줘.')
        self.assertEqual(bus['status'], 'ok', bus)
        self.assertEqual(len(bus['analysis']['rows']), 4)
        self.assertTrue(bus['analysis']['sources'][0]['url'].endswith('/512'))

    def test_hub_grounded_search(self):
        for request, kind, ident in [('옛 제주 모습을 볼 만한 곳을 찾아줘.', 'attraction', '1349'),
                                     ('애월 카페 추천', 'food', '780'),
                                     ('서귀포 음식점 찾아줘.', 'food', '780')]:
            with self.subTest(request=request):
                result = self.message(request)
                self.assertEqual(result['status'], 'ok', result)
                self.assertTrue(result['places'], result)
                for place in result['places']:
                    self.assertEqual(place['kind'], kind)
                    self.assertTrue(place['primary_source']['url'].endswith('/' + ident))
                    self.assertNotEqual(place['category'], '편의점')

    def test_tampered_state_cannot_confirm(self):
        draft = self.message('오전 10시에 제주공항에서 차로 출발해서 3시간 안에 돌아오게 짜줘.')
        with self.assertRaises(ValueError):
            run_assistant(ROOT, {'action':'confirm','state':draft['state']+'a','origin_choice':'candidate'})
