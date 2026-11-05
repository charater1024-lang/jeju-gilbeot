"""Monthly aggregate forecasting. Predictions never imply individual POI ranks.

This module needs only the Python standard library. Actual source CSVs must be
mapped to the documented canonical columns before use; it does not fetch data.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path


COLUMNS = {"month", "region", "category", "value", "measure", "source_id"}
MEASURES = {"transactions", "users", "amount_krw"}
SCOPE = "region_category_month"
ALGORITHM = "ridge_log1p_monthly_aggregate"


def _provenance(sources: list[str]) -> str:
    synthetic = [s.casefold().startswith("synthetic") for s in sources]
    return "synthetic" if all(synthetic) else "synthetic_with_mixed" if any(synthetic) else "unverified"


def _validate_model(model: object) -> dict:
    """Reject corrupt/edited models rather than silently truncating dot products."""
    invalid = "저장된 월별 집계 모델의 스키마가 올바르지 않습니다."
    if not isinstance(model, dict):
        raise ValueError(invalid)
    if type(model.get("version")) is not int or model["version"] != 1 or model.get("algorithm") != ALGORITHM:
        raise ValueError(invalid)
    if model.get("scope") != SCOPE or not isinstance(model.get("measure"), str) or model["measure"] not in MEASURES:
        raise ValueError(invalid)
    groups = model.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError(invalid)
    if any(not isinstance(g, list) or len(g) != 2 or any(not isinstance(s, str) or not s.strip() for s in g) for g in groups):
        raise ValueError(invalid)
    if len({tuple(g) for g in groups}) != len(groups):
        raise ValueError(invalid)
    weights = model.get("weights")
    if not isinstance(weights, list) or len(weights) != len(groups) + 4:
        raise ValueError(invalid)
    if any(type(w) not in (int, float) or not math.isfinite(w) for w in weights):
        raise ValueError(invalid)
    origin = model.get("origin_index")
    if type(origin) is not int or origin < 12:
        raise ValueError(invalid)
    trained = model.get("trained_through")
    if not isinstance(trained, str) or _month(trained) < origin:
        raise ValueError(invalid)
    sources = model.get("source_ids")
    if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or not s.strip() for s in sources):
        raise ValueError(invalid)
    if len(set(sources)) != len(sources) or model.get("data_provenance") != _provenance(sources):
        raise ValueError(invalid)
    checksum = model.get("training_csv_sha256")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError(invalid)
    return model


def _month(value: str) -> int:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", str(value)) or int(value[:4]) < 1:
        raise ValueError("month는 YYYY-MM 형식이어야 합니다.")
    year, month = map(int, value.split("-"))
    return year * 12 + month - 1


def _features(month: int, group: tuple[str, str], groups: list[tuple[str, str]], origin: int) -> list[float]:
    angle = 2 * math.pi * (month % 12) / 12
    return [1.0] + [float(group == key) for key in groups] + [math.sin(angle), math.cos(angle), (month - origin) / 12]


def _fit(rows: list[dict], groups: list[tuple[str, str]], origin: int) -> list[float]:
    """Ridge least squares on log1p(value), solved by coordinate descent."""
    features = [_features(r["index"], (r["region"], r["category"]), groups, origin) for r in rows]
    targets = [math.log1p(r["value"]) for r in rows]
    size = len(features[0])
    weights = [0.0] * size
    residual = targets[:]
    columns = [[x[j] for x in features] for j in range(size)]
    denominators = [sum(x * x for x in col) + (0.0 if j == 0 else 1.0) for j, col in enumerate(columns)]
    for _ in range(1000):
        change = 0.0
        for j, col in enumerate(columns):
            old = weights[j]
            new = sum(x * (r + old * x) for x, r in zip(col, residual)) / denominators[j]
            delta = new - old
            weights[j] = new
            change = max(change, abs(delta))
            for i, x in enumerate(col):
                residual[i] -= delta * x
        if change < 1e-8:
            break
    return weights


def _predict(weights: list[float], index: int, group: tuple[str, str], groups: list[tuple[str, str]], origin: int) -> float:
    log_value = sum(w * x for w, x in zip(weights, _features(index, group, groups, origin)))
    return math.expm1(min(35.0, max(0.0, log_value)))


def _scores(actual: list[float], predicted: list[float]) -> dict:
    absolute = sum(abs(a - p) for a, p in zip(actual, predicted))
    denominator = sum(actual)
    return {"mae": round(absolute / len(actual), 6), "wape": round(absolute / denominator, 6) if denominator else None, "n": len(actual)}


def _read(path: Path, raw: bytes | None = None) -> list[dict]:
    with io.StringIO((path.read_bytes() if raw is None else raw).decode("utf-8-sig"), newline="") as handle:
        reader = csv.DictReader(handle)
        missing = COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"필수 열 누락: {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError("월별 집계 데이터가 없습니다.")
    seen = set()
    measures = set()
    for row in rows:
        row["index"] = _month(row["month"])
        for field in ("region", "category", "measure", "source_id"):
            row[field] = row[field].strip()
            if not row[field]:
                raise ValueError(f"{field}가 비어 있습니다.")
        if row["measure"] not in MEASURES:
            raise ValueError("measure는 transactions, users, amount_krw 중 하나여야 합니다.")
        measures.add(row["measure"])
        key = (row["month"], row["region"], row["category"])
        if key in seen:
            raise ValueError("월·지역·업종 조합이 중복되었습니다. 서로 다른 제공처도 자동 합산하지 않습니다.")
        seen.add(key)
        try:
            row["value"] = float(row["value"])
        except (ValueError, TypeError) as exc:
            raise ValueError("value는 음수가 아닌 유한한 숫자여야 합니다.") from exc
        if not math.isfinite(row["value"]) or row["value"] < 0:
            raise ValueError("value는 음수가 아닌 유한한 숫자여야 합니다.")
    if len(measures) != 1:
        raise ValueError("한 모델에서 이용건수·이용자수·금액을 혼합할 수 없습니다.")
    return sorted(rows, key=lambda r: (r["index"], r["region"], r["category"]))


def train_context(csv_path: str | Path, output_dir: str | Path) -> dict:
    """Validate temporal holdout, then refit on all history and save JSON files.

    Returns {model_path, metrics_path, metrics}; paths are absolute strings.
    A minimum 15 distinct months leaves at least 12 pre-holdout months.
    """
    csv_path = Path(csv_path)
    raw = csv_path.read_bytes()
    rows = _read(csv_path, raw)
    checksum = hashlib.sha256(raw).hexdigest()
    months = sorted({r["month"] for r in rows})
    if len(months) < 15:
        raise ValueError("시간순 검증을 위해 최소 15개 관측월이 필요합니다.")
    split = int(len(months) * 0.8)
    train_months = set(months[:split])
    train = [r for r in rows if r["month"] in train_months]
    test = [r for r in rows if r["month"] not in train_months]
    groups = sorted({(r["region"], r["category"]) for r in train})
    if any((r["region"], r["category"]) not in groups for r in test):
        raise ValueError("검증 기간에만 등장한 지역·업종이 있습니다. 학습 이력이 필요합니다.")
    origin = train[0]["index"]
    weights = _fit(train, groups, origin)
    actual = [r["value"] for r in test]
    predicted = [_predict(weights, r["index"], (r["region"], r["category"]), groups, origin) for r in test]
    baseline = []
    for row in test:
        history = [r for r in train if (r["region"], r["category"]) == (row["region"], row["category"])]
        seasonal = [r["value"] for r in history if r["index"] % 12 == row["index"] % 12]
        values = seasonal or [r["value"] for r in history[-3:]]
        baseline.append(sum(values) / len(values))
    sources = sorted({r["source_id"] for r in rows})
    provenance = _provenance(sources)
    metrics = {
        "scope": SCOPE, "measure": rows[0]["measure"], "data_provenance": provenance, "training_csv_sha256": checksum,
        "split": "last_20_percent_of_distinct_months", "validation_training_through": months[split - 1],
        "validation_from": months[split], "validation_through": months[-1],
        "training_rows": len(train), "validation_rows": len(test),
        "model": _scores(actual, predicted), "baseline": _scores(actual, baseline),
        "baseline_method": "training_only_same_calendar_month_mean_else_last_three_observations_mean",
        "limitations": ["합성 자료가 포함된 점수는 실제 서비스 성능이 아닙니다." if provenance.startswith("synthetic") else "출처와 이용권한은 별도 검증이 필요합니다.", "지역·업종 집계 예측이며 개별 식당 인기나 음식 품질을 나타내지 않습니다."],
    }
    model = {
        "version": 1, "algorithm": ALGORITHM, "scope": SCOPE,
        "measure": rows[0]["measure"], "groups": [list(g) for g in groups],
        "origin_index": origin, "weights": _fit(rows, groups, origin),
        "trained_through": months[-1], "source_ids": sources, "data_provenance": provenance, "training_csv_sha256": checksum,
        "feature_order": "intercept,group_one_hot,sin_month,cos_month,years_since_origin",
        "ridge_alpha": 1.0, "log_prediction_clip": [0, 35],
        "notes": "검증은 과거 80%로만 학습한 모델을 사용했고 저장 모델은 전체 기간으로 재학습했습니다.",
    }
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    model_path = output / "model_context.json"
    metrics_path = output / "metrics_context.json"
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"model_path": str(model_path), "metrics_path": str(metrics_path), "metrics": metrics}


def forecast_context(model_path: str | Path, month: str) -> list[dict]:
    """Forecast each known region/category for a strictly future calendar month."""
    index = _month(month)
    model = _validate_model(json.loads(Path(model_path).read_text(encoding="utf-8")))
    horizon = index - _month(model["trained_through"])
    if horizon <= 0:
        raise ValueError("예측월은 모델 학습 최종월보다 미래여야 합니다.")
    warnings = []
    if horizon > 3:
        warnings.append("학습 최종월보다 3개월 넘게 떨어진 외삽으로 불확실성이 큽니다.")
    if model["data_provenance"].startswith("synthetic"):
        warnings.append("합성 데이터가 포함된 학습 예측입니다. 실제 제주 수요나 맛집 순위가 아닙니다.")
    groups = [tuple(g) for g in model["groups"]]
    return [{
        "month": month, "region": region, "category": category,
        "predicted_value": round(_predict(model["weights"], index, (region, category), groups, model["origin_index"]), 3),
        "measure": model["measure"], "scope": SCOPE, "trained_through": model["trained_through"],
        "horizon_months": horizon, "data_provenance": model["data_provenance"],
        "source_ids": model["source_ids"], "warnings": warnings[:],
    } for region, category in groups]
