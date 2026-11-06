"""Measure the incremental value of a fixed-lead forecast for Hub 561 ridership."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '2')
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

VAR = ('temperature_2m', 'precipitation', 'wind_speed_10m')
FEATURES = ('mean_temperature_c', 'log_daily_precipitation_mm', 'wet_hours', 'max_wind_kmh')
CONFIGS = tuple(
    dict(family=family, loss=loss, leaves=leaves, blend=blend)
    for family, loss, leaves in (
        ('ridge', 'squared_error', None), ('hgb', 'absolute_error', 7),
        ('hgb', 'absolute_error', 15), ('hgb', 'squared_error', 7),
        ('hgb', 'squared_error', 15),
    ) for blend in (.35, .65, 1.)
)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text('utf-8'))


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n', 'utf-8')


def weather_by_date(raw):
    if raw.get('utc_offset_seconds') != 32400:
        raise ValueError('The weather snapshot must use KST.')
    hourly = raw['hourly']
    columns = [hourly[f'{variable}_previous_day2'] for variable in VAR]
    times = hourly['time']
    if len(times) % 24 or any(len(c) != len(times) for c in columns):
        raise ValueError('Hourly archive is not day-aligned.')
    weather = {}
    for first in range(0, len(times), 24):
        day = times[first][:10]
        if day in weather or times[first:first+24] != [f'{day}T{hour:02d}:00' for hour in range(24)]:
            raise ValueError('Duplicate or incomplete hourly timestamps.')
        values = [column[first:first+24] for column in columns]
        if any(value is None or not math.isfinite(value) for column in values for value in column):
            continue
        temperature, rain, wind = values
        if min(rain) < 0 or min(wind) < 0:
            raise ValueError('Invalid precipitation or wind value.')
        weather[day] = (sum(temperature)/24, math.log1p(sum(rain)), sum(value >= .1 for value in rain), max(wind))
    return weather


def arrays(data, weather):
    day = data.ordinals
    weekday = data.weekday
    year_phase = 2*np.pi*day/365.25
    week_phase = 2*np.pi*weekday/7
    code = data.code if len(data.groups) <= 255 else np.zeros(len(day))
    calendar = np.column_stack((code, weekday, [d.month for d in data.dates], np.log1p(data.baseline),
                                np.sin(week_phase), np.cos(week_phase), np.sin(year_phase), np.cos(year_phase)))
    forecasts = np.array([weather.get(d.isoformat(), (np.nan,)*len(FEATURES)) for d in data.dates])
    available = np.all(np.isfinite(forecasts), axis=1)
    return calendar, forecasts, available


def predict(config, train, target, train_arrays, target_arrays, *, include_weather):
    train_calendar, train_weather, fit_available = train_arrays
    target_calendar, target_weather, target_available = target_arrays
    if config['family'] == 'ridge':
        train_calendar, target_calendar = train_calendar[:, 3:], target_calendar[:, 3:]
    if include_weather:
        train_calendar = np.column_stack((train_calendar, train_weather))
        target_calendar = np.column_stack((target_calendar, target_weather))
    # Match training coverage and fallback in the paired control even without weather inputs.
    if not np.any(fit_available) or not np.any(target_available):
        raise ValueError('Missing forecast coverage in a chronological fold.')
    y = np.clip(train.actual / np.maximum(train.baseline, 1.), .35, 2.8)
    weights = 2. ** (-(train.ordinals.max() - train.ordinals) / 180)
    if config['family'] == 'ridge':
        model = Ridge(alpha=50.)
    else:
        model = HistGradientBoostingRegressor(loss=config['loss'], max_iter=85, learning_rate=.06,
            max_leaf_nodes=config['leaves'], min_samples_leaf=80, l2_regularization=1.,
            categorical_features=[0, 1, 2], early_stopping=False, random_state=56122)
    model.fit(train_calendar[fit_available], y[fit_available], sample_weight=weights[fit_available])
    factor = np.ones(len(target.actual))
    factor[target_available] = np.clip(model.predict(target_calendar[target_available]), .70, 1.40)
    return factor


def adjustment(baseline, factor, config):
    return baseline * (1. + config['blend']*(factor-1.))


def run(args):
    began = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.root / 'scripts'))
    sys.path.insert(0, str(args.root))
    from experiment_bus_calendar_v21 import paired_data, score
    from jeju_agent.route_demand import read_observations

    path = args.root / 'models_candidates_v20/bus/561'
    prior = read(path / 'experiment_report.json')
    split = prior['protocol']['split']
    source = args.root / 'data_raw/hub/hub_561_5842.csv'
    if digest(source) != prior['raw_audit']['source_sha256']:
        raise ValueError('Original observations differ from the frozen protocol.')
    if args.observations_cache:
        if digest(args.observations_cache) != prior['raw_audit']['cache_sha256']:
            raise ValueError('Observation cache does not match the v20 extraction.')
        observations = [r for r in read(args.observations_cache) if re.fullmatch(r'\d{1,4}(?:-\d{1,3})?', r['route_id'])]
    else:
        observations, _ = read_observations(source)
    receipt = read(args.weather_receipt)
    if receipt['lead_hours'] != 48 or digest(args.weather) != receipt['sha256']:
        raise ValueError('Weather forecast archive differs from the acquisition receipt.')
    weather = weather_by_date(read(args.weather))
    protocol = dict(schema_version=1, target='561 daily general ridership', split=split,
                    raw_source_sha256=prior['raw_audit']['source_sha256'], forecast_receipt=receipt,
                    forecast_features=FEATURES, complete_forecast_days=len(weather),
                    candidates=list(CONFIGS), paired_control='same model, fit/target dates, and fallback without weather features',
                    selection='choose highest mean dev hit among weather candidates with MAE <= 1.02 times v20; freeze before fixed test',
                    gate='dev and test hit must exceed active v20 and test hit must exceed paired control, MAE no worse than 1.02x active v20',
                    coverage='all original cells evaluated; forecasts with missing hours use unchanged v20 prediction',
                    no_observed_weather=True, old_test_previously_seen=True,
                    libraries={'numpy':np.__version__, 'scikit_learn':sklearn.__version__})
    write(args.output/'protocol.json', protocol)
    results = [[] for _ in CONFIGS]
    coverage = []
    baseline_val = []
    for fold in split['fold_dates']:
        train, target, _, _ = paired_data(observations, fold['fit_end'], fold['validation_start'], fold['validation_end'])
        tr, te = arrays(train, weather), arrays(target, weather)
        coverage.append(dict(fit_end=fold['fit_end'], fit_cells=int(tr[2].sum()), total_fit_cells=len(tr[2]),
                             test_cells=int(te[2].sum()), total_test_cells=len(te[2])))
        baseline_val.append(score(target.actual, target.baseline))
        fits = {}
        for i, config in enumerate(CONFIGS):
            key = config['family'], config['loss'], config['leaves']
            if key not in fits:
                fits[key] = {wx: predict(config, train, target, tr, te, include_weather=wx) for wx in (False, True)}
            results[i].append({('weather' if wx else 'calendar_control'): score(target.actual, adjustment(target.baseline, factor, config))
                               for wx, factor in fits[key].items()})
        print('validation completed', fold['fit_end'], coverage[-1], round(time.monotonic()-began, 1), flush=True)

    def mean(rows, metric):
        return float(np.mean([row['within_20_percent']['percent'] if metric == 'hit' else row[metric] for row in rows]))

    trials = []
    for config, folds in zip(CONFIGS, results):
        measured = [f['weather'] for f in folds]
        trials.append(dict(config=config, validation=folds, weather_mean_hit=mean(measured, 'hit'),
                           weather_mean_mae=mean(measured, 'mae'), mae_guard=mean(measured, 'mae') <= 1.02*mean(baseline_val, 'mae')))
    allowed = [row for row in trials if row['mae_guard']]
    if not allowed:
        write(args.output/'result.json', dict(trials=trials, validation_v20=baseline_val, passes_gate=False, reason='validation MAE'))
        return
    chosen = max(allowed, key=lambda row: (row['weather_mean_hit'], -row['weather_mean_mae']))
    write(args.output/'selection_freeze.json', dict(protocol_sha256=digest(args.output/'protocol.json'),
        selected=chosen, trials=trials, validation_v20=baseline_val, test_used_to_select=False))
    train, target, target_rows, groups = paired_data(observations, split['final_fit_end'], split['test_start'], split['test_end'])
    assert sorted(groups) == split['evaluation_groups'] and len(target_rows) == split['test_count']
    tr, te = arrays(train, weather), arrays(target, weather)
    baseline = score(target.actual, target.baseline)
    assert baseline['within_20_percent']['hits'] == 13535 and abs(baseline['mae'] - 4.966360529688168) < 1e-8
    measured = {}
    for wx in (False, True):
        factor = predict(chosen['config'], train, target, tr, te, include_weather=wx)
        predicted = adjustment(target.baseline, factor, chosen['config'])
        assert np.array_equal(predicted[~te[2]], target.baseline[~te[2]])
        measured['weather' if wx else 'calendar_control'] = score(target.actual, predicted)
    winner, control = measured['weather'], measured['calendar_control']
    passes = (chosen['weather_mean_hit'] > mean(baseline_val, 'hit') and
              winner['within_20_percent']['hits'] > max(baseline['within_20_percent']['hits'], control['within_20_percent']['hits']) and
              winner['mae'] <= 1.02*baseline['mae'])
    report = dict(protocol_sha256=digest(args.output/'protocol.json'), selection_sha256=digest(args.output/'selection_freeze.json'),
                  validation_v20=baseline_val, selected=chosen, fit_validation_coverage=coverage,
                  test=dict(v20=baseline, **measured), test_fit_cells=int(tr[2].sum()),
                  test_weather_cells=int(te[2].sum()), test_weather_days=len(set(d for d, m in zip(target.dates, te[2]) if m)),
                  test_total_days=len(set(target.dates)), passes_gate=passes, elapsed_seconds=time.monotonic()-began)
    write(args.output/'result.json', report)
    print(json.dumps(dict(test=report['test'], gate=passes, weather_days=report['test_weather_days'],
                         elapsed=report['elapsed_seconds']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--weather', type=Path, required=True)
    parser.add_argument('--weather-receipt', type=Path, required=True)
    parser.add_argument('--observations-cache', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
