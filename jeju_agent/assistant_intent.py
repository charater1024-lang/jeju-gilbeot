"""Small offline Korean request classifier and explicit condition extraction.

The utterances below are development examples labelled for this interface.
The fitted counts classify request types, and never supply facts about places.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from math import log
import re
import unicodedata


_EXAMPLES = {
    'plan': (
        '제주공항 오전 10시 출발 자동차로 세 시간 코스 짜줘',
        '오전 아홉 시부터 오후 두 시까지 둘러볼 일정 만들어 주세요',
        '공항에서 출발해서 저녁 다섯 시까지 돌아오는 여행 코스',
        '도보로 두 곳 방문하는 코스를 짜 주세요',
        '차로 동쪽을 두 시간 둘러보고 돌아오는 일정',
        '오전 10시에 출발 오후 3시에 복귀할 거예요',
        '공항 출발 바다를 보는 코스 자동차로 추천해줘',
        '아침 열 시 출발 두 곳만 가는 일정',
        '내일 오후에 제주 여행 일정 계획해줘',
        '서쪽 관광 코스를 만들어 줘',
        '두 시간 안에 돌아오는 일정 짜줘',
        '자동차로 여행 코스 추천',
    ),
    'revise': (
        '아까 일정에서 한 곳만 줄여줘', '기존 코스에서 두 곳으로 줄여 주세요',
        '이동이 더 짧은 일정으로 바꿔줘', '용두암은 빼고 다시 계산해줘',
        '이 코스에서 용두암은 제외해 줘', '여행 일정을 오후 세 시 복귀로 바꿔줘',
        '방문 장소를 한 곳 줄여 주세요', '동선이 짧게 다시 짜줘',
        '지금 코스를 도보로 바꿔줘', '기존 코스에서 한 군데 빼줘',
        '출발을 오전 열한 시로 수정해줘', '용두암은 빼줘',
    ),
    'food': (
        '도민과 내국인 참고 집단의 6월 외식 업종 비중을 비교해줘',
        '제주도민 7월 음식 업종별 카드 소비 비중', '관광객 5월 소비 업종 비율 보여줘',
        '내국인 8월 식당 업종별 소비 구성 알려줘', '도민과 관광객 소비 경향 비교',
        '6월 식음료 업종 이용건수 구성비', '제주 주민의 3월 외식 소비 분석',
        '월별 카드 소비 경향이 궁금해', '두 집단의 9월 업종별 비중 비교',
        '4월 도민 식음료 소비를 분석해 주세요', '내국인 참고집단 2월 소비 비율',
        '11월 외식업종 비중을 알려줘',
    ),
    'mobility': (
        '토요일 오전과 오후 버스 승차 패턴 비교해줘',
        '제주 전체 버스 시간대별 승차 경향을 보여줘', '일요일 저녁 버스 승차 인원 추정',
        '금요일 오전 버스 이용건수 패턴 알려줘', '토요일과 일요일 일반 승차 비교',
        '날짜별 버스 탑승 통계 분석해줘', '버스 오전 오후 승차 패턴이 궁금해',
        '일반 승차권 시간대별 이용 경향', '제주 버스 수요의 과거 경향',
        '토요일 승차 통계 보여 주세요', '금요일 아침과 저녁 버스 탑승 비중 비교',
        '버스 이용객 집계 오전 경향 알려줘',
    ),
    'search': (
        '옛날 제주 풍경을 만나는 명소 찾아줘', '제주의 옛 이야기를 느낄 수 있는 관광지 찾아줘',
        '바다를 바라볼 수 있는 관광 명소 추천해줘', '산책할 곳을 찾아줘',
        '푸른 바다를 볼 만한 장소 어디야', '역사 유적지를 찾아 주세요',
        '제주 동쪽 바다 근처 관광지를 검색해줘', '숲길 있는 관광지',
        '제주 서쪽 한식 식당 찾아줘', '박물관 추천해 주세요',
        '사진 찍기 좋은 전망 명소를 검색해줘', '흑돼지 식당 찾아줘',
    ),
    'clarify': (
        '안녕하세요', '노래를 불러줘', '예약을 대신 해줘', '전화 걸어줘',
        '날씨 알려줘', '실시간 교통 알려줘', '영업시간 확인해줘', '가격 결제해줘',
        '강아지 사진 그려줘', '비밀번호 바꿔줘', '지금 얼마나 혼잡해', '통역해줘',
    ),
}

_NUMBERS = dict(zip(('한', '두', '세', '네', '다섯', '여섯', '일곱', '여덟', '아홉', '열', '열한', '열두'), range(1, 13)))
_NUM = r'(?:\d{1,3}|열\s*한|열\s*두|다섯|여섯|일곱|여덟|아홉|한|두|세|네|열)'
_CLOCK = re.compile(rf'(?<![\d:])(?P<period>오전|오후|아침|저녁)?\s*(?P<hour>{_NUM})\s*(?:시(?!간)(?:\s*(?P<half>반)|\s*(?P<minutes>\d{{1,2}})\s*분)?|:(?P<colon>\d{{2}})(?!\d))')
_DURATION = re.compile(rf'(?<!\d)(?:(?P<hours>{_NUM})\s*시간(?!\s*(?:대|표))(?:\s*(?P<minutes>{_NUM})\s*분|\s*(?P<half>반))?\s*(?:동안|안에|이내|짜리|정도|남았)?|(?P<only_minutes>{_NUM})\s*분\s*(?:동안|안에|이내|짜리|정도|남았))')
_VISITS = re.compile(rf'(?<!\d)(?P<count>{_NUM})\s*(?:곳|군데)')
_MONEY = re.compile(r'(?<!\d)(?P<amount>\d[\d,]{0,11})(?:\s*(?P<units>만|천))?\s*원')
_DATE = re.compile(r'(?<!\d)(\d{4})(?:[-.]|\s*년\s*)(\d{1,2})(?:[-.]|\s*월\s*)(\d{1,2})(?:\s*일)?(?!\d)')
_MONTH = re.compile(r'(?<!\d)(\d{1,2})\s*월(?!\s*요일|\d)')
_WEEKDAYS = '월화수목금토일'
_REGIONS = {'동부':'east', '동쪽':'east', '서부':'west', '서쪽':'west', '북부':'north', '북쪽':'north', '남부':'south', '남쪽':'south'}
_SUBREGION = re.compile(r'제주시|서귀포|애월|성산|중문|조천|구좌|한림|한경|표선|남원|대정|안덕|추자|우도')
_THEMES = ('바다', '해변', '숲', '오름', '박물관', '역사', '산책', '전망', '동굴', '정원')
_FOOD_SCOPE = re.compile(r'소비|구성비|업종\s*(?:별|비중|비율)|외식\s*업종|카드\s*이용')
_MOBILITY_SCOPE = re.compile(r'승차|탑승|버스.{0,14}(?:패턴|수요|경향|통계|이용객|인원)')
_PLAN_HINT = re.compile(r'출발|복귀|돌아오|여행\s*일정|코스\s*(?:만들|짜|계획|추천)|일정\s*(?:짜|만들)|(?:짜|계획)\s*주?(?:세요|줘)')
_REVISION_HINT = re.compile(r'줄여|바꿔|수정|재계산|다시\s*(?:짜|계산)|(?:아까|기존|이전)\s*(?:코스|일정)|이동.{0,12}짧|동선.{0,12}짧')
_FOOD_SEARCH = re.compile(r'식당|음식점|맛집|카페|찻집|빵집|베이커리|커피\s*전문점')
_SEARCH_HINT = re.compile(r'찾아|검색|볼\s*만한|관광지|명소|추천|어디|' + _FOOD_SEARCH.pattern)
_NEGATION = re.compile(r'빼\s*(?:고|줘|주|기)|제외|말고|싫|아닌|아니고|안\s*가|가지\s*않|원하지|불포함|피하|빼기')
_EXCLUDE = re.compile(r'(?P<name>[가-힣A-Za-z][가-힣A-Za-z0-9·]{1,24}?)(?:\s*(?:에는|은|는|을|를|이랑|과|와))?\s*(?:빼\s*(?:고|줘|주(?:세요|시고)|기)|제외(?:하(?:고|기|세요)|해\s*(?:줘|주세요))?(?![가-힣])|말고)')
_UNSUPPORTED = re.compile(r'실시간|지금\s*(?:열|혼잡|출발)|문\s*(?:을\s*)?(?:연|여는)|영업|개방|운영\s*시간|예약|결제|전화|날씨|휠체어|유모차|덜\s*걷|입장료|주차|메뉴|좌석|맛집\s*순위|인기\s*순위|비\s*(?:가\s*)?오(?:는|면)|실내|야외|반려\s*동물|접근성')


def _features(text):
    compact = re.sub(r'[^가-힣a-z]', '', unicodedata.normalize('NFKC', text).lower())
    return Counter(compact[i:i + n] for n in (2, 3) for i in range(len(compact) - n + 1))


@lru_cache(maxsize=1)
def _fit_classifier():
    counts = {}
    for intent, examples in _EXAMPLES.items():
        counts[intent] = Counter()
        for example in examples:
            counts[intent].update(_features(example))
    vocabulary = set().union(*(counts.values()))
    return vocabulary, counts, {label: sum(c.values()) + len(vocabulary) for label, c in counts.items()}


def _classify(text, candidates):
    vocabulary, counts, denominators = _fit_classifier()
    features = {gram: count for gram, count in _features(text).items() if gram in vocabulary}
    if not features:
        return 'clarify'
    return max(candidates, key=lambda label: sum(count * log((counts[label][gram] + 1) / denominators[label]) for gram, count in features.items()))


def _answer(intent, fields=None, missing=(), clarification=None):
    return {'intent':intent, 'fields':fields or {}, 'missing':list(missing), 'clarification':clarification,
            'model':{'algorithm':'char_ngram_multinomial_nb', 'runtime_llm':False,
                     'training_examples':sum(map(len, _EXAMPLES.values())), 'training_scope':'authored_ui_intent_examples'}}


def _clarify(message):
    return _answer('clarify', clarification=message)


def _number(token):
    compact = re.sub(r'\s+', '', token)
    return int(compact) if compact.isdecimal() else _NUMBERS[compact]


def _date_fields(text, today):
    try:
        dates = {date(int(m[1]), int(m[2]), int(m[3])) for m in _DATE.finditer(text)}
    except ValueError as error:
        raise ValueError('실제로 있는 날짜를 YYYY-MM-DD 형식으로 적어 주세요.') from error
    for label, days in [('오늘', 0), ('내일', 1), ('모레', 2)]:
        if label in text:
            dates.add(today + timedelta(days=days))
    if len(dates) > 1:
        raise ValueError('한 날짜씩 요청해 주세요.')
    return {'date':next(iter(dates)).isoformat()} if dates else {}


def _regions(text):
    regions = {_REGIONS[word] for word in _REGIONS if word in text}
    if len(regions) > 1:
        raise ValueError('지역은 한 곳씩 선택해 주세요.')
    return {'region':next(iter(regions))} if regions else {}


def _clock_value(match):
    hour = _number(match['hour'])
    minutes = 30 if match['half'] else int(match['minutes'] or match['colon'] or 0)
    if match['period']:
        if not 1 <= hour <= 12:
            raise ValueError('오전·오후를 붙인 시각은 1시부터 12시까지로 적어 주세요.')
        hour = hour % 12 + (12 if match['period'] in ('오후','저녁') else 0)
    elif match['colon'] is None and 1 <= hour <= 12:
        raise ValueError('시각의 오전·오후를 적어 주세요. 24시간 표기(예: 16:00)도 가능합니다.')
    if not 0 <= hour <= 24 or not 0 <= minutes <= 59 or (hour == 24 and minutes):
        raise ValueError('유효한 시각을 입력해 주세요.')
    return hour * 60 + minutes


def _trip_fields(text, today, pending):
    fields = {**_date_fields(text, today), **_regions(text)}
    weekdays = {_WEEKDAYS.index(m[1]) for m in re.finditer(r'([월화수목금토일])\s*요일', text)}
    if len(weekdays)>1 or (weekdays and 'date' in fields and weekdays!={date.fromisoformat(fields['date']).weekday()}):
        raise ValueError('여행할 날짜 또는 요일을 하나로 정해 주세요.')
    if weekdays and 'date' not in fields:
        weekday = next(iter(weekdays))
        if re.search(r'이번\s*주|다음\s*주|지난\s*주', text):
            week = 1 if re.search(r'다음\s*주',text) else -1 if re.search(r'지난\s*주',text) else 0
            day = today + timedelta(days=weekday-today.weekday()+7*week)
        else:
            day = today + timedelta(days=(weekday-today.weekday())%7)
        fields['date'] = day.isoformat()
    elif 'date' not in fields and re.search(r'이번\s*주|다음\s*주|지난\s*주|주말', text):
        raise ValueError('일정을 작성할 날짜를 알려 주세요.')
    consumed = [m.span() for m in _DATE.finditer(text)]
    exclusion_text = re.sub(rf'{_NUM}\s*(?:곳|군데)\s*(?:만\s*)?(?:빼\s*(?:줘|주세요)|제외해\s*(?:줘|주세요))',' ',text)
    exclusions = list(_EXCLUDE.finditer(exclusion_text))
    if any(m['name'] in {'자동차','버스','도보','렌터카','승용차','자차','걸어서','가지'} for m in exclusions) or re.search(r'안\s*(?:타|걷)|걷지|(?:자동차|버스|도보|차)\s*(?:는|은)?\s*(?:없이|아닌|않)',text):
        raise ValueError('이동수단은 제외할 방식 대신 이용할 자동차 또는 도보를 적어 주세요.')
    if exclusions:
        fields['exclude_names'] = list(dict.fromkeys(m['name'] for m in exclusions))
    remaining = _EXCLUDE.sub(' ', exclusion_text)
    if _NEGATION.search(remaining) or re.search(r'제외\s*하지|빼지\s*(?:말|않)|말아\s*(?:줘|주세요)', text):
        raise ValueError('제외할 관광지 이름을 분명히 적어 주세요.')
    if re.search(r'(?:[가-힣]+\s*(?:,|와\s+|과\s+|이랑\s+|및\s+))+[가-힣]+(?:은|는|을|를)?\s*(?:빼|제외|말고)', text):
        raise ValueError('제외할 장소마다 이름과 제외 조건을 적어 주세요.')
    transports = [mode for mode, pattern in [('car',r'자동차|승용차|렌터카|렌트카|자차|(?<![가-힣])차로'), ('walk',r'도보|걸어서|걸어\s*가'), ('bus',r'버스')] if re.search(pattern, remaining)]
    if len(transports) > 1:
        raise ValueError('이동수단을 하나만 골라 주세요.')
    if transports:
        fields['transport'] = transports[0]
    if re.search(r'대중교통|자전거|택시|오토바이|킥보드|배편', remaining) and not transports:
        raise ValueError('자동차 또는 도보 중 이동수단을 명시해 주세요.')
    origin_text = _CLOCK.sub(' ', _DATE.sub(' ',remaining))
    origin = re.search(r'([가-힣A-Za-z0-9·]{2,28})(?:에서\s*(?:(?:자동차|렌터카|차|도보|버스)로\s*)?|\s+)출발', origin_text)
    if origin and not re.fullmatch(r'오전|오후|오늘|내일|모레|아침|저녁|차로|자동차로|도보로|버스로', origin[1]):
        fields['start_name'] = '제주공항' if origin[1] in ('공항','제주국제공항') else origin[1]
    elif re.search(r'제주\s*(?:국제)?\s*공항|(?<![가-힣])공항\s*(?:출발|에서)', remaining) and not re.search(r'공항\s*(?:으로|에|까지)\s*(?:도착|복귀|가|이동|$)', remaining):
        fields['start_name'] = '제주공항'
    destination = re.search(r'([가-힣A-Za-z0-9·]{2,28})(?:으로|에)\s*도착', remaining)
    if destination and not re.fullmatch(r'\d+시|마지막', destination[1]):
        fields['end_name'] = '제주공항' if destination[1] in ('제주국제공항','공항') else destination[1]
    if re.search(r'돌아오|돌아가|복귀|왕복', remaining):
        fields['return_to_origin'] = True
    if destination and fields.get('return_to_origin') and fields.get('start_name') != fields.get('end_name'):
        raise ValueError('출발지 복귀와 별도 도착지 중 한 가지를 골라 주세요.')
    for index, match in enumerate(_CLOCK.finditer(text)):
        tail = text[match.end():].lstrip()
        before = text[max(0, match.start()-12):match.start()].rstrip()
        field = 'end_minute' if re.match(r'까지|(?:에\s*|안에\s*)?(?:복귀|도착|돌아)', tail) or re.search(r'복귀\s*$', before) or (index and re.search(r'[~∼–-]$',before)) else 'start_minute'
        value = _clock_value(match)
        if field in fields and fields[field] != value:
            raise ValueError('출발 시각과 복귀 시각을 각각 적어 주세요.')
        fields[field] = value
        consumed.append(match.span())
    for match in _DURATION.finditer(text):
        duration = _number(match['hours'] or '0') * 60 + _number(match['minutes'] or match['only_minutes'] or '0') + (30 if match['half'] else 0)
        if duration <= 0 or duration > 1440 or ('duration_minutes' in fields and fields['duration_minutes'] != duration):
            raise ValueError('하루 이내의 이용 시간을 하나만 적어 주세요.')
        fields['duration_minutes'] = duration
        consumed.append(match.span())
    if 'start_minute' in fields and 'duration_minutes' in fields:
        end = fields['start_minute'] + fields['duration_minutes']
        if 'end_minute' in fields and fields['end_minute'] != end:
            raise ValueError('출발 시각·이용 시간·복귀 시각이 서로 맞지 않습니다.')
        fields['end_minute'] = end
    if fields.get('start_minute',0) >= fields.get('end_minute',1440) or fields.get('end_minute',1440) > 1440:
        raise ValueError('출발부터 복귀까지 같은 날짜 안의 시간으로 적어 주세요.')
    for match in _VISITS.finditer(text):
        count = _number(match['count'])
        field = 'reduce_stops' if re.match(r'\s*(?:만\s*)?(?:줄여|덜|빼)',text[match.end():]) else 'max_stops'
        if not 1 <= count <= 8 or (field in fields and fields[field] != count):
            raise ValueError('장소 수는 1~8곳 범위에서 하나만 지정해 주세요.')
        fields[field] = count
        consumed.append(match.span())
    if 'reduce_stops' in fields and 'max_stops' in fields:
        raise ValueError('줄일 곳 수와 최종 방문 곳 수 중 하나만 적어 주세요.')
    for match in _MONEY.finditer(text):
        budget = int(match['amount'].replace(',','')) * {None:1,'만':10000,'천':1000}[match['units']]
        if not 0 <= budget <= 10000000 or ('budget_krw' in fields and fields['budget_krw'] != budget):
            raise ValueError('이동비 한도를 한 금액으로 적어 주세요.')
        fields['budget_krw'] = budget
        consumed.append(match.span())
    if re.search(r'이동.{0,12}짧|동선.{0,12}짧', text):
        fields['shorter_travel'] = True
    place_names = fields.get('start_name','') + fields.get('end_name','')
    themes = [theme for theme in _THEMES if theme in remaining and theme not in place_names]
    if len(themes) > 1 and set(themes) != {'바다','해변'}:
        raise ValueError('코스 관심 주제는 한 가지씩 지정해 주세요.')
    if themes:
        fields['query'] = themes[0]
    if re.search(r'끝내|마무리|편도|[가-힣](?:까지|으로)\s*(?:가고|이동|가게)|[가-힣]까지\s*(?:코스|일정|[.!?]|$)', origin_text):
        raise ValueError('별도 도착지는 일정 화면에서 직접 확인해 주세요.')
    scope_text = remaining
    if origin and 'start_name' in fields:
        scope_text = re.sub(re.escape(origin[1])+r'\s*(?:에서|출발)', ' ', scope_text, count=1)
    if destination and 'end_name' in fields:
        scope_text = scope_text.replace(destination.group(), ' ', 1)
    if _SUBREGION.search(scope_text):
        raise ValueError('세부 지역 코스는 직접 담은 장소로 작성해 주세요. 자동 코스는 동부·서부·남부·북부 조건을 지원합니다.')
    if _FOOD_SEARCH.search(remaining) or re.search(r'들러|반드시|필수\s*방문|꼭\s*(?:가|방문)|(?:도|에|를|은)\s*가고\s*싶|넣어|추가해|직접\s*경유|박\s*일|운전\s*시간|순수\s*이동\s*시간', remaining):
        raise ValueError('꼭 방문할 장소는 지도에서 직접 담고, 일정은 하루 단위로 요청해 주세요.')
    if re.search(rf'(?:최소|딱|정확히)\s*{_NUM}\s*(?:곳|군데)|(?:곳|군데)\s*(?:이상|초과)', remaining):
        raise ValueError('자동 코스의 방문 장소 수는 최대 몇 곳인지 알려 주세요.')
    leftover = list(text)
    for start, end in consumed:
        leftover[start:end] = ' ' * (end-start)
    if re.search(r'\d', ''.join(leftover)):
        raise ValueError('해석되지 않은 숫자가 있습니다. 시각·이용 시간·장소 수·이동비를 단위와 함께 적어 주세요.')
    if pending and re.fullmatch(r'(?:제주\s*(?:국제)?\s*)?공항', text):
        fields['start_name'] = '제주공항'
    return fields


def _condition_reply(text):
    text = text.rstrip(' .!')
    return bool(re.fullmatch(r'(?:제주\s*(?:국제)?\s*)?공항|자동차(?:로)?|렌터카(?:로)?|차로|도보(?:로)?|버스(?:로)?|오늘|내일|모레|(?:(?:이번|다음|지난)\s*주\s*)?[월화수목금토일]\s*요일', text)
                or _CLOCK.fullmatch(text) or _DURATION.fullmatch(text) or _DATE.fullmatch(text)
                or _MONEY.fullmatch(text) or re.fullmatch(rf'{_NUM}\s*(?:곳|군데)\s*(?:만|으로)?',text))


def _food_fields(text):
    if _regions(text) or _SUBREGION.search(text) or re.search(r'지역별|상권별|점포별|매출|매장별|외국인',text):
        raise ValueError('제주 전체 식음료 업종 이용건수 비중을 볼 수 있습니다. 비교할 집단과 월을 알려 주세요.')
    months = {int(m[1]) for m in _MONTH.finditer(text)}
    if len(months) > 1 or any(not 1 <= m <= 12 for m in months) or re.search(r'\d{4}\s*년', text):
        raise ValueError('특정 연도나 여러 달 비교 대신 1~12월 중 한 달을 적어 주세요.')
    audiences = [label for label, words in [('resident', r'도민|제주\s*주민'), ('tourist', r'내국인|관광객')] if re.search(words,text)]
    if re.search(r'두\s*집단|집단별', text):
        audiences = ['resident','tourist']
    fields = {}
    if months:
        fields['month'] = next(iter(months))
    if audiences:
        fields['audiences'] = audiences
    return fields


def _mobility_fields(text,today):
    if _regions(text) or _SUBREGION.search(text) or re.search(r'노선|정류장|시간표|막차|첫차|환승|호선|번\s*버스|도민|관광객|내국인',text):
        raise ValueError('제주 전체 일반 승차의 시간대 경향을 비교할 수 있습니다. 날짜나 요일을 알려 주세요.')
    fields = _date_fields(text, today)
    if re.search(r'\d', _DATE.sub('',text)):
        raise ValueError('승차 집계는 요일과 오전·오후 같은 시간대를 기준으로 요청해 주세요.')
    weekdays = list(dict.fromkeys(_WEEKDAYS.index(m[1]) for m in re.finditer(r'([월화수목금토일])\s*요일',text)))
    if 'date' in fields and weekdays and weekdays != [date.fromisoformat(fields['date']).weekday()]:
        raise ValueError('날짜와 요일이 서로 맞지 않습니다.')
    if weekdays and 'date' not in fields:
        if re.search(r'지난\s*주|다음\s*주|이번\s*주',text):
            raise ValueError('비교할 날짜를 YYYY-MM-DD 형식으로 적어 주세요.')
        fields['weekdays'] = weekdays
    periods = [period for period, pattern in [('morning',r'오전|아침'),('afternoon',r'오후'),('evening',r'저녁|밤'),('daytime',r'낮|주간'),('all',r'하루|전체\s*시간대|종일')] if re.search(pattern,text)]
    if 'all' in periods and len(periods)>1:
        raise ValueError('비교할 시간대 또는 하루 전체 중 하나를 골라 주세요.')
    if periods:
        fields['periods'] = periods
    return fields


def parse_request(text, *, today=None, pending=False):
    """Interpret a single request; callers must still confirm and validate conditions."""
    if not isinstance(text,str) or not 1 <= len(text.strip()) <= 240 or len(text)>300:
        return _clarify('요청을 240자 이내로 입력해 주세요.')
    text = ' '.join(unicodedata.normalize('NFKC', text).split())
    if today is None:
        today = datetime.now(timezone(timedelta(hours=9))).date()
    food = bool(_FOOD_SCOPE.search(text))
    mobility = bool(_MOBILITY_SCOPE.search(text))
    if food and mobility:
        return _clarify('소비와 버스 승차 분석은 한 가지씩 요청해 주세요.')
    if _UNSUPPORTED.search(text):
        return _clarify('보유 자료로 확인할 수 있는 관광지 검색, 일정 작성, 소비·승차 경향 중에서 요청해 주세요.')
    if (food or mobility) and (_NEGATION.search(text) or _REVISION_HINT.search(text)):
        return _clarify('비교할 집단·월 또는 요일·시간대를 긍정 조건으로 각각 적어 주세요.')
    try:
        if food and _classify(text, ('food','clarify')) == 'food':
            fields = _food_fields(text)
            return _answer('food',fields,(key for key in ('audiences','month') if key not in fields))
        if mobility and _classify(text, ('mobility','clarify')) == 'mobility':
            fields = _mobility_fields(text,today)
            return _answer('mobility',fields,() if {'date','weekdays'} & fields.keys() else ('date',))
        if food or mobility:
            return _clarify('비교할 집단·월 또는 요일·시간대와 분석 주제를 적어 주세요.')
        plan_hint = bool(_PLAN_HINT.search(text) or (_CLOCK.search(text) and _DURATION.search(text)))
        revise_hint = bool(_REVISION_HINT.search(text) or _EXCLUDE.search(text))
        candidates = ['clarify']
        if plan_hint:
            candidates.append('plan')
        if revise_hint:
            candidates.append('revise')
        if _SEARCH_HINT.search(text) and not (plan_hint or revise_hint):
            candidates.append('search')
        # Condition-only replies should be handled by the current draft, when present.
        if pending and len(candidates)==1 and _condition_reply(text):
            fields = _trip_fields(text,today,pending)
            if fields:
                return _answer('plan',fields)
        if plan_hint and revise_hint and re.search(r'출발|\d\s*시간|\d\s*시',text) and not re.search(r'기존|아까|이전|바꿔|수정|줄여',text):
            candidates.remove('revise')
        intent = _classify(text,candidates)
        if intent in ('plan','revise'):
            fields = _trip_fields(text,today,pending)
            if intent=='revise' and not fields:
                return _clarify('줄일 장소 수나 제외할 장소 이름처럼 바꿀 조건을 알려 주세요.')
            missing = [key for key in ('start_minute','end_minute','transport') if key not in fields] if intent=='plan' else []
            return _answer(intent,fields,missing)
        if intent=='search' and not _NEGATION.search(text):
            return _answer('search',{'query':text,'kind':'food' if _FOOD_SEARCH.search(text) else 'attraction',**_regions(text)})
    except (ValueError, OverflowError) as error:
        return _clarify(str(error))
    return _clarify('관광지 검색, 여행 코스 작성·수정, 소비·버스 승차 경향 중 원하는 내용을 적어 주세요.')
