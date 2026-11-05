"""Reproduce frozen v14 evaluations and report interpretable tolerance hit rates.

This script never searches configurations or changes a serving model. All
tolerance thresholds are fixed in code before reading the evaluation results.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# These reporting thresholds were specified before this evaluation, not chosen
# after comparing results. All sensitivities are published, including decreases.
CONSUMPTION_TOLERANCE_PP = [0.5, 1.0, 2.0]
BUS_RELATIVE_TOLERANCE = [0.1, 0.2, 0.3]
BUS_ABSOLUTE_TOLERANCE_PER_HOUR = [50.0, 100.0]


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def protected_hashes():
    paths = [ROOT / "data_raw/hub/hub_1048_5832.csv",
             ROOT / "data_raw/hub/hub_512_5856.csv"]
    for directory in ["models_audience", "models_mobility"]:
        paths.extend((ROOT / directory).glob("*.json"))
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(paths)}


def hit_record(errors, threshold, unit):
    hits = sum(error <= threshold + 1e-12 for error in errors)
    total = len(errors)
    return {"threshold": threshold, "threshold_unit": unit,
            "hits": hits, "total": total,
            "rate": hits / total if total else None,
            "percent": round(100 * hits / total, 4) if total else None}


def consume_scores(cells):
    errors = [abs(cell["actual"] - cell["predicted"]) for cell in cells]
    mae = sum(errors) / len(errors)
    return {"mae_share": round(mae, 8),
            "mae_percentage_points": round(100 * mae, 6),
            "tolerance_rates": {
                str(value): hit_record([100 * error for error in errors], value,
                                       "percentage_points")
                for value in CONSUMPTION_TOLERANCE_PP}}


def evaluate_consumption():
    from jeju_agent import audience_model as model
    metrics = read("models_audience/audience_metrics.json")
    panels, source = model.read_panels(ROOT / "data_raw/hub/hub_1048_5832.csv")
    assert source["source_sha256"] == metrics["source"]["source_sha256"]
    split = metrics["split"]
    fit = [row for row in panels if row["month"] <= split["validation_end"]]
    test = [row for row in panels
            if split["test_start"] <= row["month"] <= split["test_end"]]
    assert len(fit) == 72 * 2 and len(test) == 18 * 2
    config = dict(metrics["selection"]["config"])
    recent_config = dict(config, harmonics=0)
    profiles = model._fit(fit)
    ridge = model._fit_ridge(fit, config)
    recent = model._fit_ridge(fit, recent_config)
    predictors = {
        "baseline": lambda row: model._predict(profiles, row["audience"],
                     row["calendar_month"], metrics["selection"]["shrinkage"], True),
        "recent_weighted_mean": lambda row: model._predict_ridge(recent,
                     row["audience"], row["calendar_month"], recent_config),
        "model": lambda row: model._predict_ridge(ridge, row["audience"],
                     row["calendar_month"], config),
    }
    results = {}
    for name, predict in predictors.items():
        cells = []
        for row in test:
            values = predict(row)
            for category, actual, predicted in zip(model.CATEGORIES, row["shares"], values):
                cells.append({"month": row["month"], "audience": row["audience"],
                              "category": category, "actual": actual,
                              "predicted": predicted})
        result = consume_scores(cells)
        expected = metrics["test"]["recent_weighted_mean_ablation" if name == "recent_weighted_mean" else name]
        assert result["mae_share"] == expected["mae_share"], (name, result, expected)
        result["mae_reproduced"] = True
        result["by_audience"] = {
            group: consume_scores([cell for cell in cells if cell["audience"] == group])
            for group in model.GROUPS}
        result["by_category"] = {
            category: consume_scores([cell for cell in cells if cell["category"] == category])
            for category in model.CATEGORIES}
        results[name] = result
    return {"source_id": "1048", "source_sha256": source["source_sha256"],
            "fit_period": {"start": split["train_start"], "end": split["validation_end"],
                           "months": 72},
            "test_period": {"start": split["test_start"], "end": split["test_end"],
                            "months": 18},
            "panels": 36, "category_cells": 288,
            "primary_metric": "업종 비중 오차 1퍼센트포인트 이내 비율",
            "primary_threshold_key": "1.0",
            "definition": "절대값(추정 업종 비중 - 관측 업종 비중) × 100이 1 이하인 월·집단·업종 셀 수 / 전체 288셀",
            "example": "관측 비중이 20%일 때 19%~21%로 추정하면 이 기준을 충족합니다.",
            "config_frozen": config, "results": results}


def bus_scores(rows, predictions):
    errors = [abs(row["rate"] - predicted) for row, predicted in zip(rows, predictions)]
    positive = [(row, predicted) for row, predicted in zip(rows, predictions)
                if row["rate"] > 0]
    relative = [abs(row["rate"] - predicted) / row["rate"] for row, predicted in positive]
    zeros = [(row, predicted) for row, predicted in zip(rows, predictions) if row["rate"] == 0]
    count_error = sum(error * row["hours"] for error, row in zip(errors, rows))
    observed = sum(row["count"] for row in rows)
    return {"mae_per_hour": round(sum(errors) / len(errors), 4),
            "wape_bucket_counts": round(count_error / observed, 6) if observed else None,
            "observations": len(rows), "positive_observations": len(positive),
            "zero_observations": len(zeros),
            "zero_exact_prediction_hits": sum(abs(predicted) <= 1e-12 for _, predicted in zeros),
            "relative_tolerance_rates": {
                str(value): hit_record(relative, value, "fraction_of_observed_hourly_rate")
                for value in BUS_RELATIVE_TOLERANCE},
            "absolute_tolerance_rates": {
                str(value): hit_record(errors, value, "persons_per_hour")
                for value in BUS_ABSOLUTE_TOLERANCE_PER_HOUR}}


def evaluate_bus():
    from jeju_agent import mobility_model as model
    metrics = read("models_mobility/mobility_metrics.json")
    path = ROOT / "data_raw/hub/hub_512_5856.csv"
    assert sha(path) == metrics["source_sha256"]
    rows, selection = model._read_rows(path)
    split = metrics["split"]
    fit = [row for row in rows if row["date"] <= split["train"]["end"]]
    test = [row for row in rows
            if split["test"]["start"] <= row["date"] <= split["test"]["end"]]
    assert len(fit) == 430 * 7 and len(test) == 121 * 7
    parameters = dict(metrics["hyperparameter_search"]["selected_parameters"])
    legacy = model._fit(fit)
    calendar = model._fit_calendar(fit, parameters)
    predictions = {
        "baseline": [legacy["baseline_weekday_bucket_means"][f"{row['weekday']}|{row['bucket']}"]
                     for row in test],
        "model": [model._predict_calendar(calendar, model._parse_date(row["date"]), row["bucket"])
                  for row in test],
    }
    results = {}
    for name, values in predictions.items():
        result = bus_scores(test, values)
        for field in ["mae_per_hour", "wape_bucket_counts"]:
            assert result[field] == metrics["test"][name][field], (name, field, result, metrics["test"][name])
        result["mae_wape_reproduced"] = True
        result["by_bucket"] = {}
        result["by_weekday"] = {}
        for label in model.BUCKETS:
            indices = [i for i, row in enumerate(test) if row["bucket"] == label]
            result["by_bucket"][label] = bus_scores([test[i] for i in indices], [values[i] for i in indices])
        for day in range(7):
            indices = [i for i, row in enumerate(test) if row["weekday"] == day]
            result["by_weekday"][model.WEEKDAYS[day]] = bus_scores([test[i] for i in indices], [values[i] for i in indices])
        daytime_indices = [i for i, row in enumerate(test) if row["bucket"] != model.BUCKETS[0]]
        result["excluding_01_to_06_bucket"] = bus_scores(
            [test[i] for i in daytime_indices], [values[i] for i in daytime_indices])
        results[name] = result
    return {"source_id": "512", "source_sha256": metrics["source_sha256"],
            "fit_period": split["train"], "test_period": split["test"],
            "primary_metric": "관측값 대비 오차 20% 이내 비율",
            "primary_threshold_key": "0.2",
            "definition": "절대값(추정 시간당 인원 - 관측 시간당 인원) / 관측 시간당 인원이 0.2 이하인 셀 수 / 관측 인원이 양수인 평가 셀 수",
            "example": "관측값이 시간당 500명이면 400~600명으로 추정할 때 이 기준을 충족합니다.",
            "zero_policy": "관측값이 0이면 상대오차의 분모가 0이므로 상대오차 비율에서 제외하고 별도 개수와 정확히 0을 추정한 개수를 공개합니다. 절대오차 기준에는 포함합니다.",
            "parameters_frozen": parameters, "results": results}


def main():
    before = protected_hashes()
    consumption = evaluate_consumption()
    bus = evaluate_bus()
    after = protected_hashes()
    assert before == after, "Protected source/model artifacts changed"
    result = {"schema_version": 1, "date_kst": "2026-11-01", "service_version": 14,
              "threshold_protocol": "Thresholds were fixed in the task instructions before this computation; every specified sensitivity is reported. No threshold was chosen to maximize a result.",
              "not_classification_accuracy": True,
              "interpretation": "이 비율은 정의한 허용오차를 충족한 과거 관측의 비율입니다. 개인 여행 추천 정확도·만족도·신뢰확률을 뜻하지 않습니다.",
              "test_status": "Existing v13 test periods reused for retrospective reporting; no new external holdout.",
              "no_model_selection_or_tuning": True,
              "consumption": consumption, "bus": bus,
              "artifact_integrity": {"pass": before == after, "sha256_before": before, "sha256_after": after}}
    out = ROOT / "docs/제안서개선_20261101/쉬운성능지표.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": out.relative_to(ROOT).as_posix(),
        "consumption_primary": {name: record["tolerance_rates"]["1.0"] for name, record in consumption["results"].items()},
        "bus_primary": {name: record["relative_tolerance_rates"]["0.2"] for name, record in bus["results"].items()},
        "artifact_integrity_pass": before == after}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
