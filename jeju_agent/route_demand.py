"""CPU-only calendar ML for historical source-561 statistical route labels.

Only observed regular-ticket boarding cells are learned. A source bus_number is
not silently mapped to a present-day public bus route. No missing count is zero.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SOURCE_ID = "561"
SOURCE_URL = "https://www.jejudatahub.net/data/view/data/561"
SCHEMA_VERSION = 1
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
LIMITATIONS = [
    "자료의 bus_number는 통계 노선 코드이며 현재 운행 노선·정류소·시간표와의 연결은 검증하지 않았습니다.",
    "일반 승차권의 일별 승차 집계입니다. 다른 승차권·하차·환승은 제외합니다.",
    "미래 날짜는 과거 관측에서 학습한 달력 조건별 참고값입니다. 실시간 혼잡·만차·좌석·운행 여부를 뜻하지 않습니다.",
    "원자료에 없는 날짜·노선 셀을 0으로 보충하지 않았습니다.",
    "같은 사람이 여러 번 승차할 수 있으므로 고유 관광객 수나 관광지 방문 인원으로 해석하지 않습니다.",
]


def _day(value: Any) -> dt.date:
    if not isinstance(value, str):
        raise ValueError("날짜는 YYYY-MM-DD 문자열로 입력하세요.")
    try:
        result = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("올바른 YYYY-MM-DD 날짜가 필요합니다.") from exc
    if result.year < 1900 or result.year > 2200:
        raise ValueError("날짜 범위를 확인하세요.")
    return result


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def read_observations(path: Path) -> tuple[list[dict], dict]:
    """Stream the actual raw file, reject duplicate/invalid statistical cells."""
    rows, last_date, seen = [], "", set()
    dates, groups, codes = set(), Counter(), set()
    raw_count, excluded_labels = 0, Counter()
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or []) != {"base_date", "act_type", "bus_number", "user_type", "user_count"}:
            raise ValueError("561 원자료 필수 열과 일치하지 않습니다.")
        for number, row in enumerate(reader, 2):
            raw_count += 1
            raw_day = row["base_date"]
            if not re.fullmatch(r"\d{8}", raw_day):
                raise ValueError(f"{number}행의 날짜 형식이 올바르지 않습니다.")
            day = f"{raw_day[:4]}-{raw_day[4:6]}-{raw_day[6:]}"
            _day(day)
            if day < last_date:
                raise ValueError("561 원자료가 날짜순이 아닙니다. 중복 검사를 위해 정렬 상태를 확인하세요.")
            if day != last_date:
                seen, last_date = set(), day
            route, act, ticket = row["bus_number"].strip(), row["act_type"].strip(), row["user_type"].strip()
            key = (act, route, ticket)
            if key in seen:
                raise ValueError(f"중복 통계 셀입니다: {day}, {route}, {act}, {ticket}")
            seen.add(key)
            if not route or not act or not ticket:
                raise ValueError(f"{number}행의 통계 구분이 비어 있습니다.")
            count_text = row["user_count"].strip()
            if not re.fullmatch(r"\d+", count_text):
                raise ValueError(f"{number}행의 이용자 수는 0 이상의 정수여야 합니다.")
            count = int(count_text)
            if count > 1_000_000_000:
                raise ValueError(f"{number}행의 이용자 수 범위를 확인하세요.")
            dates.add(day)
            groups[f"{act}|{ticket}"] += 1
            if act == "승차" and ticket == "일반":
                # A strict source-label format excludes virtual/unknown labels.
                if not re.fullmatch(r"\d{1,4}(?:-\d{1,3})?", route):
                    excluded_labels[route] += 1
                    continue
                codes.add(route)
                rows.append({"date": day, "route_id": route, "count": count})
    if not rows:
        raise ValueError("학습할 실제 일반 승차 관측이 없습니다.")
    period = sorted(dates)
    expected = (_day(period[-1]) - _day(period[0])).days + 1
    return rows, {
        "source_id": SOURCE_ID, "sha256": _hash(Path(path)), "raw_rows": raw_count,
        "raw_observed_dates": len(dates), "raw_missing_dates": expected - len(dates),
        "raw_period": {"start": period[0], "end": period[-1]}, "group_row_counts": dict(groups),
        "selected_ticket": "일반", "selected_action": "승차", "selected_cells": len(rows),
        "source_route_labels": len(codes), "missing_cells_imputed": 0,
        "excluded_nonstandard_label_cells": sum(excluded_labels.values()),
        "excluded_nonstandard_labels": dict(excluded_labels),
        "route_identity": "exact_source_bus_number_unmapped_to_current_routes",
    }


def _features(day: dt.date) -> list[float]:
    phase = 2 * math.pi * ((day.month - 1) + (day.day - 1) / 31) / 12
    weekend = float(day.weekday() >= 5)
    return [1.0] + [float(day.weekday() == i) for i in range(1, 7)] + [
        math.sin(phase), math.cos(phase), math.sin(2 * phase), math.cos(2 * phase),
        weekend * math.sin(phase), weekend * math.cos(phase),
    ]


def _solve(matrix: list[list[float]], target: list[float]) -> list[float]:
    size = len(target)
    data = [list(row) + [y] for row, y in zip(matrix, target)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda index: abs(data[index][col]))
        if abs(data[pivot][col]) < 1e-12:
            raise ValueError("학습 행렬을 계산할 수 없습니다.")
        data[col], data[pivot] = data[pivot], data[col]
        divisor = data[col][col]
        for j in range(col, size + 1):
            data[col][j] /= divisor
        for i in range(col + 1, size):
            factor = data[i][col]
            for j in range(col, size + 1):
                data[i][j] -= factor * data[col][j]
    result = [0.0] * size
    for i in range(size - 1, -1, -1):
        result[i] = data[i][size] - sum(data[i][j] * result[j] for j in range(i + 1, size))
    return result


def _eligible(rows: list[dict], end: dt.date) -> list[str]:
    recent_start, tail_start = end - dt.timedelta(days=179), end - dt.timedelta(days=27)
    recent, tail, total = Counter(), Counter(), Counter()
    for row in rows:
        day = _day(row["date"])
        if recent_start <= day <= end:
            recent[row["route_id"]] += 1
            total[row["route_id"]] += row["count"]
        if tail_start <= day <= end:
            tail[row["route_id"]] += 1
    return sorted(route for route, count in recent.items() if count >= 162 and tail[route] >= 24 and total[route] / count >= 5)


def _window(rows: list[dict], end: dt.date, routes: list[str]) -> list[dict]:
    start, selected = (end - dt.timedelta(days=729)).isoformat(), set(routes)
    return [row for row in rows if start <= row["date"] <= end.isoformat() and row["route_id"] in selected]


def fit(rows: list[dict], config: dict) -> dict:
    if not rows:
        raise ValueError("학습 관측이 없습니다.")
    end = max(row["date"] for row in rows)
    end_day = _day(end)
    half_life = config.get("half_life_days")
    grouped = defaultdict(list)
    features = {}
    for row in rows:
        grouped[row["route_id"]].append(row)
        if row["date"] not in features:
            day = _day(row["date"])
            features[row["date"]] = (day.weekday(), _features(day), 1.0 if half_life is None else 2 ** (-(end_day - day).days / half_life))
    fitted = {}
    for route, observed in grouped.items():
        weighted_count, total_weight = 0.0, 0.0
        sums, counts = [0.0] * 7, [0.0] * 7
        for row in observed:
            weekday, _, weight = features[row["date"]]
            weighted_count += weight * row["count"]
            total_weight += weight
            sums[weekday] += weight * row["count"]
            counts[weekday] += weight
        scale = max(1.0, weighted_count / total_weight)
        model = {"mean": scale, "last_date": max(row["date"] for row in observed), "observations": len(observed), "weekday_means": [sums[i] / counts[i] if counts[i] else scale for i in range(7)]}
        if config["family"] == "calendar_ridge":
            size = 13
            matrix, target = [[0.0] * size for _ in range(size)], [0.0] * size
            for row in observed:
                _, x, weight = features[row["date"]]
                active = [(i, value) for i, value in enumerate(x) if value and not (config["harmonics"] == 1 and i in (9, 10))]
                y = row["count"] / scale
                for i, value in active:
                    wv = weight * value
                    target[i] += wv * y
                    for j, other in active:
                        matrix[i][j] += wv * other
            for i in range(size):
                matrix[i][i] += config["alpha"] if i else 1e-8
            model["weights"] = _solve(matrix, target)
        fitted[route] = model
    return {"config": dict(config), "fit_end": end, "routes": fitted}


def predict(fitted: dict, route: str, day: dt.date) -> float:
    model = fitted["routes"].get(route)
    if model is None:
        raise ValueError("학습 범위에 없는 통계 노선 코드입니다.")
    if fitted["config"]["family"] == "calendar_ridge":
        result = model["mean"] * sum(a * b for a, b in zip(model["weights"], _features(day)))
    else:
        result = model["weekday_means"][day.weekday()]
    return max(0.0, result)


def _metrics(actual: list[float], predicted: list[float]) -> dict:
    if not actual:
        return {"observations": 0, "mae": None, "rmse": None, "wape_percent": None, "within_20_percent": None}
    errors = [abs(a - b) for a, b in zip(actual, predicted)]
    eligible = [(a, e) for a, e in zip(actual, errors) if a > 0]
    hits = sum(e <= a * 0.20 for a, e in eligible)
    total = sum(actual)
    return {
        "observations": len(actual), "mae": sum(errors) / len(actual),
        "rmse": math.sqrt(sum(e * e for e in errors) / len(actual)),
        "wape_percent": 100 * sum(errors) / total if total > 0 else None,
        "within_20_percent": {"hits": hits, "denominator": len(eligible), "percent": 100 * hits / len(eligible) if eligible else None, "excluded_zero_actual": len(actual) - len(eligible), "definition": "abs(predicted-observed)<=0.20*observed; observed>0"},
        "unit": "일반 승차 인원/통계노선코드·일",
    }


def score(rows: list[dict], fitted: dict, *, slices: bool = False) -> dict:
    predictions = [predict(fitted, row["route_id"], _day(row["date"])) for row in rows]
    result = _metrics([row["count"] for row in rows], predictions)
    if slices:
        groups = defaultdict(lambda: ([], []))
        route_groups = defaultdict(lambda: ([], []))
        for row, pred in zip(rows, predictions):
            label = "주말" if _day(row["date"]).weekday() >= 5 else "평일"
            groups[label][0].append(row["count"])
            groups[label][1].append(pred)
            route_groups[row["route_id"]][0].append(row["count"])
            route_groups[row["route_id"]][1].append(pred)
        result["by_day_type"] = {key: _metrics(*values) for key, values in groups.items()}
        result["by_route"] = {key: _metrics(*values) for key, values in sorted(route_groups.items())}
    return result


def train_route_demand(csv_path: Path, output_dir: Path) -> dict:
    rows, audit = read_observations(csv_path)
    latest = max(row["date"] for row in rows)
    last = _day(latest)
    test_start, validation_start = last - dt.timedelta(days=119), last - dt.timedelta(days=239)
    fit_end = validation_start - dt.timedelta(days=1)
    routes = _eligible(rows, fit_end)
    if len(routes) < 2:
        raise ValueError("학습 기준일에서 최근 관측이 충분한 통계 노선이 두 개 이상 필요합니다.")
    train_rows = _window(rows, fit_end, routes)
    selected_set = set(routes)
    validation_rows = [row for row in rows if validation_start.isoformat() <= row["date"] < test_start.isoformat() and row["route_id"] in selected_set]
    test_rows = [row for row in rows if test_start.isoformat() <= row["date"] <= latest and row["route_id"] in selected_set]
    test_all = [row for row in rows if test_start.isoformat() <= row["date"] <= latest]
    if not validation_rows or not test_rows:
        raise ValueError("검증·테스트 관측이 없습니다.")
    baseline_config = {"family": "weekday_mean", "half_life_days": None}
    baseline = fit(train_rows, baseline_config)
    baseline_validation = score(validation_rows, baseline)
    candidates, fits = [], {}
    configurations = [{"family": "weekday_mean", "half_life_days": half} for half in (60, 180, 365)]
    configurations += [{"family": "calendar_ridge", "half_life_days": half, "alpha": alpha, "harmonics": harmonics} for half in (60, 180, 365) for alpha in (3.0, 30.0) for harmonics in (1, 2)]
    # Selection never reads test targets. Eligibility is fixed at fit_end.
    for index, config in enumerate(configurations):
        model = fit(train_rows, config)
        measured = score(validation_rows, model)
        candidates.append({"id": index, "config": config, "validation": measured})
        fits[index] = model
    chosen = min(candidates, key=lambda item: (item["validation"]["mae"], item["id"]))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    split = {
        "train": {"start": min(row["date"] for row in train_rows), "end": fit_end.isoformat(), "observations": len(train_rows)},
        "validation": {"start": validation_start.isoformat(), "end": (test_start - dt.timedelta(days=1)).isoformat(), "observations": len(validation_rows)},
        "test": {"start": test_start.isoformat(), "end": latest, "observations": len(test_rows)},
        "evaluation_routes": len(routes), "eligibility_as_of": fit_end.isoformat(),
        "eligibility_rule": ">=162 observed days of preceding180, >=24 of preceding28, recent mean>=5; exact source-label format",
        "fit_lookback_days": 730, "test_all_source_observed_cells": len(test_all),
        "test_evaluated_cell_coverage_percent": 100 * len(test_rows) / len(test_all),
        "missing_cells_imputed": 0, "frozen_fit_for_validation_and_test": True,
    }
    freeze = {"source_sha256": audit["sha256"], "selected": chosen["config"], "selection_metric": "validation MAE", "split": split, "test_used_for_selection": False}
    freeze_path = output_dir / "selection_freeze.json"
    freeze_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2), encoding="utf-8")
    selected = fits[chosen["id"]]
    measured_test, baseline_test = score(test_rows, selected, slices=True), score(test_rows, baseline, slices=True)
    serving_routes = _eligible(rows, last)
    serving_rows = _window(rows, last, serving_routes)
    serving = fit(serving_rows, chosen["config"])
    report = {
        "schema_version": SCHEMA_VERSION, "source_id": SOURCE_ID, "data_mode": "observed_real_data",
        "algorithm": "recency_weighted_route_calendar_ridge" if chosen["config"]["family"] == "calendar_ridge" else "recency_weighted_route_weekday_mean",
        "scope": "제주 일반 승차·원자료 통계 노선 코드별 일별 집계", "source": {"dataset_id": SOURCE_ID, "url": SOURCE_URL, "provider": "제주빅데이터센터", "raw_file": "data_raw/hub/hub_561_5842.csv"},
        "audit": audit, "split": split, "selected_config": chosen["config"],
        "selection": {"criterion": "validation MAE", "candidates": candidates, "test_used_for_selection": False, "freeze_sha256": _hash(freeze_path)},
        "validation": {"selected": chosen["validation"], "baseline": baseline_validation},
        "test": {"selected": measured_test, "baseline": baseline_test, "mae_reduction_percent": 100 * (baseline_test["mae"] - measured_test["mae"]) / baseline_test["mae"]},
        "evaluation_note": "처음 고정한 과거 날짜 구간의 후향평가입니다. 현장 이용자 실험이나 현재 버스 혼잡 정확도가 아닙니다.",
        "serving": {"fit_start": min(row["date"] for row in serving_rows), "fit_end": latest, "routes": len(serving_routes), "observations": len(serving_rows), "same_selected_config": True},
        "limitations": LIMITATIONS,
    }
    serving.update({"schema_version": SCHEMA_VERSION, "source_id": SOURCE_ID, "source_sha256": audit["sha256"], "observation_period": audit["raw_period"], "fit_start": min(row["date"] for row in serving_rows), "algorithm": report["algorithm"]})
    (output_dir / "route_demand_model.json").write_text(json.dumps(serving, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (output_dir / "route_demand_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_artifact_integrity(output_dir)
    return report


def write_artifact_integrity(folder: Path) -> None:
    files = ("route_demand_model.json", "route_demand_metrics.json", "selection_freeze.json")
    record = {"schema_version": SCHEMA_VERSION, "source_id": SOURCE_ID,
              "files": {name: _hash(Path(folder) / name) for name in files}}
    (Path(folder) / "artifact_integrity.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def _finite_nonnegative(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _load(root: Path) -> tuple[dict, dict]:
    folder = Path(root) / "models_route_demand"
    try:
        integrity = json.loads((folder / "artifact_integrity.json").read_text(encoding="utf-8"))
        expected_files = {"route_demand_model.json", "route_demand_metrics.json", "selection_freeze.json"}
        if integrity.get("schema_version") != SCHEMA_VERSION or integrity.get("source_id") != SOURCE_ID or set(integrity.get("files", {})) != expected_files:
            raise ValueError("노선 수요 모델 무결성 명세가 올바르지 않습니다.")
        for name, expected in integrity["files"].items():
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or _hash(folder / name) != expected:
                raise ValueError("노선 수요 모델·평가·선정 파일의 무결성이 일치하지 않습니다.")
        model = json.loads((folder / "route_demand_model.json").read_text(encoding="utf-8"))
        metrics = json.loads((folder / "route_demand_metrics.json").read_text(encoding="utf-8"))
        freeze = json.loads((folder / "selection_freeze.json").read_text(encoding="utf-8"))
        if model.get("schema_version") != SCHEMA_VERSION or metrics.get("schema_version") != SCHEMA_VERSION or model.get("source_id") != SOURCE_ID or metrics.get("source_id") != SOURCE_ID:
            raise ValueError("노선 수요 모델의 출처·버전을 확인하세요.")
        if model.get("source_sha256") != metrics.get("audit", {}).get("sha256") or model.get("source_sha256") != freeze.get("source_sha256"):
            raise ValueError("노선 수요 모델의 원자료 해시가 일치하지 않습니다.")
        if metrics.get("selection", {}).get("freeze_sha256") != _hash(folder / "selection_freeze.json") or freeze.get("test_used_for_selection") is not False:
            raise ValueError("노선 수요 모델의 선정 기록이 일치하지 않습니다.")
        if model.get("config") != metrics.get("selected_config") or model.get("config") != freeze.get("selected") or metrics.get("split") != freeze.get("split"):
            raise ValueError("노선 수요 모델의 평가 설정이 일치하지 않습니다.")
        config = model["config"]
        if config.get("family") not in ("weekday_mean", "calendar_ridge"):
            raise ValueError("지원하지 않는 노선 수요 모델입니다.")
        fit_end = _day(model["fit_end"])
        if _day(model["fit_start"]) > fit_end or metrics.get("serving", {}).get("fit_end") != model["fit_end"]:
            raise ValueError("노선 수요 모델 학습 기간이 올바르지 않습니다.")
        if not isinstance(model.get("routes"), dict) or not model["routes"] or len(model["routes"]) != metrics["serving"]["routes"]:
            raise ValueError("노선 수요 모델 코드 목록이 올바르지 않습니다.")
        for route, fitted in model["routes"].items():
            if not re.fullmatch(r"\d{1,4}(?:-\d{1,3})?", route) or not isinstance(fitted, dict):
                raise ValueError("노선 수요 모델 코드 형식이 올바르지 않습니다.")
            if not _finite_nonnegative(fitted.get("mean")) or fitted["mean"] < 1:
                raise ValueError("노선 수요 모델 평균이 유한한 양수가 아닙니다.")
            means = fitted.get("weekday_means")
            if not isinstance(means, list) or len(means) != 7 or not all(_finite_nonnegative(value) for value in means):
                raise ValueError("노선 수요 모델 요일 계수 차원·수치가 올바르지 않습니다.")
            if not isinstance(fitted.get("observations"), int) or isinstance(fitted["observations"], bool) or fitted["observations"] <= 0 or _day(fitted["last_date"]) > fit_end:
                raise ValueError("노선 수요 모델 관측 정보가 올바르지 않습니다.")
            if config["family"] == "calendar_ridge":
                weights = fitted.get("weights")
                if not isinstance(weights, list) or len(weights) != 13 or not all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in weights):
                    raise ValueError("노선 수요 모델 회귀 계수 차원·수치가 올바르지 않습니다.")
        for result in (metrics["test"]["selected"], metrics["test"]["baseline"]):
            if not all(_finite_nonnegative(result.get(key)) for key in ("mae", "rmse", "wape_percent")) or not isinstance(result.get("observations"), int) or result["observations"] <= 0:
                raise ValueError("노선 수요 모델 평가 수치가 올바르지 않습니다.")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("노선 수요 모델 파일·구조를 확인하세요.") from exc
    return model, metrics


def list_route_options(root: Path, limit: int = 1000) -> list[dict]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000:
        raise ValueError("노선 목록 수는 1~2000이어야 합니다.")
    model, _ = _load(root)
    return [{"route_id": key, "label": f"통계 코드 {key}", "history_last_date": value["last_date"]} for key, value in sorted(model["routes"].items())][:limit]


def get_route_demand(root: Path, *, route: str | None = None, date: str | None = None, limit: int = 8) -> dict:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("표시 수는 1~50이어야 합니다.")
    day = _day(date) if date is not None else dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    if route is not None and (not isinstance(route, str) or not re.fullmatch(r"\d{1,4}(?:-\d{1,3})?", route.strip())):
        raise ValueError("원자료의 정확한 통계 노선 코드를 입력하세요. 예: 201-14")
    model, metrics = _load(root)
    if route is not None:
        keys = [route.strip()]
        if keys[0] not in model["routes"]:
            raise ValueError("최근 원자료 관측이 충분하지 않거나 학습 범위에 없는 통계 코드입니다.")
    else:
        keys = sorted(model["routes"], key=lambda key: (-model["routes"][key]["mean"], key))[:limit]
    test = metrics["test"]["selected"]
    items = []
    for key in keys:
        value = model["routes"][key]
        route_test = test.get("by_route", {}).get(key)
        items.append({
            "route_id": key, "label": f"통계 코드 {key}", "prediction": round(predict(model, key, day), 1),
            "unit": "일반 승차 인원/일", "history_last_date": value["last_date"], "fit_observations": value["observations"],
            "test_mae": round(route_test["mae"], 2) if route_test else None,
            "test_observations": route_test["observations"] if route_test else 0,
            "current_route_mapping_verified": False,
        })
    return {
        "status": "ok", "scope": metrics["scope"], "estimate_type": "historical_calendar_pattern", "requested_date": day.isoformat(),
        "weekday": WEEKDAYS[day.weekday()], "algorithm": metrics["algorithm"], "runtime_llm": False,
        "message": f"{model['fit_end']}까지 관측한 자료로 {WEEKDAYS[day.weekday()]}요일의 과거 승차 패턴을 계산했습니다.",
        "pattern_features": ["weekday"] if model["config"]["family"] == "weekday_mean" else ["weekday", "annual_cycle", "weekend_annual_cycle"],
        "source": metrics["source"], "sources": [metrics["source"]], "observation_period": metrics["audit"]["raw_period"],
        "fit_period": {"start": model["fit_start"], "end": model["fit_end"]},
        "metrics": {"mae": test["mae"], "wape_percent": test["wape_percent"], "within_20_percent": test["within_20_percent"], "unit": test["unit"], "evaluation_period": metrics["split"]["test"], "mae_reduction_percent": metrics["test"]["mae_reduction_percent"], "evaluation_note": metrics["evaluation_note"], "evaluation_route_count": metrics["split"]["evaluation_routes"], "serving_route_count": metrics["serving"]["routes"], "evaluated_cell_coverage_percent": metrics["split"]["test_evaluated_cell_coverage_percent"], "all_test_observed_cells": metrics["split"]["test_all_source_observed_cells"]},
        "items": items, "route_options": list_route_options(root), "limitations": LIMITATIONS + [f"평가는 {metrics['split']['evaluation_routes']}개 통계 코드와 전체 테스트 관측의 {metrics['split']['test_evaluated_cell_coverage_percent']:.2f}%에 한정하며, 최신 자료로 적합한 운영 코드는 {metrics['serving']['routes']}개입니다."],
        "default_list_order": "최근 가중 일반 승차 관측 평균 순서이며 현재 추천 순위가 아닙니다.",
    }
