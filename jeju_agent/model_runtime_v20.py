"""Serve the two candidates that passed the v20 release checks."""
from .bus_v20 import get_bus_candidate
from .retrieval_v20 import rerank_candidates
from .route_demand import get_route_demand
from .tourism import search_tourism


def active_route_demand(root, *, route=None, date=None, limit=8):
    """Keep the verified source-code scope and apply the new weekday estimate."""
    result = get_route_demand(root, route=route, date=date, limit=limit)
    candidate = get_bus_candidate(root, '561', result['requested_date'])
    previous = result['metrics']
    measured = candidate['metrics']
    prior_test = candidate['incumbent_metrics']
    population = candidate['evaluation_population']
    by_code = {item['group']: item for item in candidate['predictions']}
    expected = {item['route_id']: item['history_last_date'] for item in result['route_options']}
    if (
        candidate['release_gate']['promotable'] is not True
        or candidate['release_gate']['test_used_to_reselect'] is not False
        or candidate['config']['family'] != 'weekday_summary'
        or candidate['config']['statistic'] != 'median'
        or candidate['fit_period'] != result['fit_period']
        or candidate['observation_period'] != result['observation_period']
        or candidate['evaluation_group_count'] != previous['evaluation_route_count']
        or candidate['serving_group_count'] != previous['serving_route_count']
        or {key: item['history_last_date'] for key, item in by_code.items()} != expected
        or population['test_all_source_cells'] != previous['all_test_observed_cells']
        or any(population['test_' + edge] != previous['evaluation_period'][edge] for edge in ('start', 'end'))
        or any(prior_test['within_20_percent'][key] != previous['within_20_percent'][key]
               for key in ('hits', 'denominator', 'excluded_zero_actual'))
        or measured['within_20_percent']['denominator'] != prior_test['within_20_percent']['denominator']
        or measured['within_20_percent']['hits'] < prior_test['within_20_percent']['hits']
        or measured['mae'] > prior_test['mae'] * 1.02
    ):
        raise ValueError('노선 승차 모델의 배포 검증과 평가 범위를 확인해 주세요.')

    for item in result['items']:
        code = item['route_id']
        group_test = candidate['test_by_group'].get(code)
        item['prediction'] = round(by_code[code]['prediction'], 1)
        item['test_mae'] = round(group_test['mae'], 2) if group_test else None
        item['test_observations'] = group_test['observations'] if group_test else 0

    tolerance = dict(previous['within_20_percent'], **measured['within_20_percent'])
    previous.update(mae=measured['mae'], wape_percent=measured['wape_percent'],
                    within_20_percent=tolerance)
    previous.pop('mae_reduction_percent', None)
    improvement = measured['within_20_percent']['percent'] - prior_test['within_20_percent']['percent']
    mae_increase = 100 * (measured['mae'] / prior_test['mae'] - 1)
    note = (f'같은 과거 평가에서 ±20% 이내 비율이 {improvement:.2f}퍼센트포인트 올랐고 '
            f'평균절대오차는 {mae_increase:.2f}% 늘었습니다.')
    previous['evaluation_note'] = note
    result['limitations'] = result['limitations'] + [note]
    result['algorithm'] = 'recency_weighted_route_weekday_median_v20'
    result['model'] = {'algorithm': result['algorithm'], 'source_id': '561',
                       'half_life_days': candidate['config']['half_life'],
                       'evaluation_scope': 'historical_fixed_test', 'runtime_llm': False}
    return result


def active_tourism_search(root, body=None):
    """Rerank the first five approved results of an ordinary text search."""
    result = search_tourism(root, body)
    query = result['applied_filters']['query']
    if (not query or result['offset'] != 0 or result['limit'] < 5
            or result['location_status'] != 'not_provided'):
        return result
    status = {}
    result['items'] = rerank_candidates(root, query, result['items'], domain='tourism', status=status)
    if status.get('applied'):
        result['model']['reranking'] = {
            'scope': 'same_first_five_records_only',
            'evaluation_scope': 'curated_source_grounded_queries',
            'evaluation_endpoint': '/api/model-evaluation',
            'runtime_llm': False,
        }
    return result
