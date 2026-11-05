"""CPU LSTM benchmark. Seven-day observation cutoff; no serving dependency."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
import numpy as np


SEED = 56121
HORIZON = 7
CONFIGS = [{'lookback': 14, 'hidden': 8}, {'lookback': 21, 'hidden': 12}]
EPOCHS = 6
BATCH = 512
SAMPLES_PER_EPOCH = 65000


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n', 'utf-8')


def file_hash(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def metrics(actual, pred):
    error = np.abs(actual - pred)
    assert np.all(actual > 0) and np.all(np.isfinite(pred))
    hits = int((error <= 0.2 * actual + 1e-10).sum())
    return dict(hits=hits, observations=len(actual), hit_percent=100 * hits / len(actual),
                mae=float(error.mean()), rmse=float(np.sqrt(np.mean(error**2))),
                wape_percent=float(100 * error.sum() / actual.sum()))


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


class LSTM:
    def __init__(self, hidden, rng):
        self.hidden = hidden
        self.w = rng.normal(0, .18, (4 + hidden, 4 * hidden)).astype('f')
        self.b = np.zeros(4 * hidden, 'f')
        self.b[hidden:2 * hidden] = 1
        self.head = rng.normal(0, .08, hidden + 5).astype('f')
        self.bias = np.zeros(1, 'f')
        self.params = (self.w, self.b, self.head, self.bias)
        self.m = [np.zeros_like(param) for param in self.params]
        self.v = [np.zeros_like(param) for param in self.params]
        self.steps = 0

    def forward(self, seq, cal, training=False):
        h = c = np.zeros((len(seq), self.hidden), 'f')
        tape = []
        for t in range(seq.shape[1]):
            features = np.concatenate((seq[:, t], h), axis=1)
            i, f, g, o = np.split(features @ self.w + self.b, 4, axis=1)
            i, f, g, o = sigmoid(i), sigmoid(f), np.tanh(g), sigmoid(o)
            c_new = f * c + i * g
            tanh_c = np.tanh(c_new)
            h = o * tanh_c
            if training:
                tape.append((features, i, f, g, o, c, tanh_c))
            c = c_new
        end = np.concatenate((h, cal), axis=1)
        return end @ self.head + self.bias[0], end, tape

    def gradients(self, seq, cal, target):
        pred, end, tape = self.forward(seq, cal, training=True)
        # Huber in log-count space reduces the influence of extreme counts.
        residual = pred - target
        d = np.clip(residual, -.35, .35) / len(seq)
        head_gradient = end.T @ d
        hidden_grad = d[:, None] * self.head[None, :self.hidden]
        cell_grad = np.zeros_like(hidden_grad)
        w_gradient, b_gradient = np.zeros_like(self.w), np.zeros_like(self.b)
        for features, i, f, g, o, prior_c, tanh_c in reversed(tape):
            cell_grad += hidden_grad * o * (1 - tanh_c**2)
            preactivation = np.concatenate((cell_grad * g * i * (1-i),
                cell_grad * prior_c * f * (1-f), cell_grad * i * (1-g**2),
                hidden_grad * tanh_c * o * (1-o)), axis=1)
            w_gradient += features.T @ preactivation
            b_gradient += preactivation.sum(axis=0)
            hidden_grad = (preactivation @ self.w.T)[:, 4:]
            cell_grad *= f
        return w_gradient, b_gradient, head_gradient, np.array([d.sum()], 'f')

    def train_batch(self, seq, cal, target):
        gradients = self.gradients(seq, cal, target)
        self.steps += 1
        for param, gradient, m, v in zip(self.params, gradients, self.m, self.v):
            m[:] = .9 * m + .1 * gradient
            v[:] = .999 * v + .001 * gradient**2
            param -= .003 * (m / (1-.9**self.steps)) / (np.sqrt(v / (1-.999**self.steps)) + 1e-7)


def gradient_check():
    rng = np.random.default_rng(42)
    net = LSTM(3, rng)
    seq = rng.normal(size=(8, 4, 4)).astype('f')
    cal = rng.normal(size=(8, 5)).astype('f')
    target = rng.normal(size=8).astype('f')
    grads = net.gradients(seq, cal, target)
    def loss():
        r = np.abs(net.forward(seq, cal)[0] - target)
        return float(np.mean(np.where(r <= .35, .5*r**2, .35*(r-.175))))
    for param, grad in zip(net.params, grads):
        pos = np.unravel_index(int(np.argmax(np.abs(grad))), grad.shape)
        previous = param[pos]
        param[pos] = previous + .001
        high = loss()
        param[pos] = previous - .001
        low = loss()
        param[pos] = previous
        assert abs((high-low)/.002 - grad[pos]) < .0002


def run(root, output, cache, cache_receipt):
    sys.path.insert(0, str(root))
    from jeju_agent.route_demand import read_observations, _eligible

    started = time.perf_counter()
    folder = root / 'models_candidates_v20/bus/561'
    original = json.loads((folder / 'protocol.json').read_text('utf-8'))
    raw_path = root / 'data_raw/hub/hub_561_5842.csv'
    assert file_hash(raw_path) == original['source_sha256']
    if cache:
        assert cache_receipt is not None
        assert json.loads(cache_receipt.read_text('utf-8'))['source_sha256'] == original['source_sha256']
        v20_report = json.loads((folder / 'experiment_report.json').read_text('utf-8'))
        assert file_hash(cache) == v20_report['raw_audit']['cache_sha256']
        raw = json.loads(cache.read_text('utf-8'))
    else:
        raw, _ = read_observations(raw_path)
    raw = [row for row in raw if re.fullmatch(r'\d{1,4}(?:-\d{1,3})?', row['route_id'])]
    split = original['split']
    folds = split['fold_dates']
    test = dict(fit_end=split['final_fit_end'], validation_start=split['test_start'], validation_end=split['test_end'])
    to_ord = {day: dt.date.fromisoformat(day).toordinal() for day in {row['date'] for row in raw}}
    low, high = min(to_ord.values()), max(to_ord.values())
    known = [set(_eligible(raw, dt.date.fromisoformat(fold['fit_end']))) for fold in folds]
    known.append(set(split['evaluation_groups']))
    routes = sorted(set.union(*known))
    route_idx = {route: idx for idx, route in enumerate(routes)}
    panel = np.full((len(routes), high-low+1), np.nan, dtype='f')
    for row in raw:
        route = route_idx.get(row['route_id'])
        if route is not None:
            panel[route, to_ord[row['date']]-low] = row['count']
    del raw
    ordinals = np.arange(low, high+1)
    weekdays = (ordinals-1) % 7
    weekday = np.stack((np.sin(2*np.pi*weekdays/7), np.cos(2*np.pi*weekdays/7)), axis=1).astype('f')
    seasonal = np.stack((np.sin(2*np.pi*ordinals/365.25), np.cos(2*np.pi*ordinals/365.25)), axis=1).astype('f')

    def run_fold(spec, allowed, config, seed):
        ix = np.array([route_idx[code] for code in sorted(allowed)])
        end = to_ord[spec['fit_end']]-low
        start, stop = (to_ord[spec[key]]-low for key in ('validation_start', 'validation_end'))
        first = max(config['lookback'] + HORIZON, end - 729)
        fit_panel = panel[ix, first:end+1]
        scale = np.zeros(len(routes), 'f')
        scale[ix] = np.log1p(np.nanmedian(fit_panel, axis=1))
        fit_code, fit_day = np.where(np.isfinite(fit_panel))
        fit_code, fit_day = ix[fit_code], fit_day + first
        eval_code, eval_day = np.where(np.isfinite(panel[ix, start:stop+1]))
        eval_code, eval_day = ix[eval_code], eval_day + start
        rng = np.random.default_rng(seed)
        net = LSTM(config['hidden'], rng)
        lag_days = np.arange(-HORIZON-config['lookback']+1, -HORIZON+1)

        def features(code, day):
            days = day[:, None] + lag_days[None, :]
            raw_values = panel[code[:, None], days]
            present = np.isfinite(raw_values)
            normalized = np.where(present, np.log1p(raw_values) - scale[code, None], 0)
            seq = np.concatenate((normalized[..., None], present[..., None], weekday[days]), axis=2)
            cal = np.concatenate((weekday[day], seasonal[day], scale[code, None]/4), axis=1)
            return seq.astype('f'), cal.astype('f')

        for epoch in range(EPOCHS):
            chosen = rng.choice(len(fit_code), min(len(fit_code), SAMPLES_PER_EPOCH), replace=False)
            for batch in range(0, len(chosen), BATCH):
                indices = chosen[batch:batch+BATCH]
                code, day = fit_code[indices], fit_day[indices]
                seq, cal = features(code, day)
                net.train_batch(seq, cal, np.log1p(panel[code, day]) - scale[code])
        actual = panel[eval_code, eval_day]
        pred = []
        for batch in range(0, len(eval_code), BATCH):
            code, day = eval_code[batch:batch+BATCH], eval_day[batch:batch+BATCH]
            seq, cal = features(code, day)
            pred.extend(np.maximum(0, np.expm1(np.clip(net.forward(seq, cal)[0]+scale[code], -8, 12))))
        # Exact current-model comparator, with group-specific last observed training day.
        baselines = np.empty((len(routes), 7), 'f')
        train_days = np.arange(first, end+1)
        for code in ix:
            y = panel[code, train_days]
            observed = np.isfinite(y)
            weight = 2.0 ** (-(train_days[observed][-1]-train_days)/60)
            for w in range(7):
                selected = observed & (weekdays[train_days] == w)
                ys, weights = y[selected], weight[selected]
                order = np.argsort(ys)
                baselines[code, w] = ys[order[np.searchsorted(np.cumsum(weights[order]), weights.sum()/2)]]
        baseline = baselines[eval_code, weekdays[eval_day]]
        return dict(candidate=metrics(actual, np.asarray(pred)), incumbent=metrics(actual, baseline))

    protocol = dict(source_id='561', source_sha256=original['source_sha256'], split=split,
                    training_library=f'NumPy {np.__version__}', candidates=CONFIGS, seed=SEED,
                    epochs=EPOCHS, max_training_samples_each_epoch=SAMPLES_PER_EPOCH,
                    lag_rule='Target date d, observe d-7 and earlier only; availability by d-7 is a retrospective assumption.',
                    features='masked log-count history with weekday encoding, target calendar and training group scale',
                    metric='absolute error <= 20 percent of actual positive count',
                    selection='Two chronological validation periods; highest mean hit rate within 2% MAE guard; if none qualify report highest-hit diagnostic only.',
                    runtime_activation=False, gradient_check='passed', test_scope='previously reported historical period, not blind')
    write(output/'lstm_protocol.json', protocol)
    validation = []
    for i, config in enumerate(CONFIGS):
        measured = []
        for j, spec in enumerate(folds):
            score = run_fold(spec, known[j], config, SEED + i*10 + j)
            measured.append(score)
            print('validation', config, j+1, score, round(time.perf_counter()-started, 1), flush=True)
        validation.append(dict(config=config, folds=measured,
            mean_hit=float(np.mean([m['candidate']['hit_percent'] for m in measured])),
            mean_mae=float(np.mean([m['candidate']['mae'] for m in measured])),
            guard_pass=sum(m['candidate']['mae'] for m in measured) <= 1.02 * sum(m['incumbent']['mae'] for m in measured)))
    selected = max(validation, key=lambda row: (row['guard_pass'], row['mean_hit'], -row['mean_mae']))
    write(output/'lstm_selection.json', dict(validation=validation, selected=selected, test_used_for_selection=False))
    test_score = run_fold(test, known[-1], selected['config'], SEED + CONFIGS.index(selected['config'])*10 + 1)
    assert test_score['candidate']['observations'] == split['test_count']
    assert test_score['incumbent']['hits'] == 13535 and abs(test_score['incumbent']['mae'] - 4.966360529688168) < 1e-5
    report = dict(protocol=protocol, selection=selected, validation=validation, test=test_score,
        deployed=False, not_deployed_reason='No verified ongoing dated observation feed; current CSV ends 2025-10-19.',
        elapsed_seconds=time.perf_counter()-started)
    write(output/'lstm_report.json', report)
    print('LSTM test', test_score, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--cache-receipt', type=Path)
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    gradient_check()
    run(options.root.resolve(), options.output, options.cache, options.cache_receipt)
