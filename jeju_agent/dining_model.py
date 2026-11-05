"""Observed Hub 1047 dining compositions, learned and served without an LLM.

The fixed retrospective common panel contains fully observed food/snack classes.
It measures card transaction composition, not restaurant ratings or meal prices.
"""
import csv
import datetime as dt
import hashlib
import io
import json
import math
from functools import lru_cache
from pathlib import Path

SOURCE_ID = "1047"
SOURCE_URL = "https://www.jejudatahub.net/data/view/data/1047"
SOURCE_RELATIVE = "data_raw/hub/hub_1047_5831.csv"
MODEL_RELATIVE = "models_dining/dining_model.json"
EXCLUDED_PARENTS = {"간이주점", "유흥주점"}
ALGORITHM = "recency_weighted_seasonal_ridge_composition"


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _month_index(month):
    year, number = map(int, month.split("-"))
    if number not in range(1, 13):
        raise ValueError("올바른 월이 아닙니다.")
    return year * 12 + number


def read_panels(path):
    """Aggregate sexes only after checking keys and exact observed availability."""
    snapshot = Path(path).read_bytes()
    reader = csv.DictReader(io.StringIO(snapshot.decode("cp949")))
    required = {"연월", "중분류업종명", "소분류업종명", "성별", "이용건수", "이용금액"}
    if not required <= set(reader.fieldnames or []):
        raise ValueError("1047 원자료의 필수 열이 없습니다.")
    observations = {}
    parents = {}
    availability = {}
    months = set()
    raw_rows = 0
    for row in reader:
        raw_rows += 1
        compact = row["연월"]
        if len(compact) != 6 or not compact.isdigit():
            raise ValueError("1047 연월 형식이 올바르지 않습니다.")
        dt.datetime.strptime(compact, "%Y%m")
        month = compact[:4] + "-" + compact[4:]
        name, parent, sex = row["소분류업종명"].strip(), row["중분류업종명"].strip(), row["성별"]
        if not name or not parent or sex not in {"남성", "여성"}:
            raise ValueError("1047 업종명 또는 성별 분류를 확인해야 합니다.")
        if name in parents and parents[name] != parent:
            raise ValueError("1047 소분류의 중분류 연결이 일관되지 않습니다.")
        parents[name] = parent
        key = (month, name, sex)
        if key in observations:
            raise ValueError("1047 중복 관측입니다.")
        numbers = []
        for field in ("이용건수", "이용금액"):
            value = float(row[field])
            if not math.isfinite(value) or value < 0 or not value.is_integer():
                raise ValueError("1047 이용건수·금액은 유한한 0 이상의 정수여야 합니다.")
            numbers.append(int(value))
        observations[key] = tuple(numbers)
        availability.setdefault(name, set()).add((month, sex))
        months.add(month)
    months = sorted(months)
    if len(months) < 48:
        raise ValueError("1047 분석에는 최소 48개월 실제 관측이 필요합니다.")
    expected = {(month, sex) for month in months for sex in ("남성", "여성")}
    categories = sorted(name for name in parents
                        if parents[name] not in EXCLUDED_PARENTS and availability[name] == expected)
    if len(categories) < 2:
        raise ValueError("1047 완전 관측 외식업종이 부족합니다.")
    parent_names = sorted({parents[name] for name in categories})
    parent_indices = {name: [i for i, category in enumerate(categories) if parents[category] == name]
                      for name in parent_names}
    panels = []
    for month in months:
        counts = [sum(observations[month, name, sex][0] for sex in ("남성", "여성")) for name in categories]
        amounts = [sum(observations[month, name, sex][1] for sex in ("남성", "여성")) for name in categories]
        total = sum(counts)
        if total <= 0:
            raise ValueError("1047 월별 이용건수 합이 0입니다.")
        if any(sum(counts[i] for i in indices) <= 0 for indices in parent_indices.values()):
            raise ValueError("1047 중분류의 이용건수가 0이어서 계층형 비교가 불가능합니다.")
        panels.append({"month": month, "calendar_month": int(month[-2:]), "counts": counts,
                       "amounts": amounts, "shares": [number / total for number in counts]})
    first, last = _month_index(months[0]), _month_index(months[-1])
    missing_months = [f"{(index - 1) // 12:04d}-{(index - 1) % 12 + 1:02d}"
                      for index in range(first, last + 1)
                      if f"{(index - 1) // 12:04d}-{(index - 1) % 12 + 1:02d}" not in months]
    excluded = [{"category": name, "parent_category": parents[name],
                 "observed_sex_month_cells": len(availability[name]),
                 "reason": "service_food_scope_excludes_pubs" if parents[name] in EXCLUDED_PARENTS
                 else "incomplete_sex_month_panel"}
                for name in sorted(parents) if name not in categories]
    source = {"dataset_id": SOURCE_ID, "url": SOURCE_URL,
              "source_sha256": hashlib.sha256(snapshot).hexdigest(), "encoding": "cp949",
              "raw_rows": raw_rows, "observed_months": len(months),
              "raw_subcategories": len(parents), "model_subcategories": len(categories),
              "model_parent_categories": len(parent_names), "missing_months": missing_months,
              "missing_months_imputed": 0, "missing_cells_imputed": 0,
              "used_source_rows": len(categories) * len(months) * 2,
              "excluded_categories": excluded,
              "universe_definition": "retrospective_complete_sex_month_panel_for_food_snack_categories",
              "universe_availability_scope": "all_observed_months_only_availability_not_error_or_values",
              "group_scope": "male_female_aggregated_no_residency_or_region_field"}
    return panels, categories, parents, parent_indices, source


def _features(month, harmonics):
    angle = 2 * math.pi * month / 12
    return [1.0] + [value for k in range(1, harmonics + 1)
                    for value in (math.sin(k * angle), math.cos(k * angle))]


def _solve(matrix, target):
    size = len(target)
    augmented = [list(row) + [value] for row, value in zip(matrix, target)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-14:
            raise ValueError("외식 모델 학습 행렬이 특이합니다.")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        for j in range(column, size + 1):
            augmented[column][j] /= divisor
        for row in range(column + 1, size):
            factor = augmented[row][column]
            for j in range(column, size + 1):
                augmented[row][j] -= factor * augmented[column][j]
    result = [0.0] * size
    for row in range(size - 1, -1, -1):
        result[row] = augmented[row][size] - sum(augmented[row][j] * result[j] for j in range(row + 1, size))
    return result


def _normalize(values):
    positive = [max(1e-12, value) for value in values]
    total = sum(positive)
    return [value / total for value in positive]


def _fit(panels, config, parent_indices, family):
    end = max(_month_index(row["month"]) for row in panels)
    rows = [row for row in panels if not config["window"] or _month_index(row["month"]) > end - config["window"]]
    size = 1 + 2 * config["harmonics"]
    category_count = len(rows[0]["shares"])
    parent_names = sorted(parent_indices)
    target_count = category_count if family == "direct" else len(parent_names) + category_count
    gram = [[0.0] * size for _ in range(size)]
    targets = [[0.0] * size for _ in range(target_count)]
    for row in rows:
        x = _features(row["calendar_month"], config["harmonics"])
        weight = 2 ** (-(end - _month_index(row["month"])) / config["half_life"]) if config["half_life"] else 1.0
        values = row["shares"]
        if family == "hierarchical":
            parent_shares = [sum(values[i] for i in parent_indices[parent]) for parent in parent_names]
            conditional = [0.0] * category_count
            for parent, share in zip(parent_names, parent_shares):
                for i in parent_indices[parent]:
                    conditional[i] = values[i] / share
            values = parent_shares + conditional
        for j in range(size):
            for k in range(size):
                gram[j][k] += weight * x[j] * x[k]
            for target, value in zip(targets, values):
                target[j] += weight * x[j] * value
    for j in range(size):
        gram[j][j] += config["alpha"] if j else 1e-10
    return {"family": family, "config": dict(config), "parent_names": parent_names,
            "parent_indices": parent_indices, "coefficients": [_solve(gram, target) for target in targets],
            "fit_months": len(rows), "fit_start": rows[0]["month"], "fit_end": rows[-1]["month"]}


def _predict(fitted, month):
    x = _features(month, fitted["config"]["harmonics"])
    values = [sum(coefficient * value for coefficient, value in zip(weights, x))
              for weights in fitted["coefficients"]]
    if fitted["family"] == "direct":
        return _normalize(values)
    parent_count = len(fitted["parent_names"])
    parent_predictions = _normalize(values[:parent_count])
    conditional = values[parent_count:]
    result = [0.0] * len(conditional)
    for parent, share in zip(fitted["parent_names"], parent_predictions):
        indices = fitted["parent_indices"][parent]
        for i, child_share in zip(indices, _normalize([conditional[i] for i in indices])):
            result[i] = share * child_share
    return result


def _mean(panels):
    return [sum(row["shares"][i] for row in panels) / len(panels) for i in range(len(panels[0]["shares"]))]


def _measure(panels, predict, categories, parent_indices):
    absolute = []
    by_category = {name: [] for name in categories}
    by_parent = {name: [] for name in parent_indices}
    predictions = []
    top10 = []
    top10_indices = set(sorted(range(len(categories)),
                               key=lambda i: sum(row["shares"][i] for row in panels), reverse=True)[:10])
    for row in panels:
        estimate = predict(row["calendar_month"])
        predictions.append(estimate)
        errors = [abs(actual - predicted) for actual, predicted in zip(row["shares"], estimate)]
        absolute.extend(errors)
        top10.extend(error for i, error in enumerate(errors) if i in top10_indices)
        for name, error in zip(categories, errors):
            by_category[name].append(error)
        for name, indices in parent_indices.items():
            by_parent[name].append(abs(sum(row["shares"][i] for i in indices) - sum(estimate[i] for i in indices)))
    n = len(absolute)
    ordered = sorted(absolute)
    tolerances = {}
    for threshold in (0.25, 0.5, 1.0):
        numerator = sum(error * 100 <= threshold + 1e-10 for error in absolute)
        tolerances[str(threshold)] = {"threshold_percentage_points": threshold, "within": numerator,
                                     "total": n, "percent": round(100 * numerator / n, 6)}
    return {"mae_percentage_points": round(100 * sum(absolute) / n, 6),
            "rmse_percentage_points": round(100 * math.sqrt(sum(error ** 2 for error in absolute) / n), 6),
            "composition_wape_percent": round(100 * sum(absolute) / len(panels), 6),
            "composition_wape_definition": "100 * sum(abs(actual_share - predicted_share)) / sum(actual_share)",
            "category_observations": n, "observed_months": len(panels),
            "p90_absolute_error_percentage_points": round(100 * ordered[math.ceil(n * .9) - 1], 6),
            "max_absolute_error_percentage_points": round(100 * ordered[-1], 6),
            "top10_observed_share_categories_mae_percentage_points": round(100 * sum(top10) / len(top10), 6),
            "within_tolerance": tolerances,
            "by_category": {name: {"mae_percentage_points": round(100 * sum(errors) / len(errors), 6),
                                   "observations": len(errors)} for name, errors in by_category.items()},
            "by_parent": {name: {"mae_percentage_points": round(100 * sum(errors) / len(errors), 6),
                                 "observations": len(errors)} for name, errors in by_parent.items()}}


def _candidate_configs():
    for window in (0, 12, 24, 36):
        for half_life in (0, 6, 12, 24):
            for harmonics in (0, 1, 2):
                for alpha in (1.0, 10.0, 100.0):
                    yield {"window": window, "half_life": half_life, "harmonics": harmonics, "alpha": alpha}


def train_dining(csv_path, output_dir):
    panels, categories, parents, parent_indices, source = read_panels(csv_path)
    train = [row for row in panels if row["month"] <= "2021-12"]
    validation = [row for row in panels if "2022-01" <= row["month"] <= "2022-12"]
    test = [row for row in panels if row["month"] >= "2023-01"]
    if len(train) != 36 or len(validation) != 12 or len(test) < 12:
        raise ValueError("1047 학습/검증/평가 기간이 고정 프로토콜과 다릅니다.")
    baseline = _mean(train)
    baseline_val = _measure(validation, lambda month: baseline, categories, parent_indices)
    candidates = []
    best = None
    for family in ("direct", "hierarchical"):
        for config in _candidate_configs():
            fitted = _fit(train, config, parent_indices, family)
            errors = [abs(actual - predicted) for row in validation
                      for actual, predicted in zip(row["shares"], _predict(fitted, row["calendar_month"]))]
            loss = sum(errors) / len(errors)
            key = (loss, config["harmonics"], family, config["window"], config["half_life"], config["alpha"])
            candidates.append({"family": family, "config": config, "validation_mae_percentage_points": round(100 * loss, 8)})
            if best is None or key < best[0]:
                best = (key, fitted)
    chosen = best[1]
    validation_model = _measure(validation, lambda month: _predict(chosen, month), categories, parent_indices)
    use_model = validation_model["mae_percentage_points"] < baseline_val["mae_percentage_points"]
    family = chosen["family"] if use_model else "mean"
    config = chosen["config"]
    freeze = {"selected_family": family, "config": config,
              "validation_metric": "category_share_mae_percentage_points", "candidate_count": len(candidates),
              "test_used_for_selection": False, "selection_source": "2019-2021 fit and 2022 validation only"}
    freeze["selection_sha256"] = _hash(freeze)
    # The selection is fixed above. Every comparator is refit on the same first 48 months.
    test_fit = train + validation
    test_fitted = _fit(test_fit, config, parent_indices, chosen["family"])
    test_mean = _mean(test_fit)
    test_model = _measure(test, lambda month: _predict(test_fitted, month) if use_model else test_mean, categories, parent_indices)
    test_baseline = _measure(test, lambda month: test_mean, categories, parent_indices)
    recent_config = dict(config, harmonics=0)
    recent_fit = _fit(test_fit, recent_config, parent_indices, "direct")
    recent_test = _measure(test, lambda month: _predict(recent_fit, month), categories, parent_indices)
    split = {"train_start": train[0]["month"], "train_end": train[-1]["month"], "train_months": len(train),
             "validation_start": validation[0]["month"], "validation_end": validation[-1]["month"], "validation_months": len(validation),
             "test_start": test[0]["month"], "test_end": test[-1]["month"], "test_months": len(test),
             "validation_fit_scope": "training_partition_only",
             "test_fit_scope": "training_plus_validation_for_all_comparators",
             "serving_fit_scope": "all_observed_months_after_evaluation",
             "evaluation_design": "retrospective_complete_panel_temporal_holdout_no_live_user_accuracy"}
    metrics = {"schema_version": 1, "algorithm": ALGORITHM, "source": source,
               "observation_period": {"start": panels[0]["month"], "end": panels[-1]["month"]},
               "scope": "observed_card_transaction_share_food_snack_common_panel",
               "categories": categories, "parents": parents, "split": split, "selection": freeze,
               "candidate_families": ["direct_seasonal_ridge", "hierarchical_seasonal_ridge"],
               "validation": {"model": validation_model, "same_fit_mean": baseline_val},
               "test": {"model": test_model, "same_fit_mean": test_baseline, "same_config_recent_mean": recent_test},
               "improvement_vs_same_fit_mean_percent": round(100 * (1 - test_model["mae_percentage_points"] / test_baseline["mae_percentage_points"]), 6),
               "candidates": candidates}
    serving_fit = _fit(panels, config, parent_indices, chosen["family"])
    if not use_model:
        serving_fit = {"family": "mean", "shares": _mean(panels), "config": config,
                       "fit_months": len(panels), "fit_start": panels[0]["month"], "fit_end": panels[-1]["month"]}
    reference_end = _month_index(panels[-1]["month"])
    historical_rows = [row for row in panels if _month_index(row["month"]) > reference_end - 12]
    historical = []
    for i, name in enumerate(categories):
        count = sum(row["counts"][i] for row in historical_rows)
        amount = sum(row["amounts"][i] for row in historical_rows)
        historical.append({"category": name, "parent_category": parents[name], "observed_transaction_count": count,
                           "observed_transaction_amount_krw": amount,
                           "historical_amount_per_transaction_krw": round(amount / count) if count else None,
                           "reference_period": {"start": historical_rows[0]["month"], "end": historical_rows[-1]["month"],
                                                "observed_months": len(historical_rows)}})
    summary = {key: test_model[key] for key in ("mae_percentage_points", "rmse_percentage_points", "composition_wape_percent",
               "category_observations", "observed_months", "within_tolerance", "max_absolute_error_percentage_points",
               "top10_observed_share_categories_mae_percentage_points")}
    summary["baseline_mae_percentage_points"] = test_baseline["mae_percentage_points"]
    summary["same_config_recent_mean_mae_percentage_points"] = recent_test["mae_percentage_points"]
    summary["improvement_vs_same_config_recent_mean_percent"] = round(100 * (1 - test_model["mae_percentage_points"] / recent_test["mae_percentage_points"]), 6)
    summary["improvement_vs_same_fit_mean_percent"] = metrics["improvement_vs_same_fit_mean_percent"]
    summary["evaluation_period"] = {"start": test[0]["month"], "end": test[-1]["month"]}
    summary["evaluation_scope"] = split["evaluation_design"]
    model = {"schema_version": 1, "algorithm": ALGORITHM, "selected_serving_model": family + "_seasonal_ridge" if use_model else "observed_mean",
             "source": source, "observation_period": metrics["observation_period"], "categories": categories,
             "category_parents": {name: parents[name] for name in categories}, "fitted": serving_fit,
             "historical": historical, "metrics": summary, "selection": freeze,
             "category_test_metrics": test_model["by_category"],
             "serving_fit_scope": "all_observed_months_after_evaluation"}
    model["model_sha256"] = _hash(model)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "dining_model.json").write_text(json.dumps(model, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "dining_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return metrics


def _positive_integer(value, name, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{name} 값은 정수여야 합니다.")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} 값은 정수여야 합니다.") from None
    if isinstance(value, float) and value != number:
        raise ValueError(f"{name} 값은 정수여야 합니다.")
    if isinstance(value, str) and value.strip() != str(number):
        raise ValueError(f"{name} 값은 정수여야 합니다.")
    if number < 1 or number > maximum:
        raise ValueError(f"{name} 값은 1부터 {maximum}까지 가능합니다.")
    return number


@lru_cache(maxsize=4)
def _load_model(model_path, model_mtime, model_size, source_path, source_mtime, source_size):
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    if not isinstance(model, dict) or model.get("schema_version") != 1:
        raise ValueError("외식 모델 형식을 확인해야 합니다.")
    receipt = model.pop("model_sha256", None)
    if not isinstance(receipt, str) or receipt != _hash(model):
        raise ValueError("외식 모델 무결성이 일치하지 않습니다.")
    model["model_sha256"] = receipt
    if model.get("algorithm") != ALGORITHM or model.get("source", {}).get("dataset_id") != SOURCE_ID:
        raise ValueError("외식 모델 알고리즘 또는 출처가 일치하지 않습니다.")
    if model["source"].get("source_sha256") != hashlib.sha256(Path(source_path).read_bytes()).hexdigest():
        raise ValueError("외식 원자료와 모델 출처 해시가 일치하지 않습니다.")
    categories = model.get("categories")
    if not isinstance(categories, list) or len(categories) < 2 or len(set(categories)) != len(categories):
        raise ValueError("외식 모델 업종 목록이 올바르지 않습니다.")
    if any(not isinstance(name, str) or not name or model.get("category_parents", {}).get(name) in EXCLUDED_PARENTS for name in categories):
        raise ValueError("외식 모델 업종 범위가 올바르지 않습니다.")
    fitted = model.get("fitted", {})
    family = fitted.get("family")
    if family not in {"direct", "hierarchical", "mean"}:
        raise ValueError("외식 모델 종류가 올바르지 않습니다.")
    config = fitted.get("config", {})
    if config not in list(_candidate_configs()):
        raise ValueError("외식 모델 설정이 올바르지 않습니다.")
    if family == "mean":
        matrix = [fitted.get("shares", [])]
        expected_rows, expected_columns = 1, len(categories)
    else:
        matrix = fitted.get("coefficients", [])
        names = fitted.get("parent_names", [])
        mapping = fitted.get("parent_indices", {})
        expected_names = sorted(set(model["category_parents"].values()))
        expected_mapping = {name: [i for i, category in enumerate(categories) if model["category_parents"][category] == name] for name in expected_names}
        if names != expected_names or mapping != expected_mapping:
            raise ValueError("외식 모델 계층 연결이 올바르지 않습니다.")
        expected_rows = len(categories) + (len(names) if family == "hierarchical" else 0)
        expected_columns = 1 + 2 * config["harmonics"]
    if not isinstance(matrix, list) or len(matrix) != expected_rows or any(not isinstance(row, list) or len(row) != expected_columns for row in matrix):
        raise ValueError("외식 모델 계수 크기가 올바르지 않습니다.")
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for row in matrix for value in row):
        raise ValueError("외식 모델 계수는 유한한 숫자여야 합니다.")
    historical = model.get("historical")
    if not isinstance(historical, list) or [row.get("category") for row in historical] != categories:
        raise ValueError("외식 모델 관측 참고자료가 올바르지 않습니다.")
    return model


def predict_dining(root, *, month=6, category=None, limit=12):
    """Return monthly aggregate food-class composition and dated observed spend."""
    month = _positive_integer(month, "월", 12)
    limit = _positive_integer(limit, "표시 개수", 100)
    if category is not None and (not isinstance(category, str) or len(category) > 100):
        raise ValueError("외식 업종 검색어는 100자 이하 문자열이어야 합니다.")
    query = (category or "").strip()
    base = Path(root)
    path, source_path = base / MODEL_RELATIVE, base / SOURCE_RELATIVE
    info, source_info = path.stat(), source_path.stat()
    model = _load_model(str(path.resolve()), info.st_mtime_ns, info.st_size,
                        str(source_path.resolve()), source_info.st_mtime_ns, source_info.st_size)
    fitted = model["fitted"]
    predictions = fitted["shares"] if fitted["family"] == "mean" else _predict(fitted, month)
    items = []
    for name, prediction, observed in zip(model["categories"], predictions, model["historical"]):
        parent = model["category_parents"][name]
        if query and query not in name and query not in parent:
            continue
        items.append({**observed, "predicted_share_percent": round(100 * prediction, 6),
                      "test_mae_percentage_points": model["category_test_metrics"][name]["mae_percentage_points"],
                      "prediction_unit": "percent_of_94_complete_observed_food_classes" if len(predictions) == 94 else "percent_of_complete_observed_food_classes"})
    items.sort(key=lambda row: (-row["predicted_share_percent"], row["category"]))
    total_matches = len(items)
    selected_share = sum(row["predicted_share_percent"] for row in items)
    return {"status": "historical_pattern", "month": month,
            "scope": "1047 관측 카드 이용건수의 외식 세부업종 구성비",
            "scope_detail": {"learned_categories": len(model["categories"]),
                             "sexes": "남성·여성 합계", "region_available": False, "resident_tourist_available": False,
                             "share_denominator": "모델에 포함된 완전 관측 외식·간식 업종 전체",
                             "amount_is_observed_not_predicted": True},
            "model": {"algorithm": model["algorithm"], "selected_serving_model": model["selected_serving_model"],
                      "runtime_llm": False, "serving_fit_scope": model["serving_fit_scope"],
                      "selection_sha256": model["selection"]["selection_sha256"]},
            "source": {"dataset_id": SOURCE_ID, "name": "업종별 성별 외식업 이용 정보",
                       "url": SOURCE_URL, "provider": "제주빅데이터센터", "distribution": "제주데이터허브",
                       "source_sha256": model["source"]["source_sha256"],
                       "observed_months": model["source"]["observed_months"],
                       "missing_months": model["source"]["missing_months"], "missing_months_imputed": 0},
            "observation_period": model["observation_period"], "metrics": model["metrics"],
            "category_filter": query or None, "total_matches": total_matches,
            "filtered_share_percent": round(selected_share, 6), "returned_count": min(limit, total_matches),
            "items": items[:limit],
            "limitations": ["2019~2024년 관측에 기반한 월별 통계 패턴이며 현재 매장 인기도나 개인 선호가 아닙니다.",
                            "남녀 자료를 합산했으며 지역·도민·관광객을 구분하는 필드는 없습니다.",
                            "완전 관측 업종만 비교하고 누락 월을 0으로 채우지 않았습니다. 간이·유흥주점은 분석 대상에서 제외했습니다.",
                            "결제 건당 금액은 최근 12개월 관측 이용금액÷이용건수이며 1인 식사 가격이나 현재 메뉴 가격이 아닙니다.",
                            "업종 필터를 적용해도 구성비의 분모는 전체 학습 대상 업종으로 유지됩니다.",
                            "허용오차 내 비율은 과거 관측 구성비와의 비교이며 추천 정확도나 실제 이용자 만족도가 아닙니다."]}
