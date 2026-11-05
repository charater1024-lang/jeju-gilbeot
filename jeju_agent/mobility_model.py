"""Learn historical island-wide regular-ticket bus demand patterns on CPU.

Source 512 contains ticket categories, not resident/tourist identities. This model
never estimates bus timetables, available seats, an individual route's load, or
current conditions. Missing observations are never converted to zero counts.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any
from functools import lru_cache


SCHEMA_VERSION = 2
ALGORITHM = "recency_weighted_huber_calendar_regression"
LEGACY_ALGORITHM = "ridge_log1p_hourly_regular_ticket_demand"
BASELINE_ALGORITHM = "weekday_bucket_mean_hourly_regular_ticket_demand"
SOURCE_ID = "512"
SCOPE = "제주 전체 일반승차 집계"
BUCKETS = ["01시-06시", "07시-09시", "10시-12시", "13시-15시", "16시-18시", "19시-21시", "22시-24시"]
HOURS = {label: 6 if index == 0 else 3 for index, label in enumerate(BUCKETS)}
PERIODS = {"morning": BUCKETS[1:3], "daytime": BUCKETS[2:5], "evening": BUCKETS[5:7], "all": list(BUCKETS)}
FEATURES = ["intercept"] + [f"bucket:{label}" for label in BUCKETS] + [f"weekday:{index}" for index in range(7)] + ["month_sin", "month_cos"]
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _today_kst() -> dt.date:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()


def _parse_date(value: Any) -> dt.date:
    if not isinstance(value, str):
        raise ValueError("날짜는 YYYY-MM-DD 또는 YYYYMMDD 문자열이어야 합니다.")
    value = value.strip()
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date() if len(value) == 8 and value.isdigit() else dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("올바른 날짜를 입력하세요. 형식은 YYYY-MM-DD입니다.") from exc


def _finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _read_rows(csv_path: Path) -> tuple[list[dict], dict]:
    """Validate observed cells and select the complete regular-ticket panel."""
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        date_field = "base_date" if "base_date" in fields else "date"
        required = {date_field, "day_of_week", "base_hour", "user_type", "user_count"}
        if not required <= fields:
            raise ValueError(f"승차 데이터 필수 열이 없습니다: {', '.join(sorted(required - fields))}")
        selected, seen, counts = [], set(), {}
        raw_rows = 0
        for line, raw in enumerate(reader, start=2):
            raw_rows += 1
            day = _parse_date(raw.get(date_field))
            bucket = str(raw.get("base_hour", "")).strip()
            user_type = str(raw.get("user_type", "")).strip()
            if bucket not in HOURS or not user_type:
                raise ValueError(f"{line}행의 시간대 또는 승차 구분이 올바르지 않습니다.")
            weekday = str(raw.get("day_of_week", "")).strip().removesuffix("요일")
            if weekday != WEEKDAYS[day.weekday()]:
                raise ValueError(f"{line}행의 날짜와 요일이 일치하지 않습니다.")
            key = (day.isoformat(), bucket, user_type)
            if key in seen:
                raise ValueError(f"중복 승차 관측 행이 있습니다: {key}")
            seen.add(key)
            text = str(raw.get("user_count", "")).strip()
            try:
                count = float(text)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{line}행의 user_count가 비어 있거나 숫자가 아닙니다.") from exc
            if not math.isfinite(count) or count < 0 or count > 1_000_000_000 or not count.is_integer():
                raise ValueError(f"{line}행의 user_count는 0 이상의 유한한 정수여야 합니다.")
            counts[user_type] = counts.get(user_type, 0) + 1
            if user_type == "일반":
                selected.append({"date": day.isoformat(), "weekday": day.weekday(), "bucket": bucket, "hours": HOURS[bucket], "count": int(count), "rate": count / HOURS[bucket]})
    days = sorted({row["date"] for row in selected})
    if len(days) < 28:
        raise ValueError("일반승차의 최소 28일 관측이 필요합니다.")
    dates_expected = (_parse_date(days[-1]) - _parse_date(days[0])).days + 1
    if dates_expected != len(days):
        raise ValueError("일반승차 관측에 누락된 날짜가 있습니다. 누락을 0으로 채우지 말고 원자료를 확인하세요.")
    if len(selected) != len(days) * len(BUCKETS):
        raise ValueError("일반승차의 날짜별 7개 시간대가 완전하지 않습니다. 결측 셀을 0으로 채우지 않습니다.")
    return sorted(selected, key=lambda row: (row["date"], BUCKETS.index(row["bucket"]))), {
        "raw_rows": raw_rows, "selected_rows": len(selected), "selected_user_type": "일반",
        "ticket_type_rows": counts, "excluded_rows": raw_rows - len(selected),
        "excluded_types": sorted(key for key in counts if key != "일반"),
        "missing_cells_imputed": 0,
    }


def _features(day: dt.date, bucket: str) -> list[float]:
    phase = (day.month - 1) * 2 * math.pi / 12
    return [1.0] + [float(bucket == label) for label in BUCKETS] + [float(day.weekday() == weekday) for weekday in range(7)] + [math.sin(phase), math.cos(phase)]


def _solve(matrix: list[list[float]], target: list[float]) -> list[float]:
    size = len(target)
    data = [list(row) + [value] for row, value in zip(matrix, target)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(data[row][col]))
        if abs(data[pivot][col]) < 1e-12:
            raise ValueError("학습 행렬이 특이합니다. 관측 기간과 수치를 확인하세요.")
        data[col], data[pivot] = data[pivot], data[col]
        divisor = data[col][col]
        for index in range(col, size + 1):
            data[col][index] /= divisor
        for row in range(col + 1, size):
            factor = data[row][col]
            for index in range(col, size + 1):
                data[row][index] -= factor * data[col][index]
    result = [0.0] * size
    for row in range(size - 1, -1, -1):
        result[row] = data[row][size] - sum(data[row][col] * result[col] for col in range(row + 1, size))
    return result


def _fit(rows: list[dict], alpha: float = 1.0) -> dict:
    size = len(FEATURES)
    matrix, target = [[0.0] * size for _ in range(size)], [0.0] * size
    grouped: dict[str, list[float]] = {}
    for row in rows:
        x = _features(_parse_date(row["date"]), row["bucket"])
        y = math.log1p(row["rate"])
        active = [(index, value) for index, value in enumerate(x) if value]
        for index, value in active:
            target[index] += value * y
            for other, coefficient in active:
                matrix[index][other] += value * coefficient
        grouped.setdefault(f"{row['weekday']}|{row['bucket']}", []).append(row["rate"])
    for index in range(size):
        matrix[index][index] += alpha if index else 1e-8
    means = {key: sum(values) / len(values) for key, values in grouped.items()}
    return {"weights": _solve(matrix, target), "baseline_weekday_bucket_means": means}


def _predict_rate(weights: list[float], day: dt.date, bucket: str) -> float:
    log_rate = sum(weight * value for weight, value in zip(weights, _features(day, bucket)))
    return math.expm1(max(0.0, min(math.log1p(1_000_000_000), log_rate)))


def _score(rows: list[dict], fitted: dict) -> dict:
    learned, baseline = [], []
    for row in rows:
        learned.append(_predict_rate(fitted["weights"], _parse_date(row["date"]), row["bucket"]))
        baseline.append(fitted["baseline_weekday_bucket_means"][f"{row['weekday']}|{row['bucket']}"])

    def metrics(predictions: list[float]) -> dict:
        errors = [abs(row["rate"] - value) for row, value in zip(rows, predictions)]
        count_error = sum(error * row["hours"] for error, row in zip(errors, rows))
        observed = sum(row["count"] for row in rows)
        return {"mae_per_hour": round(sum(errors) / len(rows), 4), "wape_bucket_counts": round(count_error / observed, 6) if observed else None, "mae_bucket_count": round(count_error / len(rows), 4), "observations": len(rows), "observed_bucket_users": observed}

    learned_metrics, baseline_metrics = metrics(learned), metrics(baseline)
    return {"model": learned_metrics, "baseline": baseline_metrics, "model_better_than_baseline_mae": learned_metrics["mae_per_hour"] < baseline_metrics["mae_per_hour"]}


def _model_digest(model: dict) -> str:
    payload = {key: value for key, value in model.items() if key != "model_sha256"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _calendar_features(day: dt.date, harmonics: int, interact: bool) -> list[float]:
    """Known calendar only: no observed validation/test counts or future lags."""
    phase = (day.timetuple().tm_yday - 1) * 2 * math.pi / 365.25
    cyclic = [value for order in range(1, harmonics + 1)
              for value in (math.sin(order * phase), math.cos(order * phase))]
    return ([float(day.weekday() == index) for index in range(7)] + cyclic
            + ([value * float(day.weekday() >= 5) for value in cyclic] if interact else []))


def _candidate_parameters() -> list[dict]:
    """Fixed v14 search space, selected solely on the chronological validation."""
    return [{"harmonics": harmonics, "interact": interact, "alpha": alpha,
             "half_life_days": half, "robust": robust}
            for half in [None, 90, 180, 360]
            for harmonics in [0, 1, 2]
            for interact in ([False, True] if harmonics else [False])
            for alpha in ([1, 10, 100] if harmonics else [1])
            for robust in [False, True]]


def _fit_calendar(rows: list[dict], parameters: dict) -> dict:
    """Separate bucket regressions give full weekday x bucket interactions.

    Cyclic effects and their weekend interactions are regularized. Six Huber
    IRLS steps reduce outlier influence; exponential weights favor recent actual
    observations. Both scale and robust residual threshold use fit rows only.
    """
    end = _parse_date(rows[-1]["date"])
    bucket_models = {}
    for bucket in BUCKETS:
        group = [row for row in rows if row["bucket"] == bucket]
        dates = [_parse_date(row["date"]) for row in group]
        design = [_calendar_features(day, parameters["harmonics"], parameters["interact"]) for day in dates]
        scale = max(1.0, statistics.median(row["rate"] for row in group))
        target = [row["rate"] / scale for row in group]
        half = parameters["half_life_days"]
        base_weights = [0.5 ** ((end - day).days / half) if half else 1.0 for day in dates]
        weights = list(base_weights)
        size = len(design[0])
        active_rows = [[(index, value) for index, value in enumerate(x) if value] for x in design]
        for iteration in range(6 if parameters["robust"] else 1):
            matrix = [[0.0] * size for _ in range(size)]
            vector = [0.0] * size
            for active, y, weight in zip(active_rows, target, weights):
                for index, value in active:
                    weighted = weight * value
                    vector[index] += weighted * y
                    for other, coefficient in active:
                        matrix[index][other] += weighted * coefficient
            for index in range(size):
                matrix[index][index] += 0.001 if index < 7 else parameters["alpha"]
            coefficients = _solve(matrix, vector)
            if parameters["robust"]:
                residuals = [y - sum(coefficients[index] * value for index, value in active)
                             for active, y in zip(active_rows, target)]
                threshold = max(0.005, statistics.median(abs(value) for value in residuals) * 1.4826 * 1.35)
                weights = [base * min(1.0, threshold / max(1e-10, abs(residual)))
                           for base, residual in zip(base_weights, residuals)]
        bucket_models[bucket] = {"scale": scale, "coefficients": coefficients}
    return {"parameters": dict(parameters), "bucket_models": bucket_models}


def _predict_calendar(fitted: dict, day: dt.date, bucket: str) -> float:
    parameters = fitted["parameters"]
    features = _calendar_features(day, parameters["harmonics"], parameters["interact"])
    values = fitted["bucket_models"][bucket]
    rate = sum(weight * value for weight, value in zip(values["coefficients"], features)) * values["scale"]
    return max(0.0, min(1_000_000_000.0, rate))


def _metrics(rows: list[dict], predictions: list[float]) -> dict:
    errors = [abs(row["rate"] - value) for row, value in zip(rows, predictions)]
    count_error = sum(error * row["hours"] for error, row in zip(errors, rows))
    observed = sum(row["count"] for row in rows)
    return {"mae_per_hour": round(sum(errors) / len(rows), 4),
            "rmse_per_hour": round(math.sqrt(sum(error * error for error in errors) / len(rows)), 4),
            "wape_bucket_counts": round(count_error / observed, 6) if observed else None,
            "mae_bucket_count": round(count_error / len(rows), 4),
            "observations": len(rows), "observed_bucket_users": observed}


def _evaluate(rows: list[dict], calendar: dict, legacy: dict) -> dict:
    predictions = [_predict_calendar(calendar, _parse_date(row["date"]), row["bucket"]) for row in rows]
    baseline = [legacy["baseline_weekday_bucket_means"][f"{row['weekday']}|{row['bucket']}"] for row in rows]
    ridge = [_predict_rate(legacy["weights"], _parse_date(row["date"]), row["bucket"]) for row in rows]
    report = {"model": _metrics(rows, predictions), "baseline": _metrics(rows, baseline),
              "legacy_ridge": _metrics(rows, ridge)}
    report["model_better_than_baseline_mae"] = report["model"]["mae_per_hour"] < report["baseline"]["mae_per_hour"]
    report["mae_reduction_percent_vs_baseline"] = round(100 * (1 - report["model"]["mae_per_hour"] / report["baseline"]["mae_per_hour"]), 4)
    report["by_bucket"] = {}
    report["by_weekday"] = {}
    for key, values, field in [("by_bucket", BUCKETS, "bucket"), ("by_weekday", range(7), "weekday")]:
        for value in values:
            indices = [index for index, row in enumerate(rows) if row[field] == value]
            subset = [rows[index] for index in indices]
            if subset:
                report[key][str(value)] = {"model": _metrics(subset, [predictions[index] for index in indices]),
                                           "baseline": _metrics(subset, [baseline[index] for index in indices])}
    return report


def _select_serving(validation_mae: dict) -> str:
    """Tie preference is baseline; the test is not accepted by this function."""
    return min(["weekday_bucket_mean", "ridge", "huber_calendar"], key=lambda name: validation_mae[name])


def train_mobility(csv_path: Path, output_dir: Path) -> dict:
    csv_path, output_dir = Path(csv_path), Path(output_dir)
    rows, source_selection = _read_rows(csv_path)
    days = sorted({row["date"] for row in rows})
    train_cut, validation_cut = int(len(days) * 0.64), int(len(days) * 0.82)
    train_days, validation_days, test_days = days[:train_cut], days[train_cut:validation_cut], days[validation_cut:]
    training = [row for row in rows if row["date"] <= train_days[-1]]
    validation = [row for row in rows if validation_days[0] <= row["date"] <= validation_days[-1]]
    test = [row for row in rows if row["date"] >= test_days[0]]
    legacy = _fit(training)
    candidates = []
    best_fit, best_parameters, best_mae = None, None, float("inf")
    for parameters in _candidate_parameters():
        fitted = _fit_calendar(training, parameters)
        predictions = [_predict_calendar(fitted, _parse_date(row["date"]), row["bucket"]) for row in validation]
        score = _metrics(validation, predictions)
        # Full precision comparison; rounded metrics are presentation only.
        mae = sum(abs(row["rate"] - pred) for row, pred in zip(validation, predictions)) / len(validation)
        candidates.append({"parameters": parameters, **score})
        if mae < best_mae:
            best_fit, best_parameters, best_mae = fitted, parameters, mae
    validation_report = _evaluate(validation, best_fit, legacy)
    validation_mae = {"huber_calendar": best_mae,
                      "ridge": sum(abs(row["rate"] - _predict_rate(legacy["weights"], _parse_date(row["date"]), row["bucket"])) for row in validation) / len(validation),
                      "weekday_bucket_mean": sum(abs(row["rate"] - legacy["baseline_weekday_bucket_means"][f"{row['weekday']}|{row['bucket']}"]) for row in validation) / len(validation)}
    selected = _select_serving(validation_mae)
    # Selection is now frozen. No test metric participates in the gate/search.
    test_report = _evaluate(test, best_fit, legacy)
    why = "시간순 검증 구간의 시간당 MAE가 가장 낮은 모형을 선택했습니다. 테스트 오차는 선택에 사용하지 않았습니다."
    serving = {"selected_serving_model": selected, "selection_metric": "validation_mae_per_hour",
               "validation_mae_per_hour": validation_mae, "why": why, "test_used_for_selection": False}

    def period(dates, partition):
        return {"start": dates[0], "end": dates[-1], "days": len(dates), "rows": len(partition)}

    source_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    limitations = [
        "관측 단위는 제주 전체 일반승차 집계입니다. 일반은 승차권 구분이며 도민·관광객 구분이 아닙니다.",
        "다른 승차권 구분의 누락 셀은 0으로 채우지 않았으며 이 모델에서 제외했습니다.",
        "시간대별 총승차 인원을 해당 구간의 시간 수로 나눠 시간당 수요를 학습했습니다.",
        "원자료 시간구간 라벨의 정확한 경계와 실제 버스 출발시각은 별도 검증하지 않았습니다.",
        "과거 승차 패턴 참고용이며 현재·미래 실시간 수요·좌석·버스별 혼잡·운행시간을 예측하지 않습니다.",
        "선택일의 요일과 연중 주기를 조회하며 장기 증가 추세를 외삽하지 않습니다.",
        "기존 v13에서 공개된 과거 테스트 구간을 재사용한 후향 비교입니다. 새로운 미공개 자료에서의 성능은 별도 검증해야 합니다.",
        "테스트 관측값으로 후보 또는 하이퍼파라미터를 선택하지 않았습니다. 운영 모델은 평가 후 전체 관측자료로 다시 적합했습니다.",
        "예측구간·신뢰구간을 제공하지 않으며 일반 승차 합계는 고유 승객 수가 아닙니다.",
    ]
    metrics = {"schema_version": SCHEMA_VERSION, "source_id": SOURCE_ID,
               "source_title": "시간대별 승차인원 현황", "scope": SCOPE, "algorithm": ALGORITHM,
               "source_sha256": source_sha256, "source_url": "https://www.jejudatahub.net/data/view/data/512",
               "original_provider": "제주빅데이터센터", "data_mode": "observed",
               "observation_period": {"start": days[0], "end": days[-1], "days": len(days)},
               "selection": source_selection,
               "split": {"method": "chronological_64_18_18_percent_of_dates", "train": period(train_days, training),
                         "validation": period(validation_days, validation), "test": period(test_days, test),
                         "evaluation_fit_scope": "training_partition_only_for_both_validation_and_test",
                         "validation_used_for_tuning": True, "baseline_fit_scope": "training_partition_only",
                         "test_status": "previously_reported_retrospective_holdout_not_new_external_test"},
               "validation": validation_report, "test": test_report, "serving_selection": serving,
               "hyperparameter_search": {"candidate_count": len(candidates), "selected_parameters": best_parameters,
                                         "criterion": "validation_mae_per_hour", "test_used": False, "candidates": candidates},
               "limitations": limitations,
               "metric_definitions": {"mae_per_hour": "평균 절대 오차 인원/시간",
                                      "rmse_per_hour": "오차 제곱평균의 제곱근 인원/시간; 큰 오차에 더 민감",
                                      "wape_bucket_counts": "구간 인원 절대오차 합 / 관측 구간 인원 합; 0.1은 10%",
                                      "mae_bucket_count": "구간별 인원 절대오차 평균",
                                      "baseline": "같은 최초 학습구간의 요일·시간대 산술 평균",
                                      "interval": "예측구간 및 신뢰구간을 제공하지 않음"}}
    final_legacy = _fit(rows)
    final_calendar = _fit_calendar(rows, best_parameters)
    model = {"schema_version": SCHEMA_VERSION, "model_version": "mobility_regular_v2", "algorithm": ALGORITHM,
             "source_id": SOURCE_ID, "source_title": metrics["source_title"], "source_file_name": csv_path.name,
             "source_sha256": source_sha256, "source_url": metrics["source_url"], "scope": SCOPE, "user_type": "일반",
             "data_mode": "observed", "observation_period": metrics["observation_period"], "training_rows": len(rows),
             "feature_order": FEATURES, "buckets": BUCKETS, "bucket_hours": HOURS,
             "weights": final_legacy["weights"], "baseline_weekday_bucket_means": final_legacy["baseline_weekday_bucket_means"],
             "calendar": final_calendar, "ridge_alpha": 1.0, "target": "user_count_per_hour",
             "prediction_log_clip": [0.0, math.log1p(1_000_000_000)], "limitations": limitations,
             "selected_evaluation": {"validation": validation_report["baseline" if selected == "weekday_bucket_mean" else "legacy_ridge" if selected == "ridge" else "model"],
                                     "test": test_report["baseline" if selected == "weekday_bucket_mean" else "legacy_ridge" if selected == "ridge" else "model"]}}
    model.update(serving)
    model["model_sha256"] = _model_digest(model)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "mobility_model.json").write_text(json.dumps(model, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "mobility_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    _load_cached.cache_clear()
    return metrics


def _validate_model(model: Any) -> None:
    if not isinstance(model, dict) or model.get("schema_version") != SCHEMA_VERSION or model.get("algorithm") != ALGORITHM or model.get("model_version") != "mobility_regular_v2" or model.get("source_id") != SOURCE_ID or model.get("user_type") != "일반" or model.get("scope") != SCOPE or model.get("data_mode") != "observed":
        raise ValueError("지원하지 않는 승차 패턴 모델입니다. 다시 학습하세요.")
    if model.get("feature_order") != FEATURES or model.get("buckets") != BUCKETS or model.get("bucket_hours") != HOURS:
        raise ValueError("모델의 특성 정의 또는 시간대 길이가 올바르지 않습니다.")
    weights = model.get("weights")
    if not isinstance(weights, list) or len(weights) != len(FEATURES) or any(not _finite(value) for value in weights):
        raise ValueError("모델 계수 차원과 유한한 수치를 확인하세요.")
    baseline = model.get("baseline_weekday_bucket_means")
    expected = {f"{weekday}|{label}" for weekday in range(7) for label in BUCKETS}
    if not isinstance(baseline, dict) or set(baseline) != expected or any(not _finite(value) or value < 0 for value in baseline.values()):
        raise ValueError("모델의 학습 기준 평균값이 올바르지 않습니다.")
    period = model.get("observation_period")
    if not isinstance(period, dict):
        raise ValueError("모델 관측 기간이 없습니다.")
    start, end = _parse_date(period.get("start")), _parse_date(period.get("end"))
    if start > end or period.get("days") != (end - start).days + 1 or model.get("training_rows") != period["days"] * len(BUCKETS):
        raise ValueError("모델의 관측 기간과 행 수가 일치하지 않습니다.")
    source_hash = model.get("source_sha256")
    if not isinstance(source_hash, str) or len(source_hash) != 64 or any(char not in "0123456789abcdef" for char in source_hash):
        raise ValueError("모델의 원자료 SHA256이 올바르지 않습니다.")
    selected = model.get("selected_serving_model")
    validation_mae = model.get("validation_mae_per_hour")
    if selected not in {"ridge", "weekday_bucket_mean", "huber_calendar"} or model.get("selection_metric") != "validation_mae_per_hour" or model.get("test_used_for_selection") is not False:
        raise ValueError("서비스 모델 선택 기준이 올바르지 않습니다. 검증 구간으로 다시 선택하세요.")
    if not isinstance(validation_mae, dict) or set(validation_mae) != {"ridge", "weekday_bucket_mean", "huber_calendar"} or any(not _finite(value) or value < 0 for value in validation_mae.values()):
        raise ValueError("서비스 모델의 검증 오차 정보가 올바르지 않습니다.")
    expected_selected = _select_serving(validation_mae)
    if selected != expected_selected or not isinstance(model.get("why"), str):
        raise ValueError("서비스 모델 선택이 검증 오차와 일치하지 않습니다.")
    calendar = model.get("calendar")
    if not isinstance(calendar, dict) or set(calendar) != {"parameters", "bucket_models"}:
        raise ValueError("달력 회귀 모델 정의가 올바르지 않습니다.")
    parameters = calendar.get("parameters")
    if not isinstance(parameters, dict) or parameters not in _candidate_parameters():
        raise ValueError("달력 회귀의 학습 매개변수가 올바르지 않습니다.")
    if type(parameters["harmonics"]) is not int or type(parameters["interact"]) is not bool or type(parameters["robust"]) is not bool:
        raise ValueError("달력 회귀의 특성 자료형이 올바르지 않습니다.")
    expected_size = 7 + 2 * parameters["harmonics"] * (2 if parameters["interact"] else 1)
    buckets = calendar.get("bucket_models")
    if not isinstance(buckets, dict) or set(buckets) != set(BUCKETS):
        raise ValueError("달력 회귀의 시간대 모델이 올바르지 않습니다.")
    for bucket in buckets.values():
        if not isinstance(bucket, dict) or not _finite(bucket.get("scale")) or not 1 <= bucket["scale"] <= 1_000_000_000:
            raise ValueError("달력 회귀의 학습 스케일이 올바르지 않습니다.")
        coefficients = bucket.get("coefficients")
        if not isinstance(coefficients, list) or len(coefficients) != expected_size or any(not _finite(value) for value in coefficients):
            raise ValueError("달력 회귀의 계수 차원과 유한한 수치를 확인하세요.")
    if model.get("model_sha256") != _model_digest(model):
        raise ValueError("모델 파일의 SHA256 검증에 실패했습니다. 다시 학습하세요.")


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        model = json.load(handle)
    _validate_model(model)
    return model


def predict_mobility(model_path: Path, date: str, period: str = "daytime") -> dict:
    """Compare selected-day patterns learned from historical data, not live demand."""
    day = _parse_date(date)
    if not isinstance(period, str) or period not in PERIODS:
        raise ValueError("period는 morning, daytime, evening, all 중 하나여야 합니다.")
    path = Path(model_path).resolve()
    model = _load_cached(str(path), path.stat().st_mtime_ns)
    selected = model["selected_serving_model"]
    if selected == "huber_calendar":
        rates = [_predict_calendar(model["calendar"], day, label) for label in BUCKETS]
    elif selected == "ridge":
        rates = [_predict_rate(model["weights"], day, label) for label in BUCKETS]
    else:
        rates = [model["baseline_weekday_bucket_means"][f"{day.weekday()}|{label}"] for label in BUCKETS]
    low, high = min(rates), max(rates)
    slots = []
    for label, rate in zip(BUCKETS, rates):
        relative = (rate - low) / (high - low) if high > low else 0.5
        preferred = label in PERIODS[period]
        slots.append({"label": label, "bucket_hours": HOURS[label], "predicted_users_per_hour": round(rate, 2), "predicted_bucket_users": round(rate * HOURS[label], 2), "relative_demand": round(relative, 4), "within_preferred_period": preferred, "recommendation_eligible": preferred and label != BUCKETS[0]})
    candidates = [slot for slot in slots if slot["recommendation_eligible"]]
    recommended = min(candidates, key=lambda slot: (slot["predicted_users_per_hour"], BUCKETS.index(slot["label"])))
    end = _parse_date(model["observation_period"]["end"])
    age = max(0, (_today_kst() - end).days)
    warnings = [
        "과거 자료로 학습한 일반승차 패턴 참고입니다. 선택일의 실제 혼잡도 또는 실시간 예측이 아닙니다.",
        "일반은 승차권 구분입니다. 일반승차 집계를 도민이나 관광객 전체의 이동으로 해석할 수 없습니다.",
        "시간당 인원은 01시-06시 구간 6시간, 다른 구간 3시간으로 나눈 비교값입니다.",
        "추천 시간대는 선택한 범위 안에서 학습된 시간당 수요가 가장 낮은 원자료 라벨입니다. 개별 버스의 출발 시각·좌석·노선 혼잡을 뜻하지 않습니다.",
        "시간대의 정확한 경계는 별도 검증하지 않았으며 출발시각을 생성하지 않습니다. 01시-06시 라벨은 기본 추천 대상에서 제외했습니다.",
    ]
    if age > 90:
        warnings.insert(0, f"관측 마지막 날짜는 {end.isoformat()}이며 현재 기준 {age}일 전입니다. 오래된 과거 패턴으로만 참고하세요.")
    if selected == "weekday_bucket_mean":
        warnings.append("검증 오차가 낮거나 같은 요일·시간대 평균을 서비스 기본으로 선택했습니다. Ridge 회귀 실험 결과도 평가 보고서에 남겼습니다.")
    elif selected == "huber_calendar":
        warnings.append("시간대별 요일·연중 주기·주말 계절 효과를 학습한 최근 가중 Huber 회귀를 사용합니다. 원자료가 없는 현재의 실제 관측으로 보정하지 않았습니다.")
    if day <= end:
        warnings.append("선택일은 학습 자료의 관측 기간 안이거나 그 이전입니다. 이 출력은 과거를 재현한 검증 예측값이 아닙니다.")
    algorithm = ALGORITHM if selected == "huber_calendar" else LEGACY_ALGORITHM if selected == "ridge" else BASELINE_ALGORITHM
    features = "bucket_weekday_annual_weekend_interactions_no_future_trend" if selected == "huber_calendar" else "bucket_weekday_month_no_future_trend" if selected == "ridge" else "weekday_bucket_means_no_future_trend"
    return {"status": "historical_pattern", "source_id": SOURCE_ID, "source_title": model["source_title"], "source_sha256": model["source_sha256"], "scope": SCOPE, "selected_date": day.isoformat(), "period": period, "observation_period": model["observation_period"], "as_of_date": _today_kst().isoformat(), "data_age_days": age, "is_stale": age > 90, "freshness": "stale_historical_reference" if age > 90 else "historical_reference", "slots": slots, "recommended_slot": recommended, "model": {"algorithm": algorithm, "candidate_algorithm": ALGORITHM, "selected_serving_model": selected, "selection_metric": model["selection_metric"], "selection_why": model["why"], "version": model["model_version"], "target": "log1p_user_count_per_hour" if selected == "ridge" else "user_count_per_hour", "feature_scope": features, "scope": SCOPE, "evaluation": model["selected_evaluation"]}, "warnings": warnings}
