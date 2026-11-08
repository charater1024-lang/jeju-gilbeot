"""Temporal evaluation of a partially pooled 1048 seasonal composition model."""

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

SOURCE = 'data_raw/hub/hub_1048_5832.csv'
FOLDS = [('2022-06', '2022-07', '2022-12'), ('2022-12', '2023-01', '2023-06'),
         ('2023-06', '2023-07', '2023-12')]
TEST = ('2024-01', '2025-06')
FIT_CUTOFF = '2023-12'
THRESHOLD = .01
TARGET = 90.0
GUARD = 1.02
INCUMBENT = {'window': 12, 'half_life': 6, 'harmonics': 2, 'alpha': 10.}
CANDIDATES = [dict(window=w, half_life=h, seasonal_deviation_ridge=s,
                   forecast_months_forward=t, scale=k)
              for w, h, s, t, k in itertools.product(
                  (18, 30, 42, 60), (6, 12), (2., 10.), (0., 3., 6.), ('share', 'clr'))]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def read(path):
    return json.loads(path.read_text('utf-8'))


def ordinal(month):
    year, m = map(int, month.split('-'))
    return year * 12 + m


def design(month, sign, trend):
    angle = month * 2 * math.pi / 12
    harmonics = [math.sin(angle), math.cos(angle), math.sin(2 * angle), math.cos(2 * angle)]
    return [1., sign, *harmonics, *(value * sign for value in harmonics), trend, trend * sign]


def sign_for(group):
    if group == 'resident':
        return -1.
    if group == 'tourist':
        return 1.
    raise ValueError('Unexpected audience group.')


def train_candidate(rows, config, solve):
    # Per-group intercepts with shared seasonal effects and penalized deviations.
    end = max(ordinal(row['month']) for row in rows)
    rows = [row for row in rows if ordinal(row['month']) > end - config['window']]
    penalties = [1e-9, 1e-9] + [2.] * 4 + [config['seasonal_deviation_ridge']] * 4 + [8., 16.]
    gram = [[0.] * len(penalties) for _ in penalties]
    targets = [[0.] * len(penalties) for _ in rows[0]['shares']]
    for row in rows:
        age = ordinal(row['month']) - end
        features = design(row['calendar_month'], sign_for(row['audience']), age / 12)
        actual = row['shares']
        if config['scale'] == 'clr':
            logs = [math.log(max(share, 1e-10)) for share in actual]
            center = math.fsum(logs) / len(logs)
            actual = [value - center for value in logs]
        weight = 2 ** (age / config['half_life'])
        for column, feature in enumerate(features):
            weighted_feature = weight * feature
            for other_column, other_feature in enumerate(features):
                gram[column][other_column] += weighted_feature * other_feature
            for target, share in zip(targets, actual):
                target[column] += weighted_feature * share
    for column, penalty in enumerate(penalties):
        gram[column][column] += penalty
    coefficients = [solve(gram, target) for target in targets]
    tables = {}
    for group in ('resident', 'tourist'):
        table = []
        for month in range(1, 13):
            features = design(month, sign_for(group), config['forecast_months_forward'] / 12)
            future = [math.fsum(weight * feature for weight, feature in zip(target, features))
                      for target in coefficients]
            if config['scale'] == 'clr':
                peak = max(future)
                future = [math.exp(value - peak) for value in future]
            positive = [max(value, 1e-10) for value in future]
            total = math.fsum(positive)
            table.append([value / total for value in positive])
        tables[group] = table
    return tables


def candidate_predictions(audience, train, rows, config):
    tables = train_candidate(train, config, audience._solve)
    return [tables[row['audience']][row['calendar_month'] - 1] for row in rows]


def incumbent_predictions(audience, train, rows):
    coefficients = audience._fit_ridge(train, INCUMBENT)
    return [audience._predict_ridge(coefficients, row['audience'], row['calendar_month'], INCUMBENT)
            for row in rows]


def metrics(rows, predictions):
    errors = [abs(actual - prediction)
              for row, predicted in zip(rows, predictions)
              for actual, prediction in zip(row['shares'], predicted)]
    hits = sum(error <= THRESHOLD + 1e-12 for error in errors)
    return {'hits': hits, 'total': len(errors), 'percent': 100 * hits / len(errors),
            'mae_percentage_points': 100 * math.fsum(errors) / len(errors)}


def combined_validation(audience, rows, candidate):
    observed, predicted = [], []
    for fit_end, start, end in FOLDS:
        train = [r for r in rows if r['month'] <= fit_end]
        validation = [r for r in rows if start <= r['month'] <= end]
        observed.extend(validation)
        if candidate is None:
            predicted.extend(incumbent_predictions(audience, train, validation))
        else:
            predicted.extend(candidate_predictions(audience, train, validation, candidate))
    return metrics(observed, predicted)


def selection_stage(audience, panels, audit, output):
    protocol = dict(source=SOURCE, source_sha256=audit['source_sha256'], candidate_family='pooled season and damped level',
                    folds=FOLDS, test=TEST, fit_cutoff=FIT_CUTOFF, test_cells=288,
                    target_percent=TARGET, threshold_percentage_points=100*THRESHOLD,
                    test_previously_seen=True, selection='maximize dev hit among MAE<=102% of v20',
                    ties='dev MAE then fixed order', candidates=CANDIDATES,
                    release='>=90% on full fixed test, v20 MAE guard, group and month-only parity')
    write(output/'protocol.json', protocol)
    eligible_panels = [r for r in panels if r['month'] <= FIT_CUTOFF]
    baseline = combined_validation(audience, eligible_panels, None)
    candidates = []
    for index, candidate in enumerate(CANDIDATES):
        measured = combined_validation(audience, eligible_panels, candidate)
        candidates.append(dict(index=index, config=candidate, validation=measured,
                               guard_pass=measured['mae_percentage_points'] <= GUARD*baseline['mae_percentage_points']))
    eligible = [candidate for candidate in candidates if candidate['guard_pass']]
    selected = min(eligible, key=lambda c: (-c['validation']['hits'], c['validation']['mae_percentage_points'], c['index'])) if eligible else None
    receipt = dict(protocol_sha256=digest(protocol), selected=selected, validation_incumbent=baseline,
                   tested_candidates=candidates, test_used_for_selection=False)
    write(output/'selection.json', receipt)
    return {'selected': selected, 'baseline_validation': baseline, 'eligible': len(eligible)}


def test_stage(audience, panels, audit, output):
    protocol = read(output/'protocol.json')
    receipt = read(output/'selection.json')
    if receipt['protocol_sha256'] != digest(protocol) or audit['source_sha256'] != protocol['source_sha256']:
        raise ValueError('Frozen protocol or data does not match selection.')
    selected = receipt['selected']
    if not selected:
        return None
    train = [r for r in panels if r['month'] <= FIT_CUTOFF]
    test = [r for r in panels if TEST[0] <= r['month'] <= TEST[1]]
    incumbent = metrics(test, incumbent_predictions(audience, train, test))
    if incumbent['total'] != 288 or incumbent['hits'] != 252 or abs(incumbent['mae_percentage_points']-.426111)>1e-6:
        raise ValueError('1048 test cohort or comparator differs from v20.')
    predictions = candidate_predictions(audience, train, test, selected['config'])
    chosen = metrics(test, predictions)
    promote = chosen['percent'] >= TARGET and chosen['mae_percentage_points'] <= GUARD*incumbent['mae_percentage_points']
    by_panel = {(r['month'], r['audience']): predicted for r, predicted in zip(test, predictions)}
    detailed = audience._measure(test, lambda row: by_panel[(row['month'], row['audience'])])
    cohort = [{'month': r['month'], 'audience': r['audience'], 'shares': r['shares']} for r in test]
    report = dict(protocol_sha256=digest(protocol), selection_sha256=digest(receipt), candidate=selected,
                  incumbent_test=incumbent, candidate_test=chosen, passes_gate=promote,
                  observed_period={'start': panels[0]['month'], 'end': panels[-1]['month']},
                  test_period={'start': TEST[0], 'end': TEST[1]}, test_panel_count=len(test),
                  test_cohort_sha256=digest(cohort), test_fit_cutoff=FIT_CUTOFF,
                  candidate_test_detail=detailed, test_status='previously_seen_retrospective_fixed_period_not_pristine_external_holdout')
    write(output/'result.json', report)
    if promote:
        tables = train_candidate(panels, selected['config'], audience._solve)
        profiles = {group: {str(month): shares for month, shares in enumerate(table, 1)}
                    for group, table in tables.items()}
        model = dict(schema_version=1, dataset_id='1048', algorithm='recency_weighted_pooled_seasonal_trend_ridge_composition',
                     selected_serving_model='pooled_seasonal_trend_ridge_v23',
                     categories=audience.CATEGORIES, groups=audience.GROUPS, monthly_profiles=profiles,
                     serving_fit_scope='all_observed_months_after_evaluation',
                     source_sha256=audit['source_sha256'], experiment=report,
                     runtime_dependencies='python standard library only', runtime_llm=False)
        model['model_sha256'] = digest(model)
        write(output/'serving_profile.json', model)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=('validation', 'test'), required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    sys.path.insert(0, str(args.root))
    from jeju_agent import audience_model

    panels, audit = audience_model.read_panels(args.root/SOURCE)
    operation = selection_stage if args.stage == 'validation' else test_stage
    result = operation(audience_model, panels, audit, args.output)
    if result is None:
        print('No eligible candidate. Test was not opened.')
    else:
        print(json.dumps(result, ensure_ascii=False))
