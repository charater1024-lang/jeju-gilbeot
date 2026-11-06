"""Serve the frozen and verified Hub 1048 v23 month-only profiles."""

import calendar
from copy import deepcopy
import datetime as dt
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

from .audience_model import CATEGORIES, GROUPS, _hash, _load as load_incumbent


PROFILE_DIR = 'models_candidates_v23/audience'
SOURCE_FILE = 'data_raw/hub/hub_1048_5832.csv'
SOURCE_URL = 'https://www.jejudatahub.net/data/view/data/1048'
ALGORITHM = 'recency_weighted_pooled_seasonal_trend_ridge_composition'
SERVING_MODEL = 'pooled_seasonal_trend_ridge_v23'
TEST_PERIOD = {'start': '2024-01', 'end': '2025-06'}
OBSERVATION_PERIOD = {'start': '2018-01', 'end': '2025-06'}
TEST_SCOPE = 'previously_seen_retrospective_fixed_period_not_pristine_external_holdout'


def _read(path):
    return json.loads(Path(path).read_text('utf-8'))


def _stamp(path):
    info = path.stat()
    return str(path.resolve()), info.st_mtime_ns, info.st_size


def _valid_shares(shares):
    return (isinstance(shares, list) and len(shares) == len(CATEGORIES)
            and all(type(share) in (int, float) and math.isfinite(share) and 0 <= share <= 1 for share in shares)
            and abs(sum(shares) - 1) < 1e-8)


@lru_cache(maxsize=8)
def _load_bundle(protocol_stamp, selection_stamp, result_stamp, profile_stamp, incumbent_stamp, source_stamp):
    protocol = _read(protocol_stamp[0])
    selection = _read(selection_stamp[0])
    report = _read(result_stamp[0])
    profile = _read(profile_stamp[0])
    incumbent = load_incumbent(*incumbent_stamp[:2])
    expected_source = incumbent['source_sha256']
    claimed_profile_hash = profile.pop('model_sha256', None)
    if not (claimed_profile_hash == _hash(profile)
            and profile.get('experiment') == report
            and selection.get('protocol_sha256') == report.get('protocol_sha256') == _hash(protocol)
            and report.get('selection_sha256') == _hash(selection)
            and profile.get('source_sha256') == protocol.get('source_sha256') == expected_source
            and protocol.get('source') == SOURCE_FILE):
        raise ValueError('소비 모델과 학습·평가 기록의 해시 또는 출처가 일치하지 않습니다.')
    if source_stamp and hashlib.sha256(Path(source_stamp[0]).read_bytes()).hexdigest() != expected_source:
        raise ValueError('소비 모델과 원자료의 해시가 일치하지 않습니다.')

    candidate = selection.get('selected')
    heldout = report.get('candidate_test', {})
    baseline = report.get('incumbent_test', {})
    detailed = report.get('candidate_test_detail', {})
    if not (profile.get('schema_version') == 1 and profile.get('dataset_id') == '1048'
            and profile.get('algorithm') == ALGORITHM and profile.get('selected_serving_model') == SERVING_MODEL
            and profile.get('categories') == CATEGORIES and profile.get('groups') == GROUPS
            and profile.get('runtime_llm') is False
            and profile.get('serving_fit_scope') == 'all_observed_months_after_evaluation'
            and report.get('candidate') == candidate and candidate and candidate.get('guard_pass') is True
            and selection.get('test_used_for_selection') is False and report.get('passes_gate') is True
            and protocol.get('test') == [TEST_PERIOD['start'], TEST_PERIOD['end']]
            and protocol.get('threshold_percentage_points') == 1.0
            and report.get('test_status') == TEST_SCOPE and report.get('test_fit_cutoff') == '2023-12'
            and report.get('test_period') == TEST_PERIOD and report.get('observed_period') == OBSERVATION_PERIOD
            and report.get('test_panel_count') == 36 and len(report.get('test_cohort_sha256', '')) == 64
            and heldout.get('total') == baseline.get('total') == detailed.get('category_observations') == 288
            and type(heldout.get('hits')) is int and 260 <= heldout['hits'] <= 288
            and abs(heldout.get('percent', -1) - 100*heldout['hits']/288) < 1e-8
            and baseline.get('hits') == 252
            and abs(baseline.get('mae_percentage_points', -1) - incumbent['metrics']['test']['model']['mae_percentage_points']) < 1e-6
            and 0 <= heldout.get('mae_percentage_points', -1) <= 1.02*baseline['mae_percentage_points']
            and abs(detailed.get('mae_percentage_points', -1) - heldout['mae_percentage_points']) < 1e-6):
        raise ValueError('소비 모델의 평가 범위 또는 운영 채택 기준을 확인하세요.')

    profiles = profile.get('monthly_profiles')
    if not isinstance(profiles, dict) or set(profiles) != set(GROUPS):
        raise ValueError('소비 모델의 집단별 표가 유효하지 않습니다.')
    months = {str(month) for month in range(1, 13)}
    if any(not isinstance(table, dict) or set(table) != months or not all(map(_valid_shares, table.values()))
           for table in profiles.values()):
        raise ValueError('소비 모델의 월별 구성비가 유효하지 않습니다.')

    test_metrics = dict(incumbent['metrics']['test'])
    test_metrics['incumbent_same_fit'] = test_metrics['model']
    test_metrics['model'] = {**detailed, 'within_tolerance': {
        'threshold_percentage_points': 1., 'hits': heldout['hits'],
        'total': heldout['total'], 'percent': heldout['percent']},
        'evaluation_scope': TEST_SCOPE, 'test_period': TEST_PERIOD}
    return {'profiles': profiles, 'report': report, 'source': incumbent['metrics']['source'],
            'metrics': test_metrics, 'model': {
                'algorithm': ALGORITHM, 'selected_serving_model': SERVING_MODEL, 'version': 23,
                'config': candidate['config'], 'source_sha256': expected_source, 'model_sha256': claimed_profile_hash,
                'monthly_periodicity': True, 'serving_fit_scope': profile['serving_fit_scope']},
            'selection': {'selected': SERVING_MODEL, 'config': candidate['config'],
                          'candidate_count': len(protocol['candidates']), 'test_used_for_selection': False}}


def _bundle(root):
    root = Path(root)
    source = root/SOURCE_FILE
    inputs = [_stamp(root/PROFILE_DIR/name) for name in ('protocol.json', 'selection.json', 'result.json', 'serving_profile.json')]
    try:
        return _load_bundle(*inputs, _stamp(root/'models_audience/audience_model.json'), _stamp(source) if source.is_file() else None)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError('소비 모델 검증 자료가 올바른 형식이 아닙니다.') from exc


def audience_status_v23(root):
    bundle = _bundle(root)
    return deepcopy({'available': True, 'observation_period': OBSERVATION_PERIOD,
                     'selection': bundle['selection'], 'metrics': bundle['metrics'],
                     'source': bundle['source'], 'model': bundle['model'],
                     'evaluation_scope': TEST_SCOPE})


def predict_audience_v23(root, audience='resident', month=1):
    """Return the existing consumption API shape using only the approved profile."""
    if not isinstance(audience, str) or audience not in GROUPS:
        raise ValueError('이용 모드는 resident 또는 tourist여야 합니다.')
    if type(month) not in (int, str) or str(month) not in {str(i) for i in range(1, 13)}:
        raise ValueError('월은 1~12 정수여야 합니다.')
    bundle = _bundle(root)
    shares = bundle['profiles'][audience][str(month)]
    ranked = sorted(zip(CATEGORIES, shares), key=lambda pair: (-pair[1], pair[0]))
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    year, m = map(int, OBSERVATION_PERIOD['end'].split('-'))
    age = (today - dt.date(year, m, calendar.monthrange(year, m)[1])).days
    return {'status': 'historical_pattern', 'audience': audience,
            'audience_label': '도민 모드' if audience == 'resident' else '관광객 모드',
            'data_group_label': '원자료 '+GROUPS[audience]+' 구간', 'month': int(month),
            'source_id': '1048', 'source_url': SOURCE_URL, 'observation_period': dict(OBSERVATION_PERIOD),
            'data_age_days': age, 'is_stale': age > 90,
            'categories': [{'id': CATEGORIES.index(name), 'name': name, 'share': round(share, 6), 'rank': i+1}
                           for i, (name, share) in enumerate(ranked)],
            'model': deepcopy(bundle['model']), 'metrics': deepcopy(bundle['metrics']),
            'warnings': ['제주 전체 8개 식음료 업종의 과거 이용건수로 학습한 집단별 참고값입니다.',
                         '관광객 모드는 원자료 내국인 구간을 참고합니다.',
                         f"자료의 마지막 관측월은 {OBSERVATION_PERIOD['end']}입니다. 현재 소비와 점포별 수요는 별도 자료가 필요합니다."]}
