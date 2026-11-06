"""Temporal evaluation of a partially pooled 1048 seasonal composition model."""

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import numpy as np

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
    angle = month * 2*np.pi/12
    harmonics = np.column_stack((np.sin(angle), np.cos(angle), np.sin(2*angle), np.cos(2*angle)))
    return np.column_stack((np.ones_like(month), sign, harmonics, harmonics*sign[:, None], trend, trend*sign))


def sign_for(group):
    if group == 'resident':
        return -1.
    if group == 'tourist':
        return 1.
    raise ValueError('Unexpected audience group.')


def train_candidate(rows, config):
    # Per-group intercepts with shared seasonal effects and penalized deviations.
    end = max(ordinal(row['month']) for row in rows)
    rows = [row for row in rows if ordinal(row['month']) > end-config['window']]
    age = np.array([ordinal(row['month'])-end for row in rows], float)
    month = np.array([row['calendar_month'] for row in rows], float)
    sign = np.array([sign_for(row['audience']) for row in rows])
    x = design(month, sign, age/12)
    actual = np.asarray([row['shares'] for row in rows], float)
    if config['scale'] == 'clr':
        actual = np.log(np.maximum(actual, 1e-10))
        actual -= actual.mean(axis=1, keepdims=True)
    weights = 2**(age/config['half_life'])
    penalties = [1e-9, 1e-9] + [2.]*4 + [config['seasonal_deviation_ridge']]*4 + [8., 16.]
    coef = np.linalg.solve(x.T @ (weights[:, None]*x) + np.diag(penalties),
                           x.T @ (weights[:, None]*actual))
    tables = {}
    for group in ('resident', 'tourist'):
        future = design(np.arange(1, 13), np.full(12, sign_for(group)),
                        np.full(12, config['forecast_months_forward']/12)) @ coef
        if config['scale'] == 'clr':
            future = np.exp(future - future.max(axis=1, keepdims=True))
        future = np.maximum(future, 1e-10)
        tables[group] = future/future.sum(axis=1, keepdims=True)
    return tables


def candidate_predictions(train, rows, config):
    tables = train_candidate(train, config)
    return [tables[row['audience']][row['calendar_month']-1] for row in rows]


def incumbent_predictions(audience, train, rows):
    coefficients = audience._fit_ridge(train, INCUMBENT)
    return [audience._predict_ridge(coefficients, row['audience'], row['calendar_month'], INCUMBENT)
            for row in rows]


def metrics(rows, predictions):
    errors = np.abs(np.asarray([row['shares'] for row in rows])-np.asarray(predictions))
    hits = int((errors <= THRESHOLD + 1e-12).sum())
    return {'hits': hits, 'total': int(errors.size), 'percent': 100*hits/errors.size,
            'mae_percentage_points': float(100*errors.mean())}


def combined_validation(audience, rows, candidate):
    observed, predicted = [], []
    for fit_end, start, end in FOLDS:
        train = [r for r in rows if r['month'] <= fit_end]
        validation = [r for r in rows if start <= r['month'] <= end]
        observed.extend(validation)
        if candidate is None:
            predicted.extend(incumbent_predictions(audience, train, validation))
        else:
            predicted.extend(candidate_predictions(train, validation, candidate))
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
    print(json.dumps({'selected': selected, 'baseline_validation': baseline, 'eligible': len(eligible)}, ensure_ascii=False))


def test_stage(audience, panels, audit, output):
    protocol = read(output/'protocol.json')
    receipt = read(output/'selection.json')
    if receipt['protocol_sha256'] != digest(protocol) or audit['source_sha256'] != protocol['source_sha256']:
        raise ValueError('Frozen protocol or data does not match selection.')
    selected = receipt['selected']
    if not selected:
        print('No eligible candidate. Test was not opened.')
        return
    train = [r for r in panels if r['month'] <= FIT_CUTOFF]
    test = [r for r in panels if TEST[0] <= r['month'] <= TEST[1]]
    incumbent = metrics(test, incumbent_predictions(audience, train, test))
    if incumbent['total'] != 288 or incumbent['hits'] != 252 or abs(incumbent['mae_percentage_points']-.426111)>1e-6:
        raise ValueError('1048 test cohort or comparator differs from v20.')
    predictions = candidate_predictions(train, test, selected['config'])
    chosen = metrics(test, predictions)
    promote = chosen['percent'] >= TARGET and chosen['mae_percentage_points'] <= GUARD*incumbent['mae_percentage_points']
    by_panel = {(r['month'], r['audience']): predicted.tolist() for r, predicted in zip(test, predictions)}
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
        tables = train_candidate(panels, selected['config'])
        profiles = {group: {str(month+1): share.tolist() for month, share in enumerate(table)}
                    for group, table in tables.items()}
        if any(not np.array_equal(np.asarray(list(profiles[group].values())), table)
               for group, table in tables.items()):
            raise ValueError('Monthly profile export differs from learned probabilities.')
        model = dict(schema_version=1, dataset_id='1048', algorithm='recency_weighted_pooled_seasonal_trend_ridge_composition',
                     selected_serving_model='pooled_seasonal_trend_ridge_v23',
                     categories=audience.CATEGORIES, groups=audience.GROUPS, monthly_profiles=profiles,
                     serving_fit_scope='all_observed_months_after_evaluation',
                     source_sha256=audit['source_sha256'], experiment=report,
                     runtime_dependencies='python standard library only', runtime_llm=False)
        model['model_sha256'] = digest(model)
        write(output/'serving_profile.json', model)
    print(json.dumps(report, ensure_ascii=False))


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
    operation(audience_model, panels, audit, args.output)
