"""Build the v20 public evaluation ledger from the frozen experiment receipts."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


def read(root, path):
    return json.loads((root / path).read_text(encoding="utf-8"))


def digest(value):
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def metric(name, count, total, percent):
    if not (type(count) is int and type(total) is int and 0 <= count <= total and total > 0):
        raise ValueError(f"Invalid metric counts: {name}, {count}/{total}")
    if abs(100 * count / total - percent) > 1e-4:
        raise ValueError(f"Metric disagrees with counts: {name}")
    return {"name": name, "hits": count, "total": total, "percent": percent}


def composition_metric(name, result):
    score = result["within_tolerance"]
    return metric(name, score["hits"], score["total"], score["percent"])


def bus_metric(name, result):
    score = result["within_20_percent"]
    return metric(name, score["hits"], score["denominator"], score["percent"])


def retrieval_metric(result):
    return metric("첫 결과 적합·미지원 빈 응답", result["successes"], result["cases"], result["success_percent"])


def classification_metric(name, result):
    return metric(name, result["correct"], result["cases"], result["accuracy_percent"])


def experiment(model, candidate, count, family_count, *, comparator=None, config=None, reason):
    return {
        "id": model["id"],
        "title": model["title"],
        "candidate_count": count,
        "family_count": family_count,
        "candidate_metric_percent": candidate["percent"] if candidate else None,
        "candidate_metric": candidate,
        "comparator_metric": comparator,
        "selected_config": config,
        "promoted": model["promoted"],
        "decision_reason": reason,
    }


def base_row(row, **fields):
    return {
        "id": row["id"],
        "title": row["title"],
        "type": row["type"],
        "field_accuracy_proven": False,
        **fields,
    }


def build(root, date_kst):
    previous = read(root, "docs/UI가독성_v19/모델평가현황.json")["models"]
    protocol = read(root, "development_support/change_v20/release_protocol.json")
    by_id = {row["id"]: row for row in previous}
    compositions = read(root, "models_candidates_v20/composition/summary.json")["results"]
    models, experiments = {}, {}
    for result in compositions:
        source = result["dataset_id"]
        old = by_id[{"1048": "audience_distribution", "1047": "dining_detail"}[source]]
        tol = protocol["regression_targets"][source]["tolerance_percentage_points"]
        name = f"±{tol:g}퍼센트포인트 이내"
        candidate, incumbent = result["test"]["selected"], result["test"]["incumbent_same_fit"]
        for sample in (candidate, incumbent):
            if sample["within_tolerance"]["threshold_percentage_points"] != tol:
                raise ValueError(f"{source}: tolerance differs from release protocol")
        promoted = result["deployment_gate_pass"]
        active = candidate if promoted else incumbent
        row = base_row(
            old, source_id=source, fixed_tolerance=tol, promoted=promoted,
            metric=composition_metric(name, active),
            error={"mae": active["mae_percentage_points"], "unit": "퍼센트포인트"},
            test_period=result["test_period"],
            evaluation_scope="이전 보고에 사용한 고정 기간의 실제 월별 구성비 관측값을 같은 적합 범위로 비교",
        )
        models[row["id"]] = row
        comparison = experiment(
            row, composition_metric(name, candidate), result["candidate_count"], result["family_count"],
            comparator=composition_metric(name, incumbent), config=result["selection"]["selected_config"],
            reason="고정 시험에서 기존 모델보다 허용오차 내 비율이 낮고 평균 절대오차가 컸습니다.",
        )
        comparison["candidate_error"] = {"mae": candidate["mae_percentage_points"], "unit": "퍼센트포인트"}
        comparison["incumbent_error"] = {"mae": incumbent["mae_percentage_points"], "unit": "퍼센트포인트"}
        comparison["validation_metric"] = composition_metric(name, result["selection"]["validation"])
        experiments[row["id"]] = comparison

    for source, ident in (("512", "mobility_pattern"), ("561", "route_demand")):
        old = by_id[ident]
        result = read(root, f"models_candidates_v20/bus/{source}/experiment_report.json")
        split = result["protocol"]["split"]
        tol = protocol["regression_targets"][source]["relative_tolerance_percent"]
        name = f"관측 인원 ±{tol:g}% 이내"
        candidate, incumbent = result["test"], result["incumbent_test"]
        for sample in (candidate, incumbent):
            if sample["within_20_percent"]["denominator"] != split["test_count"]:
                raise ValueError(f"{source}: unexpected bus test cohort")
        promoted = result["release_gate"]["promotable"]
        active = candidate if promoted else incumbent
        unit = "명/시간" if source == "512" else "명/통계코드·일"
        cohort = {"evaluated_cells": split["test_count"], "source_cells": split["test_all_source_cells"]}
        scope = "이전 보고에 사용한 고정 기간의 실제 일별·시간대별 승차 관측값"
        if source == "561":
            cohort["evaluation_codes"] = len(split["evaluation_groups"])
            cohort["serving_codes"] = len(split["serving_groups"])
            cohort["cell_coverage_percent"] = 100 * cohort["evaluated_cells"] / cohort["source_cells"]
            if cohort["evaluation_codes"] != protocol["regression_targets"][source]["evaluation_codes_fixed_to_incumbent"]:
                raise ValueError("561: test code cohort changed")
            scope = "이전 보고에 사용한 고정 기간의 250개 통계 코드. 전체 시험 관측 중 43.68%를 평가"
        row = base_row(
            old, source_id=source, fixed_tolerance=tol, promoted=promoted,
            metric=bus_metric(name, active),
            error={"mae": active["mae"], "rmse": active["rmse"], "wape_percent": active["wape_percent"], "unit": unit},
            test_period={"start": split["test_start"], "end": split["test_end"]},
            cohort=cohort, evaluation_scope=scope,
        )
        if promoted:
            row["artifact_sha256"] = result["artifact_sha256"]
            row["algorithm"] = "recency_weighted_route_weekday_median_v20"
            row["half_life_days"] = result["selected_config"]["half_life"]
        models[ident] = row
        comparison = experiment(
            row, bus_metric(name, candidate), result["protocol"]["candidate_count"],
            len({item["config"]["family"] for item in result["validation_candidates"]}),
            comparator=bus_metric(name, incumbent), config=result["selected_config"],
            reason=("허용오차 내 비율이 높아졌고 평균 절대오차 증가가 사전 허용한 2% 범위 안입니다."
                    if promoted else "허용오차 내 비율은 높아졌으나 평균 절대오차가 2%를 초과해 증가했습니다."),
        )
        comparison["candidate_error"] = {"mae": candidate["mae"], "unit": unit}
        comparison["incumbent_error"] = {"mae": incumbent["mae"], "unit": unit}
        experiments[ident] = comparison

    retrieval = "models_candidates_v20/retrieval"
    reports = read(root, f"{retrieval}/retrieval_metrics.json")["domains"]
    decisions = read(root, f"{retrieval}/promotion.json")
    selection = read(root, f"{retrieval}/selection.json")["production_domains"]
    dev = read(root, "development_support/retrieval_v20/validation_production_rerank.json")
    overlap = read(root, "development_support/retrieval_v20/quality_audit.json")["entity_overlap"]["food"]["dev_test_relevant_id_overlap"]
    search_rows = {
        "tourism": ("tourism_tfidf", "검색어가 있고 명시 위치가 없는 첫 페이지의 5개 이상 결과 요청에서 기존 상위 5개만 재정렬"),
        "guide": ("assistant_guide_tfidf", "출처를 확인한 도우미 가이드 검색의 작성 질의 시험"),
        "food": ("food_tfidf", f"검증·시험 정답 ID {overlap}개가 겹치고 비교기의 그룹 순서·범위가 운영과 달라 별도 탐색 결과로 기록"),
        "travel": ("travel_context_tfidf", "해변·접근성·걷기·편의시설 기록 검색의 작성 질의 시험"),
    }
    for domain, (ident, scope) in search_rows.items():
        report = reports[domain]
        promoted = decisions["domains"][domain]["activate"]
        incumbent = retrieval_metric(report["incumbent_service"])
        candidate = retrieval_metric(report["production_constrained_rerank"])
        row = base_row(
            by_id[ident], promoted=promoted,
            metric=None if domain == "food" else (candidate if promoted else incumbent),
            evaluation_scope=scope,
        )
        models[ident] = row
        comparison = experiment(
            row, None if domain == "food" else candidate, len(dev[domain]),
            len({item["config"]["family"] for item in dev[domain]}),
            comparator=None if domain == "food" else incumbent,
            config=selection[domain]["selected_config"],
            reason={
                "tourism": "같은 후보 집합에서 첫 결과가 개선됐습니다.",
                "guide": "같은 후보 집합에서 개선 폭이 0입니다.",
                "food": scope,
                "travel": "같은 후보 집합에서 개선 폭이 0입니다.",
            }[domain],
        )
        if domain == "food":
            comparison["exploratory_candidate_metric"] = candidate
            comparison["exploratory_comparator_metric"] = incumbent
        comparison["full_index_prototype_metric"] = retrieval_metric(report["selected"])
        experiments[ident] = comparison

    intent = read(root, f"{retrieval}/intent_metrics.json")
    intent_dev = read(root, f"{retrieval}/intent_selection.json")
    candidate = classification_metric("작성 문장 분류기 정답률", intent["selected_test"])
    incumbent = classification_metric("기존 나이브 베이즈 분류기 정답률", intent["incumbent_nb_test"])
    parser = classification_metric("규칙을 포함한 기존 전체 파서 정답률", intent["incumbent_full_parser_test"])
    row = base_row(
        by_id["assistant_intent"], promoted=decisions["intent_activate"], metric=parser,
        evaluation_scope="6개 요청 종류의 작성 문장 60건. 분류 모델과 입력 조건을 해석하는 규칙의 합산 결과",
        classifier_only_metric=incumbent,
    )
    models[row["id"]] = row
    experiments[row["id"]] = experiment(
        row, candidate, len(intent_dev["candidates"]), len({item["family"] for item in intent_dev["candidates"]}),
        comparator=incumbent, config=intent_dev["selected"],
        reason="같은 문장의 분류기 단독 비교에서 기존 나이브 베이즈의 정답 수가 더 많았습니다.",
    )

    route = experiments["route_demand"]
    hit_gain = route["candidate_metric"]["percent"] - route["comparator_metric"]["percent"]
    mae_gain = 100 * (route["candidate_error"]["mae"] / route["incumbent_error"]["mae"] - 1)
    ledger = {
        "schema_version": 1,
        "service_version": protocol["service_version"],
        "date_kst": date_kst,
        "target_percent": protocol["requested_target_percent"],
        "all_service_models_93_proven": False,
        "goal_note": (
            f"네 예측 모델 모두 고정한 허용오차에서 93% 목표에 미달했습니다. "
            f"561은 허용오차 내 비율이 {hit_gain:.2f}퍼센트포인트 높아졌고 "
            f"평균 절대오차는 {mae_gain:.2f}% 증가했습니다."
        ),
        "notes": [
            "평균 절대오차는 실제값과 예측값 차이의 크기를 평균한 값입니다. 회귀 비율은 표의 허용오차 안에 든 관측의 비율입니다.",
            "검색 성공에는 정답이 첫 결과인 질의와 미지원 질의에 결과가 비어 있는 경우가 포함됩니다. 작성 질의와 문장으로 평가했습니다.",
            "561은 평가 250개 통계 코드와 운영 202개 코드의 범위가 다릅니다. 현재 운행 노선·좌석 정보는 별도로 확인해야 합니다.",
        ],
        "models": [models[old["id"]] for old in previous],
        "experiments": [experiments[old["id"]] for old in previous],
    }
    ledger["snapshot_sha256"] = digest(ledger)
    return ledger


def score(metric):
    return f'{metric["percent"]:.2f}% ({metric["hits"]:,}/{metric["total"]:,})'


def write_report(root, ledger):
    models = ledger["models"]
    experiments = {item["id"]: item for item in ledger["experiments"]}
    lines = [
        "# 제주 길벗 v20 모델 조합 비교", "",
        f'{ledger["date_kst"]}. 예측 모델 4종의 고정 시험에서 93% 목표를 달성한 모델은 없습니다. '
        "561 통계 노선코드 승차와 관광 검색에 검증을 통과한 구성을 적용했습니다.", "",
        "## 실제 관측값을 맞히는 예측 모델", "",
        "| 자료 | 비교한 조합 | 고정 기준 | 기존 비율 | 선정 후보 비율 | 기존 → 후보 MAE | 적용 결과 |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for model in (row for row in models if row["type"] == "regression"):
        item = experiments[model["id"]]
        incumbent = item["incumbent_error"]
        candidate = item["candidate_error"]
        lines.append(
            f'| {model["source_id"]} {model["title"]} | {item["candidate_count"]}개 / {item["family_count"]}계열 '
            f'| {model["metric"]["name"]} | {score(item["comparator_metric"])} | {score(item["candidate_metric"])} '
            f'| {incumbent["mae"]:.6f} → {candidate["mae"]:.6f} {candidate["unit"]} '
            f'| {"후보 적용" if model["promoted"] else "기존 모델"} |'
        )
    route = experiments["route_demand"]
    hit_gain = route["candidate_metric"]["percent"] - route["comparator_metric"]["percent"]
    mae_gain = 100 * (route["candidate_error"]["mae"] / route["incumbent_error"]["mae"] - 1)
    count_gain = route["candidate_metric"]["hits"] - route["comparator_metric"]["hits"]
    dining_validation = experiments["dining_detail"]["validation_metric"]["percent"]
    dining_test = experiments["dining_detail"]["candidate_metric"]["percent"]
    lines += [
        "",
        "MAE는 관측값과 예측값 사이의 절대 차이를 평균한 값입니다. 구성비가 31%이고 관측값이 30%면 오차는 1퍼센트포인트입니다. "
        "승차 ±20% 기준은 실제 100명이면 80명에서 120명까지의 예측을 허용합니다.", "",
        f"561은 최근 관측에 더 큰 비중을 주는 요일별 중앙값을 적용했습니다. "
        f"동일한 28,092건에서 허용오차를 충족한 예측이 {count_gain:,}건, {hit_gain:.2f}퍼센트포인트 늘었습니다. "
        f"평균 절대오차는 {mae_gain:.3f}% 증가해 사전 허용 범위 2% 안에 들었습니다. "
        "전체 시험 관측 64,315건 중 43.68%에 해당하는 250개 통계 코드가 평가 대상입니다. "
        "서비스에서는 최근 관측이 충분한 202개 코드의 과거 패턴을 제공합니다.", "",
        "소비·외식은 최근 창과 가중치, Ridge·Elastic Net·커널 회귀, 랜덤 포레스트·부스팅, "
        "소형 신경망, 계층 모형과 고정 앙상블을 비교했습니다. 승차는 요일별 요약, 달력 회귀, "
        "계절 커널, 계층 평활, 트리 계열과 앙상블을 비교했습니다. 기존과 같은 관측값과 허용오차를 쓰고 "
        "시험 기간 이전의 3개 소비 검증 구간 또는 2개 승차 검증 구간에서 후보를 골랐습니다. "
        "시험은 선정 후보 하나와 같은 학습 범위의 기존 모델을 비교하는 데 썼습니다. "
        "기존 보고서의 시험 기간을 다시 사용한 후향평가입니다.", "",
        f"1047 후보는 검증 {dining_validation:.2f}%에서 고정 시험 {dining_test:.2f}%로 낮아졌습니다. "
        "소비 초기 참고 Ridge는 가중치 정규화 방식이 운영 Ridge와 달랐습니다. 비교값을 실제 운영 모듈의 "
        "동일 범위 재적합 결과로 교정했고, 이미 고정한 후보는 같은 후보로 시험했습니다. 교정 전후 기록을 모두 보존했습니다.", "",
        "## 검색과 요청 처리", "",
        "| 평가 대상 | 비교한 조합 | 기존 → 선정 후보 | 적용 결정 |",
        "|---|---:|---|---|",
    ]
    for model in (row for row in models if row["type"] != "regression"):
        item = experiments[model["id"]]
        candidate, comparator = item["candidate_metric"], item["comparator_metric"]
        if candidate:
            numbers = f"{score(comparator)} → {score(candidate)}"
        else:
            numbers = "운영 범위와 동일한 시험 필요"
        lines.append(f'| {model["title"]} | {item["candidate_count"]}개 | {numbers} | {item["decision_reason"]} |')
    tourism = experiments["tourism_tfidf"]
    food = experiments["food_tfidf"]
    parser = next(row["metric"] for row in models if row["id"] == "assistant_intent")
    lines += [
        "",
        "검색 수치는 출처 기록에 근거해 작성한 질의 시험입니다. 정답이 첫 결과로 나오거나 지원 범위 밖 질의에 "
        "결과가 비어 있으면 성공입니다. BM25, 문자·단어 TF-IDF, 필드 가중치와 순위 결합을 비교했습니다. "
        f'관광 전체 색인 실험에서는 {score(tourism["full_index_prototype_metric"])}가 나왔으나 '
        "적용 범위는 검색어가 있고 명시 위치가 없는 첫 페이지에서 5개 이상 결과를 요청할 때의 기존 상위 5개 재정렬입니다. "
        "결과 집합과 출처·지역·신뢰 정책을 보존하며 적합한 첫 결과를 더 자주 보여줍니다.", "",
        f'음식 전체 색인의 탐색 결과는 {score(food["full_index_prototype_metric"])}입니다. '
        "검증·시험 정답 기록 132개가 겹치고, 비교기의 후보 묶음 순서가 화면과 다릅니다. "
        "도우미는 제주데이터허브 780으로 출처를 제한하므로 실제 음식 검색을 평가하려면 그 범위를 따로 재현해야 합니다.", "",
        f"요청 분류의 표는 나이브 베이즈·로지스틱 회귀·선형 SVM의 분류기 단독 비교입니다. "
        f"전처리와 해석 규칙을 포함한 기존 전체 파서는 같은 작성 문장에서 {score(parser)}입니다. "
        "작성 질의·문장과 실제 이용자의 요청에는 차이가 있어 이 결과로 현장 정확도를 추정할 수 없습니다.", "",
        "## 자료 확인과 재현", "",
        "2026년 11월 4일 제주데이터허브에서 1048·1047·512 파일을 다시 받아 보관본과 SHA-256이 같은 것을 확인했습니다. "
        "561은 파일 식별자와 제공 기간이 같은 것을 확인하고 기존 약 498MB 보관본을 사용했습니다. "
        "512 파일의 마지막 관측일 2025년 10월 26일을 시험 종료일로 사용했습니다.", "",
        "- 출처 [1048 소비](https://www.jejudatahub.net/data/view/data/1048), "
        "[1047 외식](https://www.jejudatahub.net/data/view/data/1047), "
        "[512 전체 승차](https://www.jejudatahub.net/data/view/data/512), "
        "[561 노선코드 승차](https://www.jejudatahub.net/data/view/data/561).",
        "- 동결 기준과 출처 확인 기록은 `development_support/change_v20/`에 있습니다. "
        "모델별 설정과 검증·시험 결과는 `models_candidates_v20/`의 JSON을 확인할 수 있습니다.",
        "- 상세 실험 [소비·외식](소비외식_실험보고.md), [승차](승차_실험보고.md).",
        "- 실험 진입점은 `scripts/experiment_composition_v20.py`, `scripts/experiment_bus_v20.py`, "
        "`scripts/evaluate_retrieval_v20.py`입니다. 재실험은 결과 JSON을 쓰므로 평가 사본에서 실행합니다. "
        "운영 추론과 아래 요약 생성에는 추가 학습 패키지가 필요하지 않습니다.",
        "- 시간순 검증 방법 [scikit-learn 시계열 예제](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html), "
        "[TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit).", "",
        "```powershell",
        ".\\runtime\\python.exe .\\development_support\\change_v20\\build_portfolio.py",
        "```", "",
        "다음 고정 시험은 새로 수집한 기간을 먼저 분리하고, 노선코드별 승차의 최근 관측과 "
        "이용자가 실제로 입력하는 질의를 추가한 뒤 진행할 수 있습니다. 기존 시험을 재사용해 93%를 맞추면 "
        "새 관측에서도 같은 성능이 나오는지 판단할 수 없습니다.", "",
    ]
    path = root / "docs/모델다양화_v20/전체실험_결과보고.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--date-kst", default="2026-11-06")
    args = parser.parse_args()
    root = args.root.resolve()
    ledger = build(root, args.date_kst)
    path = root / "data_reference/model_portfolio_v20.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_report(root, ledger)
    sys.stdout.reconfigure(encoding="utf-8")
    print(f'{len(ledger["models"])} models / {len(ledger["experiments"])} experiments / {ledger["snapshot_sha256"]}')


if __name__ == "__main__":
    main()
