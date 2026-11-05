"""Regression tests for the bounded offline Korean request interface."""
from datetime import date
import unittest

from jeju_agent.assistant_intent import _EXAMPLES, parse_request


# Authored checks, separate from the classifier training utterances. These do
# not measure field performance or represent actual user conversations.
HOLDOUT = (
    ('plan', '오전 10시에 제주공항에서 차로 출발해서 3시간 안에 돌아오게 짜줘. 용두암은 빼줘.'),
    ('plan', '2026-11-11 오전 8시에 제주국제공항에서 자동차로 출발해 두 시간 반 동안 보고 다시 돌아오는 일정'),
    ('plan', '14:00부터 17:30까지 도보로 제주공항 출발 코스 두 곳만'),
    ('plan', '제주공항 오전10시 차로 3시간 용두암 제외'),
    ('revise', '한 곳만 줄여줘'),
    ('revise', '용두암은 빼고 이동이 짧은 코스로 바꿔줘'),
    ('revise', '여행 코스를 두 군데로 줄여주세요'),
    ('revise', '아까 일정에서 용두암은 제외해줘'),
    ('food', '제주도민과 내국인의 6월 외식 업종 비중을 비교하고 싶어요'),
    ('food', '도민 12월 식음료 소비 비율을 비교해 주세요'),
    ('food', '내국인 참고 집단의 10월 업종별 카드 소비 경향'),
    ('food', '3월 집단별 외식 업종 이용건수 구성비'),
    ('mobility', '토요일 오전과 오후의 제주 버스 승차 패턴을 비교해 주세요'),
    ('mobility', '월요일 저녁 제주 전체 승차 경향이 궁금해'),
    ('mobility', '목요일 오전과 일요일 저녁 시간대의 버스 탑승 통계'),
    ('mobility', '2026-11-08 오후 버스 승차 인원 추정'),
    ('search', '옛 제주 모습을 볼 만한 곳'),
    ('search', '애월 카페 추천'),
    ('search', '제주 북쪽 산책 명소 어디 있어요'),
    ('search', '옛 제주 문화를 볼 수 있는 유적지를 찾아줘'),
    ('clarify', '지금 문을 연 식당 검색'),
    ('clarify', '그림을 그려 주세요'),
    ('clarify', '다음 주 노선 201번 버스 승차량'),
    ('clarify', '인공지능 모델에 관한 시를 지어 줘'),
)


class AssistantIntentTests(unittest.TestCase):
    def test_exact_trip_request_extracts_explicit_times_and_place_exclusion(self):
        result = parse_request(HOLDOUT[0][1])
        self.assertEqual(result['intent'], 'plan')
        self.assertEqual(result['fields'], {'start_name':'제주공항', 'transport':'car',
            'start_minute':600, 'end_minute':780, 'duration_minutes':180,
            'return_to_origin':True, 'exclude_names':['용두암']})
        self.assertFalse(result['model']['runtime_llm'])

    def test_revision_preserves_unspecified_fields_and_separates_reduction(self):
        self.assertEqual(parse_request('한 곳만 줄여줘')['fields'], {'reduce_stops':1})
        self.assertEqual(parse_request('한 곳만 빼줘')['fields'], {'reduce_stops':1})
        self.assertEqual(parse_request('한 곳으로 줄여줘')['fields'], {'max_stops':1})
        self.assertEqual(parse_request(HOLDOUT[5][1])['fields'],
                         {'exclude_names':['용두암'], 'shorter_travel':True})

    def test_pending_condition_only_replies_and_missing_value_are_independent(self):
        self.assertEqual(parse_request('자동차로',pending=True)['fields'], {'transport':'car'})
        self.assertEqual(parse_request('두 곳만',pending=True)['fields'], {'max_stops':2})
        time = parse_request('오전 10시에 출발',pending=True)
        self.assertEqual(time['fields'], {'start_minute':600})
        self.assertIn('end_minute',time['missing'])
        self.assertIsNone(time['clarification'])
        self.assertEqual(parse_request('내일 축제 정보',pending=True)['intent'], 'clarify')

    def test_weekday_and_comparison_arguments_follow_source_units(self):
        self.assertEqual(parse_request('토요일 오전과 오후 버스 승차 패턴 비교해줘')['fields'],
                         {'weekdays':[5], 'periods':['morning','afternoon']})
        self.assertEqual(parse_request('도민과 내국인 참고 집단의 6월 외식 업종 비중을 비교해줘')['fields'],
                         {'month':6, 'audiences':['resident','tourist']})
        self.assertEqual(parse_request('토요일',today=date(2026,11,4),pending=True)['fields'],
                         {'date':'2026-11-07'})

    def test_cafes_and_interest_queries_use_separate_catalogs(self):
        self.assertEqual(parse_request('애월 카페 추천')['fields'], {'query':'애월 카페 추천','kind':'food'})
        self.assertEqual(parse_request('옛 제주 모습을 볼 만한 곳')['fields']['kind'],'attraction')

    def test_conflicting_unverified_and_exclusion_inputs_stop_before_tools(self):
        examples = [
            '오전 10시 출발해서 오후 2시에 복귀하는 3시간 일정',
            '제주공항 5시에 출발하는 여행 코스',
            '제주공항 오후 11시에 출발해서 3시간 코스',
            '2026-02-30 오전 10시 출발 일정',
            '차로 도보로 가는 일정 짜줘',
            '용두암과 성산일출봉 빼줘',
            '용두암은 제외하지 말아줘',
            '해변 말고 박물관',
            '덜 걷게 코스를 바꿔줘',
            '애월 6월 도민 외식 소비 비중',
            '토요일 7시 일반 승차 경향',
            '지금 문을 연 식당 추천',
            '오전 10시에 제주공항에서 차로 출발해 3시간 안에 돌아오는 일정. 함덕에서 끝내줘.',
            '오전 10시에 제주공항에서 차로 출발해 3시간 안에 돌아오는 일정. 성산일출봉도 가고 싶어.',
            '오전 10시에 제주공항에서 차로 출발해 3시간 안에 돌아오는 일정. 점심 식당도 넣어줘.',
            '서귀포 관광 코스를 짜줘',
            '오전 10시에 공항 출발해서 3시간 코스. 버스 안 타고 차로.',
            '오전 10시에 제주공항에서 자동차로 출발해서 3시간 코스 최소 두 곳',
        ]
        for text in examples:
            with self.subTest(text=text):
                result = parse_request(text)
                self.assertEqual(result['intent'],'clarify')
                self.assertTrue(result['clarification'])
                self.assertEqual(result['fields'],{})

    def test_authored_holdout_intent_routing(self):
        training = {text for examples in _EXAMPLES.values() for text in examples}
        for expected, text in HOLDOUT:
            with self.subTest(text=text):
                self.assertNotIn(text,training)
                self.assertEqual(parse_request(text)['intent'],expected)


if __name__=='__main__':
    unittest.main()
