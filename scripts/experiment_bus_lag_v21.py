"""Train and evaluate prospective-lag candidates for source 561 offline.

Use an independent training Python with NumPy and scikit-learn. Production
Python is untouched. This experiment assumes publication by an indicated lag.
The bulk CSV does not establish when an individual cell became available.
"""

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import warnings

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits


SOURCE = "data_raw/hub/hub_561_5842.csv"
V20 = "models_candidates_v20/bus/561"
DELAYS = (1, 7, 28)
LAG_OFFSETS = (0, 1, 2, 6, 13, 27)
MIN_OBS = 3
SEED = 20261106
CONFIGS = (
    {"id": "sameweekday_median", "family": "local", "window": 4, "weight": 1.0},
    {"id": "sameweekday_median_blend", "family": "local", "window": 4, "weight": 0.65},
    {"id": "sameweekday_median_blend8", "family": "local", "window": 8, "weight": 0.65},
    {"id": "hgb_absolute_15", "family": "hgb", "loss": "absolute_error", "leaves": 15},
    {"id": "hgb_absolute_31", "family": "hgb", "loss": "absolute_error", "leaves": 31},
    {"id": "hgb_q40_15", "family": "hgb", "loss": "quantile", "quantile": 0.4, "leaves": 15},
    {"id": "hgb_poisson_15", "family": "hgb", "loss": "poisson", "leaves": 15},
)
FEATURES = [
    "weekday", "day_of_month", "annual_sin", "annual_cos", "log_scale",
    "gap_after_cutoff", "coverage_7", "coverage_28", "recent_median_7_over_28",
    "recent_mean_28_over_median_28", "recent_std_28_over_median_28",
    "recent_median_56_over_28", "same_weekday_median_4_over_scale",
    "same_weekday_median_8_over_scale", "same_weekday_coverage_8",
] + [f"lag_cutoff_plus_{offset}_over_scale" for offset in LAG_OFFSETS]


def read_json(path):
    return json.loads(path.read_text("utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ordinal(date):
    return dt.date.fromisoformat(date).toordinal()


def metrics(actual, predicted):
    err = np.abs(actual - predicted)
    positive = actual > 0
    count = int(positive.sum())
    hits = int(np.sum(positive & (err <= 0.2 * actual + 1e-10)))
    return {
        "observations": len(actual),
        "mae": float(err.mean()),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "wape_percent": float(100 * err.sum() / actual.sum()),
        "within_20_percent": {"hits": hits, "denominator": count, "percent": 100 * hits / count},
    }


def prepare_panel(root, workspace, protocol):
    expected = protocol["source_sha256"]
    source = root / SOURCE
    observed_sha = sha(source)
    if observed_sha != expected:
        raise ValueError("Source file does not match the frozen 561 protocol")
    cache = workspace / "observed.json"
    receipt = workspace / "audit.json"
    if cache.is_file() and receipt.is_file() and read_json(receipt)["source_sha256"] == observed_sha:
        rows = read_json(cache)
        cache_receipt = {"path": str(cache), "sha256": sha(cache), "matching_raw_sha256": observed_sha}
    else:
        sys.path.insert(0, str(root))
        from jeju_agent.route_demand import read_observations

        rows, _ = read_observations(source)
        cache_receipt = None
    rows = [row for row in rows if re.fullmatch(r"\d{1,4}(?:-\d{1,3})?", row["route_id"])]
    groups = sorted({row["route_id"] for row in rows})
    group_index = {code: idx for idx, code in enumerate(groups)}
    date0 = ordinal(min(row["date"] for row in rows))
    date1 = ordinal(max(row["date"] for row in rows))
    panel = np.full((date1 - date0 + 1, len(groups)), np.nan, dtype=np.float32)
    for row in rows:
        day = ordinal(row["date"]) - date0
        code = group_index[row["route_id"]]
        if np.isfinite(panel[day, code]):
            raise ValueError("Duplicate source cell")
        panel[day, code] = row["count"]
    return panel, groups, date0, cache_receipt


def eligibility(panel, end):
    recent = panel[end - 179 : end + 1]
    tail = recent[-28:]
    count = np.isfinite(recent).sum(axis=0)
    count_tail = np.isfinite(tail).sum(axis=0)
    mean = np.nansum(recent, axis=0) / np.maximum(count, 1)
    return np.flatnonzero((count >= 162) & (count_tail >= 24) & (mean >= 5))


def observed_cells(panel, start, end, groups):
    day, group = np.nonzero(np.isfinite(panel[start : end + 1, groups]))
    day, group = day + start, groups[group]
    return day, group, panel[day, group].astype(float)


def weighted_medians(panel, date0, fit_end, groups):
    centers = np.zeros((panel.shape[1], 7))
    start = fit_end - 729
    weekdays = (np.arange(start, fit_end + 1) + date0 - 1) % 7
    fit = panel[start : fit_end + 1]
    weight = 2 ** (-(fit_end - np.arange(start, fit_end + 1)) / 60)

    def weighted_median(values, weights, mask):
        values, weights = values[mask], weights[mask]
        order = np.argsort(values)
        return values[order[np.searchsorted(np.cumsum(weights[order]), 0.5 * sum(weights))]]

    for group in groups:
        value = fit[:, group]
        present = np.isfinite(value)
        fallback = weighted_median(value, weight, present)
        for weekday in range(7):
            mask = present & (weekdays == weekday)
            centers[group, weekday] = weighted_median(value, weight, mask) if np.any(mask) else fallback
    return centers


def features_for_cells(panel, date0, days, groups, delay):
    """Every observation comes from a day <= target minus the declared delay."""
    same_week_offsets = 7 * (math.ceil(delay / 7) + np.arange(8))
    width = max(56, int(same_week_offsets[-1] - delay + 1))
    matrix = np.empty((len(days), len(FEATURES)), np.float32)
    scale = np.empty(len(days), np.float32)
    week4 = np.empty(len(days), np.float32)
    week8 = np.empty(len(days), np.float32)
    valid = np.empty(len(days), bool)
    for start in range(0, len(days), 8192):
        select = slice(start, start + 8192)
        d, g = days[select], groups[select]
        source_dates = d[:, None] - delay - np.arange(width)
        assert np.max(source_dates[:, 0] - d) <= -delay
        raw = panel[np.maximum(source_dates, 0), g[:, None]].copy()
        raw[source_dates < 0] = np.nan
        observed = np.isfinite(raw)
        recent7, recent28, recent56 = raw[:, :7], raw[:, :28], raw[:, :56]
        n7, n28 = observed[:, :7].sum(axis=1), observed[:, :28].sum(axis=1)
        weekly = raw[:, same_week_offsets - delay]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            rolling_scale = np.nanmedian(recent28, axis=1)
            rolling_scale = np.where(np.isfinite(rolling_scale), np.maximum(1, rolling_scale), 1)
            med7, med56 = np.nanmedian(recent7, axis=1), np.nanmedian(recent56, axis=1)
            mean28, std28 = np.nanmean(recent28, axis=1), np.nanstd(recent28, axis=1)
            seasonal4 = np.nanmedian(weekly[:, :4], axis=1)
            seasonal8 = np.nanmedian(weekly, axis=1)
        dates = [dt.date.fromordinal(int(n + date0)) for n in d]
        theta = 2 * np.pi * np.array([date.timetuple().tm_yday - 1 for date in dates]) / 365.25
        gap = np.where(observed.any(axis=1), np.argmax(observed, axis=1), width)
        columns = [
            (d + date0 - 1) % 7, [date.day for date in dates], np.sin(theta), np.cos(theta),
            np.log1p(rolling_scale), gap, n7 / 7, n28 / 28, med7 / rolling_scale,
            mean28 / rolling_scale, std28 / rolling_scale, med56 / rolling_scale,
            seasonal4 / rolling_scale, seasonal8 / rolling_scale, np.isfinite(weekly).mean(axis=1),
        ]
        columns += [raw[:, lag] / rolling_scale for lag in LAG_OFFSETS]
        matrix[select] = np.column_stack(columns)
        scale[select], week4[select], week8[select], valid[select] = rolling_scale, seasonal4, seasonal8, n28 >= MIN_OBS
    return matrix, scale, week4, week8, valid


def fit(config, train_features, days, counts):
    if config["family"] == "local":
        return None
    x, scale, _, _, valid = train_features
    weight = 2 ** (-(days.max() - days[valid]) / 180)
    params = {"quantile": config["quantile"]} if "quantile" in config else {}
    model = HistGradientBoostingRegressor(
        loss=config["loss"], max_leaf_nodes=config["leaves"], min_samples_leaf=45,
        max_iter=100, learning_rate=0.065, l2_regularization=1.0,
        early_stopping=False, random_state=SEED, **params,
    )
    return model.fit(x[valid], counts[valid] / scale[valid], sample_weight=weight)


def forecast(config, model, features, baseline):
    x, scale, week4, week8, valid = features
    output = baseline.copy()
    if config["family"] == "local":
        recent = week4 if config["window"] == 4 else week8
        used = valid & np.isfinite(recent)
        blend = config["weight"]
        output[used] = blend * recent[used].astype(float) + (1 - blend) * baseline[used]
    else:
        used = valid
        output[used] = np.maximum(0, model.predict(x[used]) * scale[used])
    return output, int(used.sum())


def export_model(model, config, delay, date0, fit_end, centers, groups, source_sha):
    artifact = {
        "schema_version": 1, "source_id": "561", "source_sha256": source_sha, "config": config,
        "history_delay_days": delay, "rolling_min_observations": MIN_OBS, "feature_order": FEATURES,
        "fit_end": dt.date.fromordinal(fit_end + date0).isoformat(),
        "current_feed_verified": False, "production_eligible": False,
        "weekday_fallback": {name: centers[i].tolist() for i, name in groups},
    }
    if model is not None:
        artifact["link"] = "exp" if config["loss"] == "poisson" else "identity"
        artifact["intercept"] = float(model._baseline_prediction[0, 0])
        artifact["trees"] = []
        for iteration in model._predictors:
            tree = iteration[0]
            nodes = []
            for node in tree.nodes:
                threshold = float(node["num_threshold"])
                # sklearn can use infinity for a split on missingness alone.
                nodes.append({
                    "value": float(node["value"]),
                    "num_threshold": threshold if math.isfinite(threshold) else str(threshold),
                    **{key: int(node[key]) for key in ("feature_idx", "left", "right", "is_leaf", "missing_go_to_left")},
                })
            artifact["trees"].append(nodes)
    return artifact


def predict_export(artifact, features, baseline):
    """Plain Python portability check. The result is conditional on fresh history."""
    x, scale, week4, week8, valid = features
    if not valid:
        return baseline
    config = artifact["config"]
    if config["family"] == "local":
        recent = week4 if config["window"] == 4 else week8
        return (1 - config["weight"]) * baseline + config["weight"] * recent if math.isfinite(recent) else baseline
    result = artifact["intercept"]
    for tree in artifact["trees"]:
        node = tree[0]
        while not node["is_leaf"]:
            value = float(x[node["feature_idx"]])
            left = node["missing_go_to_left"] if math.isnan(value) else value <= float(node["num_threshold"])
            node = tree[node["left"] if left else node["right"]]
        result += node["value"]
    return max(0.0, (math.exp(result) if artifact["link"] == "exp" else result) * scale)


def split_parts(panel, date0, fit_date, target_start, target_end):
    fit_end, start, end = (ordinal(date) - date0 for date in (fit_date, target_start, target_end))
    groups = eligibility(panel, fit_end)
    d_train, g_train, y_train = observed_cells(panel, fit_end - 729, fit_end, groups)
    d_eval, g_eval, y_eval = observed_cells(panel, start, end, groups)
    centers = weighted_medians(panel, date0, fit_end, groups)
    baseline = centers[g_eval, (d_eval + date0 - 1) % 7]
    return d_train, g_train, y_train, d_eval, g_eval, y_eval, centers, baseline, groups


def select_on_validation(panel, date0, split, out):
    scores = {str(delay): {config["id"]: [] for config in CONFIGS} for delay in DELAYS}
    baselines = []
    for fold in split["fold_dates"]:
        parts = split_parts(panel, date0, fold["fit_end"], fold["validation_start"], fold["validation_end"])
        d_train, g_train, y_train, d_eval, g_eval, y_eval, _, baseline, _ = parts
        baselines.append(metrics(y_eval, baseline))
        print(f"Fold {fold['fit_end']}, {len(y_train)} training and {len(y_eval)} validation cells", flush=True)
        for delay in DELAYS:
            train = features_for_cells(panel, date0, d_train, g_train, delay)
            val = features_for_cells(panel, date0, d_eval, g_eval, delay)
            for config in CONFIGS:
                model = fit(config, train, d_train, y_train)
                pred, used = forecast(config, model, val, baseline)
                result = metrics(y_eval, pred)
                result["lag_used_cells"] = used
                scores[str(delay)][config["id"]].append(result)
                print(f"validation {delay=}, {config['id']}: {result['within_20_percent']['percent']:.2f}%, MAE {result['mae']:.3f}", flush=True)
    base_mae = np.mean([fold["mae"] for fold in baselines])
    selected = {}
    comparisons = {}
    for delay in DELAYS:
        table = []
        for config in CONFIGS:
            vals = scores[str(delay)][config["id"]]
            mae = float(np.mean([value["mae"] for value in vals]))
            hit = float(np.mean([value["within_20_percent"]["percent"] for value in vals]))
            table.append({"config": config, "folds": vals, "mean_mae": mae, "mean_hit_percent": hit, "mae_guard_pass": bool(mae <= base_mae * 1.02)})
        eligible = [entry for entry in table if entry["mae_guard_pass"]]
        selected[str(delay)] = min(eligible, key=lambda entry: (-entry["mean_hit_percent"], entry["mean_mae"], entry["config"]["id"])) if eligible else None
        comparisons[str(delay)] = table
    write_json(out / "selection_freeze.json", {
        "protocol_sha256": sha(out / "protocol.json"),
        "v20_validation_baseline": baselines,
        "selections": selected, "test_scored_before_selection": False,
    })
    write_json(out / "validation_results.json", comparisons)
    return selected, comparisons


def run(args):
    root, out = args.root, args.output
    out.mkdir(parents=True, exist_ok=True)
    previous = read_json(root / V20 / "protocol.json")
    split = previous["split"]
    plan = {
        "source_id": "561", "source_sha256": previous["source_sha256"],
        "previous_protocol_sha256": sha(root / V20 / "protocol.json"),
        "forecasting_condition": "For each target d, pretend all observations dated <= d - delay were already released. No archived publication timestamps are available. Actual deployment requires a recent authorized feed.",
        "history_in_train_and_eval": "prior known days only. Never use any target-day or later value. Earlier validation/test observations enter strictly as conditional prior values; all model parameters are fixed before validation/test scoring.",
        "fit_window_days": 730, "history_delay_days": DELAYS, "lag_features": FEATURES,
        "candidate_configs": CONFIGS, "fit_iter": 100,
        "selection": "per delay maximize mean validation fold positive actual +/-20% hit rate; mean MAE <=1.02 times v20 median baseline. Tie lower MAE then config ID. Read scored test targets only after selection receipt.",
        "split": split, "test_status": "historical v20 holdout reuse, not fresh external validation",
        "versions": {"numpy": np.__version__, "scikit_learn": sklearn.__version__},
    }
    if args.resume_frozen:
        if read_json(out / "protocol.json") != json.loads(json.dumps(plan)):
            raise ValueError("Current protocol does not match the saved protocol")
        receipt = read_json(out / "selection_freeze.json")
        if receipt["protocol_sha256"] != sha(out / "protocol.json"):
            raise ValueError("Frozen selection does not match protocol")
        selected = receipt["selections"]
        full_validation = out / "validation_results.json"
        comparisons = read_json(full_validation) if full_validation.is_file() else None
    else:
        write_json(out / "protocol.json", plan)
    panel, names, date0, cache_receipt = prepare_panel(root, args.cache_dir, previous)
    if not args.resume_frozen:
        selected, comparisons = select_on_validation(panel, date0, split, out)
    # Test values enter historical lag features only at the declared offset.
    # Every parameter has already been selected on the earlier folds.
    parts = split_parts(panel, date0, split["final_fit_end"], split["test_start"], split["test_end"])
    d_train, g_train, y_train, d_eval, g_eval, y_eval, centers, baseline, groups = parts
    assert [names[i] for i in groups] == split["evaluation_groups"]
    assert len(y_eval) == split["test_count"]
    frozen = read_json(root / V20 / "predictions_test.json")["rows"]
    frozen_rows = {(ordinal(row["date"]) - date0, row["group"]): row for row in frozen}
    joined = [frozen_rows[int(d), names[g]] for d, g in zip(d_eval, g_eval)]
    assert np.array_equal(y_eval, [row["observed"] for row in joined])
    assert np.allclose(baseline, [row["predicted"] for row in joined], rtol=0, atol=1e-12)
    baseline_report = metrics(y_eval, baseline)
    test = {}
    for delay in DELAYS:
        chosen = selected[str(delay)]
        if not chosen:
            test[str(delay)] = {"selected": None, "reason": "no_validation_mae_guard_pass"}
            continue
        config = chosen["config"]
        train = features_for_cells(panel, date0, d_train, g_train, delay)
        val = features_for_cells(panel, date0, d_eval, g_eval, delay)
        model = fit(config, train, d_train, y_train)
        pred, used = forecast(config, model, val, baseline)
        report = metrics(y_eval, pred)
        artifact = export_model(model, config, delay, date0, int(d_train.max()), centers, [(i, names[i]) for i in groups], previous["source_sha256"])
        maxerr = 0.0
        x, scale, week4, week8, valid = val
        for i in np.linspace(0, len(pred) - 1, num=257, dtype=int):
            rebuilt = predict_export(artifact, (x[i], float(scale[i]), float(week4[i]), float(week8[i]), valid[i]), baseline[i])
            maxerr = max(maxerr, abs(rebuilt - pred[i]))
        assert maxerr < 1e-9, maxerr
        for index in [0, len(d_eval)//2, len(d_eval)-1]:
            day, group = int(d_eval[index]), int(g_eval[index])
            altered = panel.copy()
            altered[day - delay + 1 :, group] = 100000
            orig = features_for_cells(panel, date0, d_eval[index:index + 1], g_eval[index:index + 1], delay)
            probe = features_for_cells(altered, date0, d_eval[index:index + 1], g_eval[index:index + 1], delay)
            for first, second in zip(orig, probe):
                assert np.array_equal(first, second, equal_nan=True)
        artifact_path = out / f"candidate_delay_{delay}.json"
        write_json(artifact_path, artifact)
        test[str(delay)] = {
            "selected": config, "metrics": report, "conditional_history_used_cells": used,
            "fallback_cells": len(pred) - used,
            "improves_hit_and_mae_guard": (
                report["within_20_percent"]["percent"] > baseline_report["within_20_percent"]["percent"]
                and report["mae"] <= baseline_report["mae"] * 1.02
            ),
            "portable_prediction_checks": 257, "portable_max_abs_error": maxerr,
            "future_perturbation_checks": 3, "candidate_sha256": sha(artifact_path),
            "production_eligible": False, "reason": "no timely authorized 561 feed verified",
        }
        print(f"test {delay=}: {json.dumps(test[str(delay)], ensure_ascii=False)}", flush=True)
    write_json(out / "experiment_report.json", {
        "protocol_sha256": sha(out / "protocol.json"),
        "selection_sha256": sha(out / "selection_freeze.json"),
        "raw_observation_end": dt.date.fromordinal(date0 + panel.shape[0] - 1).isoformat(),
        "panel_cache_receipt": cache_receipt, "validation_candidates": comparisons,
        "test": test, "v20_matched_test": baseline_report,
        "v20_baseline_predictions_equal": True, "frozen_cohort_cells": len(y_eval),
        "data_coverage": split["test_count"] / split["test_all_source_cells"],
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--resume-frozen", action="store_true", help="Reuse the saved selection after an interrupted export")
    args = parser.parse_args()
    with threadpool_limits(limits=args.threads):
        run(args)
