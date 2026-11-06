r"""Repeatable edge audit for the current local search and chat HTTP API.

Start the app first. Run from the project root with:
    .\runtime\python.exe -B tests\http_edge_search.py --base-url http://127.0.0.1:8765
A failed assertion is reported per case, and any failure yields exit status 1.
Only read-only loopback calls and fixed public landmarks are used.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_smoke_v5 import Client


JEJU_AIRPORT = {"latitude": 33.506, "longitude": 126.492, "source": "manual"}
CHEONJIYEON_REFERENCE = {"latitude": 33.2447173, "longitude": 126.5598201, "source": "manual"}


def audit(base_url):
    client = Client(base_url)
    results = []

    def check(name, path, *, body=None, raw=None, origin=None, status=200, valid=None):
        if raw is None and body is not None:
            raw = json.dumps(body).encode("ascii")
        request = Request(client.base + path, data=raw, headers={
            "Accept": "application/json", "Content-Type": "application/json", "Origin": origin or client.base,
        })
        result = {"case": name, "expected_status": status, "passed": False}
        payload = None
        try:
            try:
                with client.opener.open(request, timeout=10) as response:
                    actual, headers, content = response.status, response.headers, response.read()
            except HTTPError as error:
                actual, headers, content = error.code, error.headers, error.read()
            result["status"] = actual
            if "application/json" not in headers.get("Content-Type", ""):
                raise ValueError("response did not use application/json")
            payload = json.loads(content.decode("utf-8"))
            status_matches = actual in status if isinstance(status, tuple) else actual == status
            result["passed"] = status_matches and (valid is None or bool(valid(payload)))
            if not result["passed"]:
                if isinstance(payload, dict):
                    result["observed"] = {key: payload[key] for key in (
                        "error", "intent", "location_used", "needs_location", "reply", "state", "total",
                    ) if key in payload}
                    result["observed"]["cards"] = [item["name"] for item in payload.get("cards", [])]
                else:
                    result["observed"] = [
                        (item.get("name"), item.get("match_type")) for item in payload[:5]
                    ] if isinstance(payload, list) else payload
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            result["error"] = str(error)
        results.append(result)
        return payload if result["passed"] else None

    def chat(name, message, *, status=200, valid=None, **extra):
        return check(name, "/api/chat", body={"message": message, **extra}, status=status, valid=valid)

    def guide(name, query, *, status=200, valid=None):
        return check(name, "/api/guide-search", body={"query": query}, status=status, valid=valid)

    def no_cards(payload):
        return payload["cards"] == [] and payload["location_used"] is False

    def exact_guide(ident):
        return lambda payload: (len(payload) == 1 and payload[0]["id"] == ident
                                and payload[0]["match_type"] == "exact_name"
                                and payload[0]["current_opening_verified"] is False
                                and payload[0]["official_intro"]["date_kind"] == "guide_review")

    for value, ident in (
        ("성산일출봉", "seongsan"), ("성산 일출봉", "seongsan"), ("성산일출봉 공식 소개 알려줘", "seongsan"),
        ("협재해수욕장에 대해 알려 주세요", "hyeopjae"), ("제주 성산일출봉", "seongsan"),
    ):
        guide(f"공식 소개 이름 일치 / {value}", value, valid=exact_guide(ident))
    guide("정상 좌표로 제한된 장소의 소개", "성산일출봉",
          valid=lambda data: not data[0]["automatic_eligible"] and
          "entrance_required" in {reason["code"] for reason in data[0]["visit_restrictions"]})
    for value in ("", "　 ", "🌊✨", "a" * 160, "성산일출봉 운영시간", "용두암 근처",
                  "우도 빼고 바다 풍경", "반려견 출입가능 해변", "성산일출봉과 용두암"):
        guide(f"안내 가능한 출처가 없는 검색 / {value[:25]!r}", value, valid=lambda data: data == [])
    for value in ("a" * 161, None, [], {"text": "용두암"}):
        guide(f"공식 소개 형식 검증 / {type(value).__name__}", value, status=400)

    chat("상담 빈 입력", "　 ", valid=lambda data: no_cards(data) and data["offline"] and not data["llm_used"])
    chat("상담 질문 최대 300자", "x" * 300, valid=no_cards)
    chat("상담 질문 301자", "x" * 301, status=400)
    chat("상담 질문 타입 오류", [], status=400)
    chat("상담 상태 타입 오류", "1번", state=[], status=400)
    named = chat("이름이 확인된 장소 주소", "함덕해수욕장 주소",
                 valid=lambda data: data["cards"][0]["id"] == "hamdeok")
    if named:
        chat("새 이름을 이전 대화 장소로 바꾸지 않음", "서울역 주소 알려줘", state=named["state"],
             valid=no_cards)
        chat("명시한 대화 장소의 주소 후속 질문", "그곳 주소 알려줘", state=named["state"],
             valid=lambda data: data["cards"][0]["id"] == "hamdeok")
    chat("결과 범위 밖 번호", "다섯 번째 장소", valid=lambda data: no_cards(data) and data["intent"] == "clarify_choice")
    chat("명시적으로 제외한 주제", "해변 빼고 박물관 추천",
         valid=lambda data: no_cards(data) and data["intent"] == "clarify_negation")
    chat("다른 표현의 제외 조건", "해변 피하고 박물관 추천",
         valid=lambda data: no_cards(data) or all("해변" not in card["category"] for card in data["cards"]))
    chat("추천 금지", "해변 추천하지 마", valid=no_cards)
    chat("반려견 동반 가능 조건", "반려견과 함께 갈 수 있는 해변 추천", valid=no_cards)
    chat("계단 없는 접근 조건", "계단이 없는 박물관 추천", valid=no_cards)
    chat("복수 지역 선택", "북부 또는 남부 해변 추천",
         valid=lambda data: no_cards(data) or {item["region"] for item in data["cards"]} == {"north", "south"})
    chat("장소의 현재 운영 질문", "성산일출봉 현재 영업해?",
         valid=lambda data: no_cards(data) and data["intent"] == "realtime_unavailable")
    for now in ("현재", "지금"):
        for location in (None, JEJU_AIRPORT):
            chat(f"근처와 현재 영업 조건을 함께 요청 / {now} / 위치={location is not None}",
                 f"내 근처 {now} 영업 중인 카페 추천", location=location,
                 valid=lambda data: no_cards(data) and data["intent"] == "realtime_unavailable")
    chat("위치가 없는 내 주변 요청", "내 근처 카페 추천",
         valid=lambda data: no_cards(data) and data["needs_location"])
    chat("위치 거절이 함께 전송한 위치보다 우선", "내 근처 카페 추천",
         location=JEJU_AIRPORT, location_declined=True,
         valid=lambda data: not data["location_used"] and data["location_status"] == "declined")
    chat("제주 밖 공개 지점", "내 근처 카페 추천",
         location={"latitude": 37.5547, "longitude": 126.9707, "source": "manual"},
         valid=lambda data: no_cards(data) and data["location_status"] == "outside_jeju")
    chat("수동 위치의 요청 한정 사용", "내 근처 카페 추천",
         location={**JEJU_AIRPORT, "accuracy_m": 5001, "label": "TEST_ONLY_PUBLIC_POINT"},
         valid=lambda data: data["location_used"] and data["location_status"] == "low_accuracy"
         and "TEST_ONLY_PUBLIC_POINT" not in json.dumps(data)
         and {"latitude", "longitude", "accuracy_m"}.isdisjoint(data["state"]))
    for message in ("성산일출봉 주변 맛집 추천", "제주공항 근처 카페 추천", "함덕해수욕장 가까운 카페 추천"):
        for location in (None, CHEONJIYEON_REFERENCE):
            chat(f"장소명과 위치 동의 구분 / {message} / 위치={location is not None}", message,
                 location=location, valid=lambda data: not data["location_used"] and not data["needs_location"])

    too_large = 10 ** 400
    for label, endpoint, body in (
        ("상담 위도", "/api/chat", {"message": "가까운 카페", "location": {**JEJU_AIRPORT, "latitude": too_large}}),
        ("상담 정확도", "/api/chat", {"message": "가까운 카페", "location": {**JEJU_AIRPORT, "accuracy_m": too_large}}),
        ("음식 반경", "/api/discover", {"radius_km": too_large}),
        ("음식 위도", "/api/discover", {"location": {**JEJU_AIRPORT, "latitude": too_large}}),
        ("관광 반경", "/api/tourism", {"radius_km": too_large}),
        ("관광 위도", "/api/tourism", {"location": {**JEJU_AIRPORT, "latitude": too_large}}),
        ("관광 지도 범위", "/api/tourism", {"bbox": [126.1, 33.2, too_large, 33.6]}),
    ):
        check(f"부동소수점 변환 한계를 넘는 정수 / {label}", endpoint, body=body, status=400)
    for label, body in (
        ("limit 불리언", {"limit": True}), ("limit 0", {"limit": 0}), ("limit 101", {"limit": 101}),
        ("offset 음수", {"offset": -1}), ("offset 1000001", {"offset": 1000001}),
        ("bbox 좌우 역전", {"bbox": [127, 33, 126, 34]}), ("bbox 폭 0", {"bbox": [126, 33, 126, 34]}),
        ("반경 0.999", {"radius_km": .999}), ("반경 100.001", {"radius_km": 100.001}),
        ("반경 NaN", {"radius_km": float("nan")}), ("위도 문자열", {"location": {**JEJU_AIRPORT, "latitude": "33.5"}}),
        ("미지원 종류", {"kind": "unknown"}), ("잘못된 커서", {"cursor": "*not-base64"}),
        ("커서 301자", {"cursor": "a" * 301}),
    ):
        check(f"관광 지도 검색 범위 검증 / {label}", "/api/tourism", body=body, status=400)

    first = check("관광 검색 첫 페이지", "/api/tourism", body={"limit": 1},
                  valid=lambda data: len(data["items"]) == 1 and bool(data["next_cursor"]))
    if first:
        check("관광 검색 두 번째 페이지에 이전 장소가 중복되지 않음", "/api/tourism",
              body={"limit": 1, "cursor": first["next_cursor"]},
              valid=lambda data: len(data["items"]) == 1 and data["offset"] == 1 and
              data["items"][0]["id"] != first["items"][0]["id"])
    check("관광 검색 최대 offset", "/api/tourism", body={"offset": 1000000},
          valid=lambda data: data["items"] == [] and data["has_more"] is False)
    check("관광 검색 최대 limit", "/api/tourism", body={"limit": 100},
          valid=lambda data: len(data["items"]) == data["total"] and
          all(item["source_overlap_verified"] for item in data["items"]))
    check("관광 검색의 지도 범위와 반경을 교집합으로 적용", "/api/tourism",
          body={"bbox": [126.45, 33.45, 126.55, 33.56], "radius_km": 10, "location": JEJU_AIRPORT},
          valid=lambda data: data["applied_filters"]["bbox_applied"] and data["radius_applied"] and
          all(126.45 <= item["longitude"] <= 126.55 and 33.45 <= item["latitude"] <= 33.56
              and item["distance_km"] <= 10 for item in data["items"]))
    check("음식 검색에서 지도 좌표 없는 기록을 거리 계산에 포함하지 않음", "/api/discover",
          body={"query": "카페", "radius_km": 15, "location": JEJU_AIRPORT},
          valid=lambda data: bool(data["restaurants"]) and
          all(item["distance_km"] <= 15 and item["latitude"] is not None for item in data["restaurants"]) and
          all(item["distance_km"] is None and item["within_radius"] is None
              for item in data["unmapped_restaurants"]))

    for label, raw in (
        ("빈 본문", b""), ("잘린 JSON", b"{"), ("잘못된 UTF-8", b'{"query":"\xff"}'),
        ("객체가 아닌 배열", b"[]"), ("객체가 아닌 null", b"null"), ("객체가 아닌 숫자", b"0"),
        ("깊이 2000 중첩", b'{"query":' + b"[" * 2000 + b"]" * 2000 + b"}"),
    ):
        check(f"잘못된 요청은 입력 오류 / {label}", "/api/guide-search", raw=raw, status=400)
    body = b'{"query":""}'
    padded = body.ljust(32768)
    check("요청 크기 제한 직전", "/api/guide-search", raw=padded, valid=lambda data: data == [])
    check("요청 크기 제한 초과 1바이트", "/api/guide-search", raw=padded + b" ", status=400)
    check("다른 Origin 헤더", "/api/chat", body={"message": "안녕"}, origin="http://localhost:1", status=403)
    check("없는 API", "/api/edge-audit-unknown", body={}, status=404)
    check("종료된 문장 분류 API", "/api/assistant", body={}, status=410)
    check("종료된 합성 장소 API", "/api/recommend", body={}, status=410)
    for endpoint in ("/api/places", "/api/restaurants"):
        for query in ("%_", "' OR 1=1 --", "\0"):
            check(f"명부 특수문자 검색 / {endpoint} / {query!r}", endpoint + "?" + urlencode({"query": query}),
                  status=(200, 400) if query == "\0" else 200,
                  valid=lambda data: "error" in data or (data["total"] == 0 and not data["items"]))
    plan = {"date": "2026-11-06", "transport": "walk", "origin_confirmed": True,
            "origin_source": "landmark", "start_lat": 33.506, "start_lon": 126.492,
            "end_lat": 33.506, "end_lon": 126.492, "start_minute": 540, "end_minute": 1080,
            "budget_krw": 0, "max_stops": 1, "destination_ids": ["osm_tourism_node_538148519"]}
    for token in (b"NaN", b"Infinity", b"1e9999"):
        raw_plan = json.dumps(plan).encode("ascii")[:-1] + b',"extra":' + token + b"}"
        check(f"일정의 추가 필드에도 비유한 JSON 거절 / {token.decode()}", "/api/plan-destinations",
              raw=raw_plan, status=400, valid=lambda data: "유한한 값" in data["error"])
    check("장소 상세 ID 누락", "/api/place-details", status=400)
    check("장소 상세 ID가 존재하지 않음", "/api/place-details?id=edge-audit-unknown", status=404)
    check("장소 상세 ID 121자", "/api/place-details?id=" + "x" * 121, status=400)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    results = audit(args.base_url)
    failed = [result for result in results if not result["passed"]]
    print(json.dumps({"total": len(results), "passed": len(results) - len(failed), "failed": len(failed),
                      "results": results}))
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())

