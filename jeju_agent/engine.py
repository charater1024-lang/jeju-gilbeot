"""A fitted demand model and constraint-aware itinerary search using only stdlib.

The learned target is daily visit count, not food quality or individual preference.
Preference weights and the routing algorithm are explicitly separate from ML.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any


POI_COLUMNS = {"poi_id", "name", "category", "region", "latitude", "longitude", "tags", "indoor", "stay_minutes", "cost_krw", "open_minute", "close_minute", "source_id"}
DEMAND_COLUMNS = {"date", "poi_id", "visits", "source_id"}
ALGORITHM = "ridge_regression_log1p_daily_visits"


def _data_fingerprints(data_dir: Path) -> dict[str, str]:
    return {name: hashlib.sha256((Path(data_dir) / name).read_bytes()).hexdigest() for name in ("pois.csv", "demand.csv")}


def _validate_model(model: Any) -> None:
    if not isinstance(model, dict) or model.get("algorithm") != ALGORITHM or model.get("schema_version") != 1:
        raise ValueError("지원하지 않는 모델 파일입니다. 다시 학습하세요.")
    ids, weights = model.get("poi_ids"), model.get("weights")
    if not isinstance(ids, list) or not ids or any(not isinstance(ident, str) or not ident for ident in ids) or len(ids) != len(set(ids)):
        raise ValueError("모델의 POI 식별자 목록이 올바르지 않습니다. 다시 학습하세요.")
    if not isinstance(weights, list) or len(weights) != len(ids) + 6:
        raise ValueError("모델의 계수 차원이 특성 정의와 일치하지 않습니다. 다시 학습하세요.")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in weights):
        raise ValueError("모델 계수는 모두 유한한 숫자여야 합니다. 다시 학습하세요.")
    origin, trained = _date(model.get("origin", "")), _date(model.get("trained_through", ""))
    if origin > trained:
        raise ValueError("모델 학습 날짜 범위가 올바르지 않습니다. 다시 학습하세요.")
    fingerprints = model.get("data_sha256")
    if not isinstance(fingerprints, dict) or set(fingerprints) != {"pois.csv", "demand.csv"} or any(not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value) for value in fingerprints.values()):
        raise ValueError("모델에 검증 가능한 데이터 SHA256이 없습니다. 다시 학습하세요.")


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


def _number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field}: 숫자를 입력하세요.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: 숫자를 입력하세요.") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{field}: {minimum} 이상 {maximum} 이하의 유한한 값이어야 합니다.")
    return result


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    result = _number(value, field, minimum, maximum)
    if result != int(result):
        raise ValueError(f"{field}: 정수여야 합니다.")
    return int(result)


def _read_csv(path: Path, columns: set[str]) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = columns - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: 필수 열 누락 {', '.join(sorted(missing))}")
        return list(reader)


def load_data(data_dir: Path) -> tuple[list[dict], list[dict], str]:
    data_dir = Path(data_dir)
    pois = _read_csv(data_dir / "pois.csv", POI_COLUMNS)
    if not pois:
        raise ValueError("POI 데이터가 없습니다.")
    ids: set[str] = set()
    for poi in pois:
        if not poi["poi_id"] or poi["poi_id"] in ids:
            raise ValueError("POI 식별자는 비어 있지 않고 중복이 없어야 합니다.")
        ids.add(poi["poi_id"])
        poi["latitude"] = _number(poi["latitude"], "latitude", -90, 90)
        poi["longitude"] = _number(poi["longitude"], "longitude", -180, 180)
        for field, low, high in [("stay_minutes", 1, 1440), ("cost_krw", 0, 10000000), ("open_minute", 0, 1439), ("close_minute", 1, 1440)]:
            poi[field] = _integer(poi[field], field, low, high)
        if poi["open_minute"] >= poi["close_minute"]:
            raise ValueError("영업 시간은 같은 날짜 내에서 개점 < 폐점이어야 합니다.")
        if not poi["source_id"]:
            raise ValueError("모든 POI에 source_id가 필요합니다.")
        poi["tags"] = [v.strip() for v in poi["tags"].replace(",", "|").split("|") if v.strip()]
        poi["indoor"] = str(poi["indoor"]).lower() in {"1", "true", "yes"}
    demand = _read_csv(data_dir / "demand.csv", DEMAND_COLUMNS)
    keys: set[tuple] = set()
    for row in demand:
        day = _date(row["date"])
        if row["poi_id"] not in ids:
            raise ValueError(f"수요 행에 미등록 POI가 있습니다: {row['poi_id']}")
        key = (day, row["poi_id"])
        if key in keys:
            raise ValueError("수요 데이터의 날짜와 POI 조합이 중복되었습니다.")
        keys.add(key)
        row["visits"] = _number(row["visits"], "visits", 0, 100000000)
        if not row["source_id"]:
            raise ValueError("모든 수요 행에 source_id가 필요합니다.")
    mode = "unverified"
    metadata_path = data_dir / "demo_metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("synthetic") is True:
            mode = "synthetic"
    return pois, sorted(demand, key=lambda row: (row["date"], row["poi_id"])), mode


def _features(day: dt.date, poi_id: str, poi_ids: list[str], origin: dt.date) -> list[float]:
    weekday = day.weekday() * 2 * math.pi / 7
    annual = (day.timetuple().tm_yday - 1) * 2 * math.pi / 365.25
    return [1.0] + [float(poi_id == ident) for ident in poi_ids] + [math.sin(weekday), math.cos(weekday), math.sin(annual), math.cos(annual), (day - origin).days / 365.25]


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for the small ridge system."""
    size = len(vector)
    augmented = [list(row) + [target] for row, target in zip(matrix, vector)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("모델 학습 행렬이 특이합니다. 더 많은 데이터를 확인하세요.")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        divisor = augmented[col][col]
        for j in range(col, size + 1):
            augmented[col][j] /= divisor
        for row in range(col + 1, size):
            factor = augmented[row][col]
            for j in range(col, size + 1):
                augmented[row][j] -= factor * augmented[col][j]
    weights = [0.0] * size
    for row in range(size - 1, -1, -1):
        weights[row] = augmented[row][size] - sum(augmented[row][j] * weights[j] for j in range(row + 1, size))
    return weights


def _fit(rows: list[dict], poi_ids: list[str], origin: dt.date, alpha: float = 1.0) -> list[float]:
    size = len(poi_ids) + 6
    gram = [[0.0] * size for _ in range(size)]
    target = [0.0] * size
    for row in rows:
        values = _features(_date(row["date"]), row["poi_id"], poi_ids, origin)
        y = math.log1p(row["visits"])
        active = [(i, value) for i, value in enumerate(values) if value]
        for i, value in active:
            target[i] += value * y
            for j, other in active:
                gram[i][j] += value * other
    for i in range(size):
        gram[i][i] += alpha if i else 1e-8
    return _solve(gram, target)


def _predict_log(model: dict, day: dt.date, poi_id: str) -> float:
    values = _features(day, poi_id, model["poi_ids"], _date(model["origin"]))
    # Clipping guards far-out extrapolation; it is disclosed in model metadata.
    return min(18.0, max(0.0, sum(weight * value for weight, value in zip(model["weights"], values))))


def _mae(actual: list[float], predicted: list[float]) -> dict:
    return {
        "mae_log1p": round(sum(abs(math.log1p(a) - p) for a, p in zip(actual, predicted)) / len(actual), 6),
        "mae_visits": round(sum(abs(a - math.expm1(p)) for a, p in zip(actual, predicted)) / len(actual), 3),
        "n": len(actual),
    }


def train(data_dir: Path, output_dir: Path) -> dict:
    """Temporal evaluation first; final model is refitted on all supplied history."""
    pois, demand, mode = load_data(Path(data_dir))
    dates = sorted({row["date"] for row in demand})
    if len(dates) < 14:
        raise ValueError("날짜 기준 최소 14일의 수요 이력이 필요합니다.")
    split = max(7, int(len(dates) * 0.8))
    train_dates, test_dates = dates[:split], dates[split:]
    train_rows = [row for row in demand if row["date"] <= train_dates[-1]]
    test_rows = [row for row in demand if row["date"] >= test_dates[0]]
    if not train_rows or not test_rows:
        raise ValueError("시간 분할 학습 또는 검증 행이 없습니다.")
    # Category vocabulary comes from the training partition, never holdout labels.
    train_ids = sorted({row["poi_id"] for row in train_rows})
    origin = _date(train_dates[0])
    validation_model = {"poi_ids": train_ids, "origin": origin.isoformat(), "weights": _fit(train_rows, train_ids, origin)}
    actual = [row["visits"] for row in test_rows]
    learned = [_predict_log(validation_model, _date(row["date"]), row["poi_id"]) for row in test_rows]
    global_mean = sum(math.log1p(row["visits"]) for row in train_rows) / len(train_rows)
    means: dict[str, list[float]] = {}
    for row in train_rows:
        means.setdefault(row["poi_id"], []).append(math.log1p(row["visits"]))
    poi_means = {ident: sum(values) / len(values) for ident, values in means.items()}
    metrics = {
        "data_mode": mode,
        "warning": "합성 데이터 검증 수치이며 실제 제주 데이터 성능을 의미하지 않습니다." if mode == "synthetic" else "제공 데이터에 대한 시간 분할 결과입니다. 출처와 측정 정의를 별도로 검증하세요.",
        "split": {"method": "last_20_percent_dates_holdout", "train_start": train_dates[0], "train_end": train_dates[-1], "validation_start": test_dates[0], "validation_end": test_dates[-1], "train_rows": len(train_rows), "validation_rows": len(test_rows), "fit_preprocessing_on_train_only": True},
        "model": _mae(actual, learned),
        "baseline_global_mean": _mae(actual, [global_mean] * len(actual)),
        "baseline_poi_mean": _mae(actual, [poi_means.get(row["poi_id"], global_mean) for row in test_rows]),
        "limitations": ["일별 방문량 예측 평가이며 개인별 추천 정확도 평가가 아닙니다.", "요일과 연중 주기의 외삽 성능은 데이터 기간에 따라 달라집니다.", "가격과 영업시간 및 도로 소요시간의 정확성은 별도 검증이 필요합니다."],
    }
    final_ids = sorted({row["poi_id"] for row in demand})
    model = {"schema_version": 1, "algorithm": ALGORITHM, "data_mode": mode, "target": "log1p_daily_visits", "origin": dates[0], "trained_through": dates[-1], "training_rows": len(demand), "poi_ids": final_ids, "weights": _fit(demand, final_ids, _date(dates[0])), "ridge_alpha": 1.0, "feature_order": ["intercept"] + [f"poi:{ident}" for ident in final_ids] + ["weekday_sin", "weekday_cos", "annual_sin", "annual_cos", "trend_years"], "prediction_log_clip": [0, 18], "source_ids": sorted({row["source_id"] for row in demand}), "poi_source_ids": sorted({row["source_id"] for row in pois}), "data_sha256": _data_fingerprints(Path(data_dir))}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _travel(a: tuple[float, float], b: tuple[float, float], mode: str) -> tuple[int, int, float]:
    distance = _distance_km(a, b) * (1.35 if mode == "car" else 1.2)
    minutes = math.ceil(distance / (35 if mode == "car" else 4) * 60)
    cost = math.ceil(distance * 250) if mode == "car" else 0
    return minutes, cost, distance


def _validate_request(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("요청은 JSON 객체여야 합니다.")
    result = dict(request)
    result["date"] = _date(request.get("date", "")).isoformat()
    mode = request.get("transport", "car")
    if mode not in {"car", "walk", "bus"}:
        raise ValueError("교통수단은 car, walk, bus 중 하나여야 합니다.")
    result["transport"] = mode
    for field, default, low, high in [("start_lat", 33.507, -90, 90), ("start_lon", 126.493, -180, 180), ("end_lat", request.get("start_lat", 33.507), -90, 90), ("end_lon", request.get("start_lon", 126.493), -180, 180)]:
        result[field] = _number(request.get(field, default), field, low, high)
    for field, default, low, high in [("start_minute", 540, 0, 1439), ("end_minute", 1080, 1, 1440), ("budget_krw", 100000, 0, 10000000), ("max_stops", 5, 1, 8)]:
        result[field] = _integer(request.get(field, default), field, low, high)
    if result["start_minute"] >= result["end_minute"]:
        raise ValueError("시작 시각은 종료 시각보다 빨라야 합니다.")
    interests = request.get("interests", [])
    if not isinstance(interests, list) or any(not isinstance(v, str) for v in interests) or len(interests) > 30:
        raise ValueError("interests는 문자열 목록이어야 합니다. 최대 30개입니다.")
    result["interests"] = interests
    crowd = request.get("avoid_crowds", False)
    if not isinstance(crowd, bool):
        raise ValueError("avoid_crowds는 true 또는 false여야 합니다.")
    result["avoid_crowds"] = crowd
    return result


def recommend(data_dir: Path, model_path: Path, request: dict) -> dict:
    trace: list[dict] = []

    def stage(agent: str, started: float, detail: str, status: str = "completed") -> None:
        trace.append({"agent": agent, "status": status, "duration_ms": round((time.perf_counter() - started) * 1000, 3), "detail": detail})

    started = time.perf_counter()
    req = _validate_request(request)
    stage("요청 해석 Agent", started, "여행 날짜·교통·예산·시간·선호를 구조화하고 검증했습니다.")
    started = time.perf_counter()
    pois, demand, data_mode = load_data(Path(data_dir))
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    _validate_model(model)
    forecast_day = _date(req["date"])
    trained_through = _date(model["trained_through"])
    if demand and max(_date(row["date"]) for row in demand) > trained_through:
        raise ValueError("현재 수요 데이터가 모델 학습 종료일 이후까지 갱신되었습니다. 다시 학습하세요.")
    if _data_fingerprints(Path(data_dir)) != model["data_sha256"]:
        raise ValueError("POI 또는 수요 데이터의 SHA256이 학습 데이터와 다릅니다. 출처와 예측의 일치를 위해 다시 학습하세요.")
    if forecast_day <= trained_through:
        raise ValueError(f"미래 정보 누출 방지를 위해 {trained_through.isoformat()} 이후 날짜를 선택하세요.")
    stage("데이터 검증 Agent", started, f"POI {len(pois)}개와 수요 {len(demand)}행을 검증했습니다. 데이터 모드: {data_mode}.")
    warnings = ["인기도는 일별 방문량 예측이며 맛·위생·현재 혼잡도를 뜻하지 않습니다.", "개인별 동선 데이터가 없으므로 실제 사람들이 연속 방문한 경로로 해석할 수 없습니다.", "영업시간과 가격은 제공 데이터 값이며 당일 영업 여부를 보장하지 않습니다."]
    if data_mode == "synthetic":
        warnings.insert(0, "모든 장소·방문량·가격은 기능 검증용 합성 데이터입니다. 실제 맛집 또는 실측 인기도 추천이 아닙니다.")
    else:
        warnings.insert(0, "데이터 출처와 관측 단위 검증이 완료되지 않았습니다. 실측 인기도 또는 실제 식당별 방문량으로 표시할 수 없습니다.")
    if data_mode != model.get("data_mode"):
        raise ValueError("현재 데이터 모드와 모델 학습 데이터 모드가 다릅니다. 다시 학습하세요.")
    if (forecast_day - trained_through).days > 30:
        warnings.append("학습 기간에서 30일 이상 떨어진 예측입니다. 계절 외삽의 불확실성이 큽니다.")
    response = {"status": "ok", "data_mode": data_mode, "message": "일별 수요 예측과 제약 검색으로 구성한 추천 경로입니다.", "request": req, "stops": [], "totals": {}, "warnings": warnings, "trace": trace, "model": {"algorithm": model["algorithm"], "trained_through": model["trained_through"], "forecast_date": req["date"], "forecast_scope": "daily_total_not_realtime_crowding"}}
    started = time.perf_counter()
    source_by_poi: dict[str, set[str]] = {}
    for row in demand:
        source_by_poi.setdefault(row["poi_id"], set()).add(row["source_id"])
    predictions = {poi["poi_id"]: _predict_log(model, forecast_day, poi["poi_id"]) for poi in pois}
    cold = [poi["poi_id"] for poi in pois if poi["poi_id"] not in model["poi_ids"]]
    if cold:
        warnings.append(f"학습 이력이 없는 장소 {len(cold)}개는 공통 계절·요일 계수로 예측했습니다. 개별 장소 인기도 근거가 약합니다.")
    lo, hi = min(predictions.values()), max(predictions.values())
    stage("수요 예측 Agent", started, f"학습된 Ridge 계수로 {req['date']}의 일별 방문량을 예측했습니다.")
    started = time.perf_counter()
    interests = {tag.casefold() for tag in req["interests"]}
    candidates = []
    for poi in pois:
        pred = predictions[poi["poi_id"]]
        popularity = (pred - lo) / (hi - lo) if hi > lo else 0.5
        learned_score = 1 - popularity if req["avoid_crowds"] else popularity
        matches = len(interests & {tag.casefold() for tag in poi["tags"] + [poi["category"]]})
        preference = min(1.0, matches / max(1, min(2, len(interests)))) if interests else 0.5
        candidate = dict(poi)
        candidate.update(predicted_visits=round(math.expm1(pred), 1), learned_score=round(learned_score, 4), preference_score=round(preference, 4), score=round(0.55 * learned_score + 0.45 * preference, 4), demand_source_ids=sorted(source_by_poi.get(poi["poi_id"], set())), cold_start=poi["poi_id"] in cold)
        candidates.append(candidate)
    candidates.sort(key=lambda p: (-p["score"], p["poi_id"]))
    candidates = candidates[:40]
    stage("후보 추천 Agent", started, "학습된 수요 점수와 사용자가 선택한 태그 일치도를 별도로 계산했습니다.")
    started = time.perf_counter()
    if req["transport"] == "bus":
        response.update(status="unsupported", message="버스 시간표·운행일·환승·막차 데이터가 연결되지 않아 실행 가능한 버스 경로를 생성할 수 없습니다.")
        stage("경로 최적화 Agent", started, "버스 운영 데이터가 없어 경로 생성을 중단했습니다.", "unsupported")
        started = time.perf_counter()
        stage("근거 설명 Agent", started, "누락된 데이터와 대체 입력 필요성을 안내했습니다.")
        return response
    mode = req["transport"]
    start = (req["start_lat"], req["start_lon"])
    end = (req["end_lat"], req["end_lon"])
    warnings.append("이동 시간은 직선거리 보정 추정입니다. 도로망·통행 제한·실시간 교통·보행 가능 여부는 반영하지 않습니다.")
    if mode == "car":
        warnings.append("차량 이동비는 보정거리 km당 250원 추정입니다. 렌터카·보험·주차·통행료는 미포함이며 별도 예산이 필요합니다.")
    # State: current location, clock, visit cost, travel cost, travel mins,
    # selected stops, utility, visited identifiers, covered categories.
    initial = (start, req["start_minute"], 0, 0, 0, [], 0.0, frozenset(), frozenset())
    beam = [initial]
    best = None
    best_value = -1.0
    explored = 0
    for depth in range(req["max_stops"]):
        expanded = []
        for location, clock, visit_cost, travel_cost, travel_mins, stops, utility, used, categories in beam:
            for poi in candidates:
                if poi["poi_id"] in used:
                    continue
                point = (poi["latitude"], poi["longitude"])
                leg_minutes, leg_cost, leg_km = _travel(location, point, mode)
                arrival = max(clock + leg_minutes, poi["open_minute"])
                departure = arrival + poi["stay_minutes"]
                back_minutes, back_cost, _ = _travel(point, end, mode)
                new_visit_cost = visit_cost + poi["cost_krw"]
                new_travel_cost = travel_cost + leg_cost
                if departure > poi["close_minute"] or departure + back_minutes > req["end_minute"] or new_visit_cost + new_travel_cost + back_cost > req["budget_krw"]:
                    continue
                explored += 1
                diversity_bonus = 0.08 if poi["category"] not in categories else 0.0
                new_utility = utility + poi["score"] + diversity_bonus - 0.001 * leg_minutes
                stop = {k: poi[k] for k in ["poi_id", "name", "category", "latitude", "longitude", "stay_minutes", "cost_krw", "source_id", "predicted_visits", "learned_score", "preference_score", "score", "demand_source_ids", "cold_start"]}
                stop.update(arrival_minute=arrival, departure_minute=departure, travel_minutes=leg_minutes, travel_cost_krw=leg_cost, travel_km=round(leg_km, 2), waiting_minutes=arrival - clock - leg_minutes)
                new_stops = stops + [stop]
                state = (point, departure, new_visit_cost, new_travel_cost, travel_mins + leg_minutes, new_stops, new_utility, used | {poi["poi_id"]}, categories | {poi["category"]})
                expanded.append(state)
                # An incumbent is always feasible including its final return leg.
                value = new_utility - 0.001 * back_minutes
                if value > best_value:
                    best_value, best = value, state
        expanded.sort(key=lambda state: (-state[6], state[1], state[2] + state[3], tuple(stop["poi_id"] for stop in state[5])))
        beam = expanded[:60]
        if not beam:
            break
    if best is None:
        response.update(status="infeasible", message="입력한 시간·예산·출발/도착지 안에서 방문 가능한 후보가 없습니다. 시간이나 예산을 늘리거나 범위를 좁혀주세요.")
    else:
        point, clock, visit_cost, travel_cost, travel_mins, stops, utility, _, _ = best
        back_minutes, back_cost, back_km = _travel(point, end, mode)
        response["stops"] = stops
        response["totals"] = {"duration_minutes": clock + back_minutes - req["start_minute"], "end_arrival_minute": clock + back_minutes, "travel_minutes": travel_mins + back_minutes, "visit_cost_krw": visit_cost, "travel_cost_krw": travel_cost + back_cost, "cost_krw": visit_cost + travel_cost + back_cost, "return_travel_minutes": back_minutes, "return_travel_cost_krw": back_cost, "return_travel_km": round(back_km, 2), "stops": len(stops)}
    stage("경로 최적화 Agent", started, f"빔 검색으로 {explored}개 가능 확장을 평가하고 복귀 구간·시간·예산·영업시간을 검증했습니다. 전역 최적은 보장하지 않습니다.")
    started = time.perf_counter()
    stage("근거 설명 Agent", started, "각 추천에 예측 방문량·선호 점수·데이터 출처와 추정 한계를 연결했습니다.")
    return response
