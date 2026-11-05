"""Compare 561 calendar forecasts with the active v20 benchmark.

Python with numpy and scikit-learn is only required during training.
Run with --root /path/to/JejuGilbeot --output /path/to/experiment-results.
The optional --observations-cache must match the verified v20 cache hash.
"""

import argparse
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "2")

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from calendar561 import ANNUAL, SOURCES, SPECIAL, calendar_vector, tree_vector


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def score(actual, predicted):
    error = np.abs(actual - predicted)
    positive = actual > 0
    hits = int(np.sum(error[positive] <= actual[positive] * .2 + 1e-10))
    return {
        "observations": len(actual),
        "mae": float(np.mean(error)),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "wape_percent": float(100 * np.sum(error) / np.sum(actual)),
        "within_20_percent": {
            "hits": hits,
            "denominator": int(np.sum(positive)),
            "percent": float(100 * hits / np.sum(positive)),
        },
    }


def models():
    for holiday in (False, True):
        for penalty, power in ((2., 0.), (8., 1.), (30., 1.), (8., 0.)):
            yield {
                "family": "route_calendar_ridge",
                "holiday": holiday,
                "penalty": penalty,
                "relative_weight": power,
                "blend": .65,
            }
        for loss, leaves in (
            ("squared_error", 15), ("squared_error", 31),
            ("absolute_error", 15), ("absolute_error", 31), ("quantile", 31),
        ):
            for blend in (.5, 1.):
                yield {
                    "family": "calendar_hist_boosting",
                    "holiday": holiday,
                    "loss": loss,
                    "leaves": leaves,
                    "blend": blend,
                }
    for factor in (.90, .95, .98, 1.02, 1.05, 1.10):
        yield {"family": "weekday_scale", "factor": factor}


def sample(rows, fit_end, start=None, end=None):
    from jeju_agent.route_demand import _eligible

    lower = (date.fromisoformat(fit_end) - timedelta(days=729)).isoformat()
    history = [row for row in rows if lower <= row["date"] <= fit_end]
    groups = set(_eligible(history, date.fromisoformat(fit_end)))
    train = [row for row in history if row["route_id"] in groups]
    target = [row for row in rows if start and start <= row["date"] <= end
              and row["route_id"] in groups]
    return train, target, groups


def weighted_median(values, weights):
    ordered = np.argsort(values)
    selected = np.searchsorted(np.cumsum(weights[ordered]), .5 * sum(weights))
    return float(values[ordered[min(selected, len(values) - 1)]])


class Data:
    def __init__(self, rows, fit_end, statistics=None, groups=None):
        self.fit_end = fit_end
        self.groups = groups or {code: i for i, code in enumerate(
            sorted({row["route_id"] for row in rows}))}
        self.code = np.array([self.groups[row["route_id"]] for row in rows])
        self.group_indices = {
            code: np.flatnonzero(self.code == i) for code, i in self.groups.items()
        }
        self.dates = [date.fromisoformat(row["date"]) for row in rows]
        self.actual = np.array([row["count"] for row in rows], float)
        self.weekday = np.array([day.weekday() for day in self.dates])
        self.ordinals = np.array([day.toordinal() for day in self.dates])
        self.statistics = statistics or self._fit_statistics()
        self.baseline = np.zeros(len(rows))
        for group, idx in self.group_indices.items():
            self.baseline[idx] = np.asarray(self.statistics[group]["centers"])[self.weekday[idx]]
        self._matrix_cache = {}

    def _fit_statistics(self):
        group_stats = {}
        for code, idx in self.group_indices.items():
            ordinal = self.ordinals[idx]
            values = self.actual[idx]
            ages = ordinal.max() - ordinal
            weights = 2 ** (-ages / 60)
            weekdays = self.weekday[idx]
            centers = []
            for i in range(7):
                match = weekdays == i
                centers.append(weighted_median(values[match], weights[match])
                               if np.any(match) else weighted_median(values, weights))
            overall = weighted_median(values, weights)
            recent = np.average(values, weights=2 ** (-ages / 28))
            longer = np.average(values, weights=2 ** (-ages / 180))
            group_stats[code] = {
                "centers": centers,
                "scale": float(np.log1p(overall)),
                "recent_ratio": float(recent / max(1., longer)),
                "weekday_ratio": float(np.mean(centers[:5]) / max(1., np.mean(centers[5:]))),
            }
        return group_stats

    def matrix(self, family, holiday):
        key = (family, holiday)
        if key in self._matrix_cache:
            return self._matrix_cache[key]
        vectors = [calendar_vector(day, self.fit_end, holiday) for day in self.dates]
        if family == "calendar_hist_boosting":
            by_id = {i: self.statistics[code] for code, i in self.groups.items()}
            vectors = [
                tree_vector(day, self.fit_end, vector,
                            int(group) if len(self.groups) <= 255 else 0,
                            holiday, by_id[group])
                for day, vector, group in zip(self.dates, vectors, self.code)
            ]
        self._matrix_cache[key] = np.asarray(vectors, dtype=float)
        return self._matrix_cache[key]


def fit_predict(config, train, target=None, estimator_cache=None):
    family = config["family"]
    if family == "weekday_scale":
        return (None if target is None else target.baseline * config["factor"]), {}
    x = train.matrix(family, config["holiday"])
    y = train.actual
    base = np.maximum(train.baseline, 1.)
    if family == "route_calendar_ridge":
        coefficients = {}
        predictions = None if target is None else np.empty(len(target.actual))
        for group, idx in train.group_indices.items():
            design = x[idx]
            dates = train.ordinals[idx]
            weights = 2 ** (-(dates.max() - dates) / 180)
            weights /= np.maximum(.20, y[idx] / base[idx]) ** config["relative_weight"]
            penalty = np.full(design.shape[1], config["penalty"])
            penalty[:7] *= 2
            ratio_residual = y[idx] / base[idx] - 1.
            coefs = np.linalg.solve(
                design.T @ (weights[:, None] * design) + np.diag(penalty),
                design.T @ (weights * ratio_residual),
            )
            coefficients[group] = coefs.tolist()
            if target is not None:
                destination = target.group_indices[group]
                values = target.matrix(family, config["holiday"])[destination]
                relative = np.maximum(0., 1. + values @ coefs)
                predictions[destination] = target.baseline[destination] * (
                    1. - config["blend"] + config["blend"] * relative
                )
        return predictions, {"coefficients": coefficients}

    key = (config["loss"], config["leaves"], config["holiday"])
    cache = estimator_cache if estimator_cache is not None else {}
    if key not in cache:
        params = {"quantile": .45} if config["loss"] == "quantile" else {}
        est = HistGradientBoostingRegressor(
            loss=config["loss"], max_iter=100, max_leaf_nodes=config["leaves"],
            learning_rate=.055, min_samples_leaf=60, l2_regularization=2.,
            categorical_features=[0, 1, 2], early_stopping=False, random_state=20261106,
            **params,
        )
        weights = 2 ** (-(train.ordinals.max() - train.ordinals) / 130)
        # Normalize by the fit-only weekday median. The target remains the
        # observed positive ridership, with no target or neighboring test values.
        est.fit(x, y / base, sample_weight=weights)
        cache[key] = est
    est = cache[key]
    if target is None:
        return None, {"estimator": est}
    relative = np.maximum(0., est.predict(target.matrix(family, config["holiday"])))
    return target.baseline * (1. - config["blend"] + config["blend"] * relative), {"estimator": est}


def export_hgb(est):
    categorical = np.flatnonzero(est.is_categorical_)
    numerical = np.flatnonzero(~est.is_categorical_)
    encoder = est._preprocessor.named_transformers_["encoder"]
    return {
        "offset": float(est._baseline_prediction[0, 0]),
        "order": np.r_[categorical, numerical].tolist(),
        "categories": {str(i): v.tolist() for i, v in zip(categorical, encoder.categories_)},
        "trees": [{
            "nodes": [[float(node[n]) if n in ("value", "num_threshold") else int(node[n])
                       for n in ("value", "feature_idx", "num_threshold", "missing_go_to_left",
                                 "left", "right", "is_leaf", "is_categorical", "bitset_idx")]
                      for node in predictor.nodes],
            "bitsets": predictor.raw_left_cat_bitsets.tolist(),
        } for (predictor,) in est._predictors],
    }


def paired_data(rows, fit_end, start, stop):
    history, target, groups = sample(rows, fit_end, start, stop)
    train = Data(history, fit_end)
    return train, Data(target, fit_end, train.statistics, train.groups), target, groups


def run(args):
    began = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.root))
    prior = args.root / "models_candidates_v20/bus/561"
    old = read(prior / "experiment_report.json")
    split = old["protocol"]["split"]
    raw = args.root / "data_raw/hub/hub_561_5842.csv"
    if digest(raw) != old["raw_audit"]["source_sha256"]:
        raise ValueError("561 raw file differs from the frozen comparison source")
    if args.observations_cache:
        if digest(args.observations_cache) != old["raw_audit"]["cache_sha256"]:
            raise ValueError("Observation cache differs from the verified v20 extraction")
        import re

        rows = [row for row in read(args.observations_cache)
                if re.fullmatch(r"\d{1,4}(?:-\d{1,3})?", row["route_id"])]
    else:
        from jeju_agent.route_demand import read_observations

        rows, _ = read_observations(raw)
    configs = [{"id": i, **config} for i, config in enumerate(models())]
    protocol = {
        "task": "fixed-horizon daily positive regular ridership of 561 route statistics codes",
        "source_sha256": old["raw_audit"]["source_sha256"],
        "v20_split": split,
        "forecast_inputs": "date and route-code fit-only statistics; holidays known by fold fit end",
        "public_calendar_sources": SOURCES,
        "calendar_annual": ANNUAL,
        "calendar_special": SPECIAL,
        "selection": "maximize mean dev-fold hit rate among MAE <= 1.02 x active v20; tie by MAE then ID",
        "release": "frozen holdout hit rate must exceed active v20 and MAE <= 1.02 x v20",
        "test_previously_seen": True,
        "libraries": {"numpy": np.__version__, "sklearn": sklearn.__version__},
        "candidates": configs,
    }
    protocol_path = args.output / "calendar_protocol.json"
    write(protocol_path, protocol)
    trial_scores = defaultdict(list)
    baselines = []
    for i, fold in enumerate(split["fold_dates"]):
        train, target, _, _ = paired_data(
            rows, fold["fit_end"], fold["validation_start"], fold["validation_end"],
        )
        baselines.append(score(target.actual, target.baseline))
        estimators = {}
        for cfg in configs:
            predictions, _ = fit_predict(cfg, train, target, estimators)
            trial_scores[cfg["id"]].append(score(target.actual, predictions))
            if cfg["id"] % 5 == 0:
                print("validation", i, cfg["id"], round(time.monotonic() - began, 1), flush=True)
    baseline_mae = np.mean([m["mae"] for m in baselines])
    table = []
    for cfg in configs:
        folds = trial_scores[cfg["id"]]
        table.append({
            "config": cfg,
            "folds": folds,
            "mean_hit_percent": float(np.mean([m["within_20_percent"]["percent"] for m in folds])),
            "mean_mae": float(np.mean([m["mae"] for m in folds])),
        })
    eligible = [trial for trial in table if trial["mean_mae"] <= 1.02 * baseline_mae]
    selected = min(eligible, key=lambda t: (-t["mean_hit_percent"], t["mean_mae"], t["config"]["id"]))
    freeze_path = args.output / "calendar_freeze.json"
    write(freeze_path, {
        "protocol_sha256": digest(protocol_path),
        "v20_validation": baselines,
        "validation": table,
        "selected": selected,
        "selection_has_seen_test_targets": False,
    })
    print("selection frozen", selected["config"], flush=True)

    train, target, target_rows, groups = paired_data(
        rows, split["final_fit_end"], split["test_start"], split["test_end"],
    )
    if len(target_rows) != split["test_count"] or sorted(groups) != split["evaluation_groups"]:
        raise ValueError("Evaluation cohort differs from the v20 comparison")
    frozen = {(row["date"], row["group"]): row for row in read(prior / "predictions_test.json")["rows"]}
    original = [frozen[(row["date"], row["route_id"])] for row in target_rows]
    if any(row["count"] != archived["observed"] for row, archived in zip(target_rows, original)):
        raise ValueError("Observed test targets differ from the archived test predictions")
    if not np.allclose(target.baseline, [row["predicted"] for row in original], atol=1e-9, rtol=0):
        raise ValueError("Active weighted-weekday median reproduction failed")
    predictions, _ = fit_predict(selected["config"], train, target)
    baseline = score(target.actual, target.baseline)
    candidate = score(target.actual, predictions)
    promote = (candidate["within_20_percent"]["hits"] > baseline["within_20_percent"]["hits"]
               and candidate["mae"] <= 1.02 * baseline["mae"])
    report = {
        "protocol_sha256": digest(protocol_path),
        "freeze_sha256": digest(freeze_path),
        "candidate_count": len(configs),
        "config": selected["config"],
        "validation_v20": baselines,
        "validation_selected": selected["folds"],
        "test_v20": baseline,
        "test_selected": candidate,
        "passes_fixed_gate": bool(promote),
        "test_start": split["test_start"],
        "test_end": split["test_end"],
        "fit_end": split["final_fit_end"],
        "test_evaluation_groups": len(groups),
        "test_by_group": {g: score(target.actual[idx], predictions[idx])
                          for g, idx in target.group_indices.items() if len(idx)},
        "elapsed_seconds": time.monotonic() - began,
    }
    if promote:
        serving_end = max(row["date"] for row in rows)
        serving_rows, _, serving_groups = sample(rows, serving_end)
        if sorted(serving_groups) != split["serving_groups"]:
            raise ValueError("Serving cohort differs from v20")
        serving = Data(serving_rows, serving_end)
        _, parameters = fit_predict(selected["config"], serving)
        if "estimator" in parameters:
            parameters = export_hgb(parameters["estimator"])
        model_path = args.output / "calendar_candidate_model.json"
        write(model_path, {
            "schema_version": 1,
            "config": selected["config"],
            "source_sha256": old["raw_audit"]["source_sha256"],
            "fit_end": serving_end,
            "groups": serving.groups,
            "statistics": serving.statistics,
            "parameters": parameters,
            "freeze_sha256": digest(freeze_path),
        })
        report["artifact_sha256"] = digest(model_path)
    write(args.output / "calendar_experiment_report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "test_by_group"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observations-cache", type=Path)
    run(parser.parse_args())
