"""Public model release policy. Each metric keeps its original evaluation scope."""
from .audience_v23 import audience_status_v23
from .model_portfolio import get_model_evaluation

TARGET = 90
ACTIVE = ('audience_distribution', 'dining_detail', 'assistant_guide_tfidf')
DECISIONS = {
    'audience_distribution': '새 구성비 모델 적용',
    'dining_detail': '검증된 구성비 모델 유지',
    'assistant_guide_tfidf': '공식 소개 검색에서 사용',
    'mobility_pattern': '시간대별 승차 추정 제외',
    'route_demand': '통계 노선코드 승차 추정 제외',
    'tourism_tfidf': '이름·분류·지역·거리 조건으로 조회',
    'food_tfidf': '이름·업종·주소·거리 조건으로 조회',
    'travel_context_tfidf': '원문 항목과 시간 조건으로 조회',
    'assistant_intent': '명시적인 일정 조건 입력으로 전환',
}
USAGE = {
    'audience_distribution': '관광객·도민 참고 집단의 선택 월 식음료 업종 비중',
    'dining_detail': '제주 전체 세부 외식업종별 이용 비중',
    'assistant_guide_tfidf': '출처가 확인된 공식 관광지 소개의 검색',
}


def _audience_row(root, previous):
    status = audience_status_v23(root)  # Verifies source, profile, selection and evaluation digests.
    result = status['metrics']['model']
    metric = result['within_tolerance']
    before = status['metrics']['incumbent_same_fit']
    if (metric['total'] != previous['metric']['total'] or
            metric['threshold_percentage_points'] != previous['fixed_tolerance'] or
            abs(before['mae_percentage_points']-previous['error']['mae']) > 1e-6 or
            result['test_period'] != previous['test_period']):
        raise ValueError('소비 모델이 같은 기간과 오차 기준의 비교를 통과하지 않았습니다.')
    return dict(previous,
                metric=dict(previous['metric'], hits=metric['hits'], total=metric['total'], percent=metric['percent']),
                error=dict(previous['error'], mae=result['mae_percentage_points']),
                baseline_metric=previous['metric'], baseline_error=previous['error'],
                evaluation_scope='2024-01~2025-06의 고정 288개 관측. 기존 시험 기간을 재사용한 후향평가입니다.',
                promoted=True)


def operating_evaluation(root):
    v20 = get_model_evaluation(root)
    rows = []
    for historical in v20['models']:
        ident = historical['id']
        row = _audience_row(root, historical) if ident == 'audience_distribution' else dict(historical)
        row['active'] = ident in ACTIVE
        row['decision'] = DECISIONS[ident]
        if row['active'] and (not row['metric'] or row['metric']['percent'] < TARGET):
            raise ValueError('운영 모델의 고정 평가가 90% 기준을 충족하지 못합니다.')
        rows.append(row)
    return {'service_version': 23, 'date_kst': '2026-11-06', 'target_percent': TARGET,
            'active_count': len(ACTIVE), 'models': rows,
            'field_accuracy_proven': False,
            'notes': ['구성비 비율은 기존 허용오차 이내의 과거 관측 비율입니다.',
                      '공식 소개 검색은 출처 기반 작성 질의 22건의 평가이며, 실제 사용자의 검색 정확도는 별도 검증이 필요합니다.']}


def operating_model_info(root):
    evidence = operating_evaluation(root)
    cards = [dict(row, available=True, usage=USAGE[row['id']]) for row in evidence['models'] if row['active']]
    return {'service_version': 23, 'cards': cards, 'models': cards,
            'runtime': 'offline_cpu', 'requires_cloud': False, 'requires_gpu': False}
