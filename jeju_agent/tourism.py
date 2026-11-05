"""Separate, source-labelled tourism retrieval and transparent local model cards.

Names and observed classifications train an unsupervised TF-IDF representation.
Retrieval similarity is never visitor popularity, satisfaction, or demand.
"""
from __future__ import annotations

import base64
from collections import Counter
from contextlib import closing
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from .discovery import _distance, _normalized, _point, _tokens
from .catalog_store import access_flags, region_for
from .tourism_overlap import POLICY_ID, build_overlap_records
from .tourism_names import prefer_hub_name


SCHEMA_VERSION = 2
ALGORITHM = "corpus_fitted_tourism_tfidf_cosine"
REGIONS = {"all", "east", "west", "south", "north"}
KINDS = {"attraction", "reference", "all"}
LODGING = {"hotel", "hostel", "guest_house", "motel", "apartment", "chalet", "camp_site", "caravan_site", "wilderness_hut", "alpine_hut"}
ALLOWED_TOURISM = {"attraction", "museum", "gallery", "artwork", "viewpoint", "zoo", "aquarium", "theme_park", "picnic_site"}
ALLOWED_NATURAL = {"beach", "peak", "volcano", "cave_entrance", "waterfall", "wood", "spring", "cape", "cliff", "bay", "rock", "stone", "arch", "sand"}
ALLOWED_LEISURE = {"park", "garden", "nature_reserve", "recreation_ground", "playground", "water_park", "miniature_golf", "golf_course", "sports_centre"}
THEMES = {"바다": ["바다", "해변", "해안", "beach", "coast"], "해변": ["해변", "beach"], "숲": ["숲", "wood", "forest"], "오름": ["오름", "산봉우리", "peak", "volcano"], "박물관": ["박물관", "museum"], "역사": ["역사", "유적", "historic"], "산책": ["산책", "공원", "park", "garden"], "전망": ["전망", "viewpoint"], "동굴": ["동굴", "cave_entrance"], "정원": ["정원", "garden"]}


def _hash(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(model) -> str:
    return hashlib.sha256(json.dumps({key: value for key, value in model.items() if key != "model_sha256"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


@lru_cache(maxsize=32)
def _cached_json(path: str, mtime: int):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _read(path, default=None):
    path = Path(path)
    return _cached_json(str(path.resolve()), path.stat().st_mtime_ns) if path.is_file() else default


def _region(address: str, point: tuple) -> tuple[str, str]:
    if any(value in address for value in ["제주시", "서귀포시", "읍", "면"]):
        return region_for(address), "address_reference"
    return ("east" if point[1] >= 126.75 else "west" if point[1] <= 126.4 else "south" if point[0] <= 33.36 else "north"), "coordinate_sector_heuristic"


def _observed_classification(tags: dict) -> bool:
    if str(tags.get("tourism", "")) in LODGING:
        return False
    return (str(tags.get("tourism", "")) in ALLOWED_TOURISM or str(tags.get("natural", "")) in ALLOWED_NATURAL or str(tags.get("leisure", "")) in ALLOWED_LEISURE or bool(tags.get("historic") and tags["historic"] not in {"no", "false"}))


def _flags(item) -> tuple[bool, bool]:
    ferry, access = access_flags(item["name"], item.get("address") or "", item["latitude"], item["longitude"])
    natural = item.get("observed_tags", {}).get("natural")
    return ferry or bool(item.get("requires_ferry")), access or bool(item.get("requires_access_point")) or natural in {"peak", "volcano", "cave_entrance"}


def _training_terms(item) -> Counter:
    terms = Counter(_tokens(item["name"]) * 3)
    category=(item.get("cross_source") or {}).get("osm",{}).get("category",item.get("category"))
    terms.update(_tokens(category) * 2)
    terms.update(_tokens(item.get("address"), character_ngrams=False))
    if item["source_platform"] == "openstreetmap":
        observed = item.get("observed_tags", {})
        terms.update(_tokens(" ".join(str(observed.get(key) or "") for key in ["tourism", "natural", "leisure", "historic", "description", "description:ko"])))
        terms.update(_tokens(" ".join(item.get("classifications", []))))
    # Curated browse tags/descriptions are returned for display, but the model
    # does not present them as source-observed training descriptions.
    return terms


def build_tourism(root: Path) -> dict:
    root = Path(root)
    started = time.perf_counter()
    reference = root / "data_reference"
    records, aliases, sources, overlap_audit = build_overlap_records(root)
    osm = _read(reference / "osm_tourism_places.json", {})
    osm_count = overlap_audit["accepted_map_records"]
    excluded_lodging = overlap_audit["rejection_counts"].get("lodging_or_camping", 0)
    excluded_classification = sum(value for reason,value in overlap_audit["rejection_counts"].items() if reason in {"food_or_ordinary_amenity","shop","transport_or_utility_infrastructure","ordinary_man_made_feature","ordinary_business_or_industry","not_eligible_tourist_classification","generic_map_tag_conflicts_with_food_permit_name"})
    excluded_coordinates = sum(value for reason,value in overlap_audit["rejection_counts"].items() if reason in {"invalid_map_id_name_or_coordinate","raw_normalized_coordinate_mismatch"})
    if not records:
        raise ValueError("관광 검색 학습 자료가 없습니다.")
    if len({item["id"] for item in records}) != len(records):
        raise ValueError("관광 검색 자료의 식별자가 중복되었습니다. 출처별 ID를 보존하세요.")
    documents = [_training_terms(item) for item in records]
    frequencies = Counter(term for terms in documents for term in terms)
    vocabulary = {term: index for index, term in enumerate(sorted(frequencies))}
    idf = [0.0] * len(vocabulary)
    for term, index in vocabulary.items():
        idf[index] = math.log((1 + len(records)) / (1 + frequencies[term])) + 1
    output = root / "models_tourism"
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "tourism.building.sqlite"
    if temporary.exists():
        temporary.unlink()
    postings = 0
    with closing(sqlite3.connect(temporary)) as db:
        db.executescript("""PRAGMA journal_mode=OFF;PRAGMA synchronous=OFF;
          CREATE TABLE places(doc_id INTEGER PRIMARY KEY,id TEXT UNIQUE,name TEXT,kind TEXT,category TEXT,region TEXT,latitude REAL,longitude REAL,data_json TEXT);
          CREATE INDEX filters ON places(kind,region,category);
          CREATE INDEX bounds ON places(longitude,latitude);
          CREATE TABLE aliases(source_id TEXT PRIMARY KEY,place_id TEXT NOT NULL);
          CREATE TABLE postings(term_id INTEGER,doc_id INTEGER,weight REAL,PRIMARY KEY(term_id,doc_id)) WITHOUT ROWID;""")
        for index, (item, terms) in enumerate(zip(records, documents)):
            db.execute("INSERT INTO places VALUES(?,?,?,?,?,?,?,?,?)", (index, item["id"], item["name"], item["kind"], item["category"], item["region"], item["latitude"], item["longitude"], json.dumps(item, ensure_ascii=False, separators=(",", ":"))))
            values = [(vocabulary[term], (1 + math.log(count)) * idf[vocabulary[term]]) for term, count in terms.items()]
            norm = math.sqrt(sum(value * value for _, value in values)) or 1
            db.executemany("INSERT INTO postings VALUES(?,?,?)", [(term, index, value / norm) for term, value in values])
            postings += len(values)
        db.executemany("INSERT INTO aliases VALUES(?,?)", sorted(aliases.items()))
        db.commit()
    database = reference / "tourism.sqlite"
    temporary.replace(database)
    kind_counts = Counter(item["kind"] for item in records)
    source_counts = Counter(item["source_platform"] for item in records)
    categories = Counter(item["category"] for item in records if item["kind"] == "attraction")
    edit_dates = sorted(item["source_date"] for item in records if item["source_platform"] == "openstreetmap" and item.get("source_date"))
    source_version = hashlib.sha256(json.dumps(sources, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    model = {"schema_version": SCHEMA_VERSION, "model_version": "tourism_tfidf_v1_" + source_version, "algorithm": ALGORITHM, "training_rows": len(records), "training_rows_unit": "cross_source_verified_deduplicated_places", "candidate_policy_id": POLICY_ID, "source_overlap_verified": True, "kind_counts": dict(kind_counts), "source_counts": dict(source_counts), "source_period": {"osm_snapshot_at": osm.get("snapshot_at") if osm else None, "osm_element_edit_start": edit_dates[0] if edit_dates else None, "osm_element_edit_end": edit_dates[-1] if edit_dates else None, "hub_reference_date": sources.get("hub1349", {}).get("reference_date"), "featured_verified_on": sorted({item.get("verified_on") for item in records if item.get("featured") and item.get("verified_on")})}, "sources": sources, "vocabulary": vocabulary, "idf": idf, "idf_formula": "log((1+document_count)/(1+document_frequency))+1", "tf_formula": "1+log(term_count)", "l2_normalized": True, "trained_fields": ["name", "known_category", "address", "observed_osm_classifications", "observed_osm_description_if_present"], "excluded_training_fields": ["curated_editorial_description", "curated_editorial_browse_tags"], "overlap_validation": {key:value for key,value in overlap_audit.items() if key not in {"accepted","rejected"}}, "database_sha256": _hash(database), "retrieval_accuracy_evaluated": False, "predicts_popularity": False, "predicts_satisfaction": False}
    model["model_sha256"] = _digest(model)
    model_path = output / "tourism_tfidf.json"
    model_path.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    profile = {key: value for key, value in model.items() if key not in {"vocabulary", "idf"}}
    profile.update(status="built", vocabulary_terms=len(vocabulary), postings=postings, database_bytes=database.stat().st_size, model_bytes=model_path.stat().st_size, build_seconds=round(time.perf_counter()-started,3), available_categories=[{"value":key,"label":key,"count":value} for key,value in sorted(categories.items())], classification_validation={"osm_accepted":osm_count,"explicit_lodging_excluded":excluded_lodging,"unrecognized_classification_excluded":excluded_classification,"invalid_id_or_coordinate_excluded":excluded_coordinates}, limitations=["빅데이터 명부와 지도 기록의 정규화 명칭·250m 위치가 일치하고 보수적 분류 검증을 통과한 후보만 사용합니다.", overlap_audit["limitation"], "동일 명칭·근접 지도 기록을 후보 그룹 한 곳으로 정리하고 명부의 복수 근거 행을 모두 보존합니다. 분리된 지도 그룹이 같은 명부 행으로 경쟁하면 제외합니다.", "관광 TF-IDF는 교차확인 후보의 문자 검색 모델입니다. 인기·만족도·방문량을 예측하지 않습니다.", "전체 OSM 원본 태그에서 음식점·숙박·상점·일반 시설을 검토합니다. generic 관광 태그와 음식 인허가 명칭이 충돌하면 보류합니다.", "공개 좌표는 실제 입구·개방·예약·요금·도로 접근을 검증한 위치가 아닙니다."])
    (reference / "tourism_overlap_audit.json").write_text(json.dumps(overlap_audit,ensure_ascii=False,indent=2),encoding="utf-8")
    (reference / "tourism_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    _load_model.cache_clear()
    _cached_json.cache_clear()
    _write_report(root, profile)
    return profile


@lru_cache(maxsize=4)
def _load_model(path: str, mtime: int, database: str, database_mtime: int) -> dict:
    model = json.loads(Path(path).read_text(encoding="utf-8"))
    vocab, idf = model.get("vocabulary"), model.get("idf")
    if model.get("schema_version") != SCHEMA_VERSION or model.get("candidate_policy_id") != POLICY_ID or model.get("source_overlap_verified") is not True or model.get("algorithm") != ALGORITHM or not isinstance(vocab, dict) or not isinstance(idf, list) or len(vocab) != len(idf) or not vocab:
        raise ValueError("관광 TF-IDF 모델 형식이 올바르지 않습니다.")
    if set(vocab.values()) != set(range(len(idf))) or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in idf):
        raise ValueError("관광 TF-IDF 계수와 차원을 확인하세요.")
    if model.get("model_sha256") != _digest(model) or model.get("database_sha256") != _hash(database):
        raise ValueError("관광 모델 또는 자료 SHA256이 일치하지 않습니다.")
    return model


def _number(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label} 값이 올바르지 않습니다.")
    return float(value)


def _request(body) -> dict:
    if not isinstance(body, dict):
        raise ValueError("요청은 JSON 객체여야 합니다.")
    query, region, category, kind = body.get("query", ""), body.get("region", "all"), body.get("category", "all"), body.get("kind", "attraction")
    if not isinstance(query, str) or len(query) > 100 or not isinstance(category, str) or len(category) > 80:
        raise ValueError("검색어는 100자, 분류는 80자 이내 문자열이어야 합니다.")
    if not isinstance(region, str) or region not in REGIONS or not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("지역 또는 kind 필터가 올바르지 않습니다.")
    limit, offset = body.get("limit", 30), body.get("offset", 0)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100 or isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1000000:
        raise ValueError("limit는 1~100, offset은 0 이상의 정수여야 합니다.")
    radius = body.get("radius_km")
    if radius is not None:
        radius = _number(radius, 1, 100, "반경 km")
    point, location_status = None, "not_provided"
    location = body.get("location")
    if location is not None:
        if not isinstance(location, dict):
            raise ValueError("location은 위도·경도 객체여야 합니다.")
        lat = _number(location.get("latitude"), -90, 90, "위도")
        lon = _number(location.get("longitude"), -180, 180, "경도")
        if location.get("accuracy_m") is not None:
            _number(location["accuracy_m"], 0, 100000, "위치 정확도")
        point = _point(lat, lon)
        location_status = "provided" if point else "outside_jeju"
    bbox = body.get("bbox")
    if bbox is not None:
        if isinstance(bbox, dict):
            bbox = [bbox.get(key) for key in ["west", "south", "east", "north"]]
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("bbox는 [west,south,east,north] 형식이어야 합니다.")
        bbox = [_number(value, -180 if index in {0, 2} else -90, 180 if index in {0, 2} else 90, "지도 범위") for index, value in enumerate(bbox)]
        if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError("bbox의 서쪽·남쪽은 동쪽·북쪽보다 작아야 합니다.")
    cursor = body.get("cursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 300):
        raise ValueError("cursor 형식이 올바르지 않습니다.")
    return dict(query=query.strip(), region=region, category=category, kind=kind, limit=limit, offset=offset, cursor=cursor, point=point, bbox=bbox, location_status=location_status, radius=radius)


def _vector(query, model):
    expanded = sorted({term for theme, terms in THEMES.items() if theme in query for term in terms})
    terms = Counter(_tokens(query + " " + " ".join(expanded)))
    values = {model["vocabulary"][term]: (1 + math.log(count)) * model["idf"][model["vocabulary"][term]] for term, count in terms.items() if term in model["vocabulary"]}
    norm = math.sqrt(sum(value * value for value in values.values())) or 1
    return {key: value / norm for key, value in values.items()}, expanded


def _cursor(offset, model):
    return base64.urlsafe_b64encode(json.dumps({"offset": offset, "version": model["model_version"], "model": model["model_sha256"][:16]}, separators=(",", ":")).encode()).decode().rstrip("=")


def search_tourism(root: Path, body=None) -> dict:
    root = Path(root)
    request = _request({} if body is None else body)
    database, path = root / "data_reference" / "tourism.sqlite", root / "models_tourism" / "tourism_tfidf.json"
    model = _load_model(str(path.resolve()), path.stat().st_mtime_ns, str(database.resolve()), database.stat().st_mtime_ns)
    if request["cursor"]:
        try:
            cursor = json.loads(base64.urlsafe_b64decode(request["cursor"] + "=" * (-len(request["cursor"]) % 4)))
            if cursor["version"] != model["model_version"] or cursor["model"] != model["model_sha256"][:16] or isinstance(cursor["offset"], bool) or not isinstance(cursor["offset"], int) or not 0 <= cursor["offset"] <= 1000000:
                raise ValueError("stale cursor")
            request["offset"] = cursor["offset"]
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ValueError("cursor가 유효하지 않거나 다른 모델 버전의 값입니다.") from exc
    vector, expanded = _vector(request["query"], model)
    scores = {}
    clauses, params = [], []
    for field in ["kind", "region", "category"]:
        if request[field] != "all":
            clauses.append(field + "=?")
            params.append(request[field])
    if request["bbox"]:
        west, south, east, north = request["bbox"]
        clauses += ["longitude>=?", "latitude>=?", "longitude<=?", "latitude<=?"]
        params += [west, south, east, north]
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if vector:
            values = ",".join("(?,?)" for _ in vector)
            arguments = [value for pair in vector.items() for value in pair]
            scores = {row["doc_id"]: row["score"] for row in db.execute(f"WITH q(term_id,weight) AS (VALUES {values}) SELECT p.doc_id,SUM(p.weight*q.weight) AS score FROM postings p JOIN q ON p.term_id=q.term_id GROUP BY p.doc_id", arguments)}
        candidates = []
        for row in db.execute("SELECT doc_id,data_json FROM places" + (" WHERE " + " AND ".join(clauses) if clauses else ""), params):
            score = scores.get(row["doc_id"], 0.0)
            if request["query"] and score <= 0:
                continue
            item = json.loads(row["data_json"])
            if not _approved(item):continue
            distance = _distance(request["point"], (item["latitude"], item["longitude"])) if request["point"] else None
            if distance is not None and request["radius"] is not None and distance > request["radius"]:
                continue
            theme_classification_match = False
            if expanded:
                observed = item.get("observed_tags", {})
                classification_text = _normalized(item["category"] + " " + " ".join(str(observed.get(key) or "") for key in ["tourism", "natural", "leisure", "historic"]))
                theme_classification_match = any(_normalized(term) in classification_text for term in expanded)
                theme_text = _normalized(item["name"] + " " + item["category"] + " " + " ".join(str(observed.get(key) or "") for key in ["tourism", "natural", "leisure", "historic", "description", "description:ko"]))
                # Character bigrams alone must not turn "peak" into "beach"
                # because both happen to contain the English bigram "ea".
                if not any(_normalized(term) in theme_text for term in expanded):
                    continue
            name_match = bool(request["query"] and _normalized(request["query"]) in _normalized(item["name"]))
            training = _training_terms(item)
            intersect = sorted((term for term in training if term in model["vocabulary"] and model["vocabulary"][term] in vector and (term.startswith("w:") or re.search(r"[가-힣]", term))), key=lambda term: (not term.startswith("w:"), -model["idf"][model["vocabulary"][term]], term))
            evidence, seen_terms = [], set()
            for term in intersect:
                if term[2:] in seen_terms:
                    continue
                seen_terms.add(term[2:])
                evidence.append({"term": term[2:], "feature": "word" if term.startswith("w:") else "character_bigram", "idf": round(model["idf"][model["vocabulary"][term]], 4)})
                if len(evidence) >= 8:
                    break
            tier = (0 if theme_classification_match else 1 if name_match else 2) if expanded else (0 if name_match else 1)
            item.update(plan_place_id=item["id"], similarity_score=round(score, 6) if request["query"] else None, score_definition="TF-IDF 문자 관련도이며 인기도·만족도 확률이 아닙니다.", evidence_terms=evidence, match_reason="관측 분류와 검색 테마가 일치" if theme_classification_match else "장소명에 검색어 직접 일치" if name_match else "실제 이름·관측 분류의 학습된 문자 표현과 검색어가 관련됩니다." if request["query"] else "위치가 있으면 직선거리순, 없으면 공식 참조와 이름순입니다.", ranking_tier=tier, theme_classification_match=theme_classification_match, distance_km=round(distance, 3) if distance is not None else None)
            candidates.append(prefer_hub_name(item))
        category_rows = [dict(row) for row in db.execute("SELECT category AS value,category AS label,COUNT(*) AS count FROM places" + (" WHERE kind=?" if request["kind"] != "all" else "") + " GROUP BY category ORDER BY category", [request["kind"]] if request["kind"] != "all" else [])]
    if request["query"] and request["point"]:
        candidates.sort(key=lambda item: (item["ranking_tier"], item["distance_km"], -item["similarity_score"], item["name"], item["id"]))
    elif request["query"]:
        candidates.sort(key=lambda item: (item["ranking_tier"], -item["similarity_score"], item["name"], item["id"]))
    elif request["point"]:
        candidates.sort(key=lambda item: (item["distance_km"], item["name"], item["id"]))
    else:
        candidates.sort(key=lambda item: (-int(item.get("featured", False)), item["name"], item["id"]))
    total, offset = len(candidates), request["offset"]
    items = candidates[offset:offset + request["limit"]]
    next_offset = offset + len(items) if offset + len(items) < total else None
    warnings = ["빅데이터 명부와 지도 기록의 명칭·위치를 교차확인한 관광 후보만 표시합니다. 명부·지도 한쪽에만 있는 장소는 관광 추천에서 제외합니다.", "허브 1349는 분류 미확인 여행장소 명부이며 교차확인 결과가 공식 지정 관광지나 현재 영업 검증을 뜻하지 않습니다.", "검색 관련도는 문자 표현이며 관광객 인기도·만족도·방문량을 예측한 점수가 아닙니다.", "공개 분류와 대표 좌표는 실제 입구·개방·예약·요금·도로 접근을 검증한 정보가 아닙니다."]
    if request["kind"] == "reference":warnings.append("분류 미확인 여행장소 명부는 관광 검색에서 제공하지 않습니다. 교차확인 관광지를 선택하세요.")
    if request["location_status"] == "outside_jeju":
        warnings.append("제공 위치가 제주 범위 밖이므로 거리 정렬과 반경 필터를 적용하지 않았습니다.")
    elif request["radius"] is not None and request["point"] is None:
        warnings.append("기준 위치가 없어 요청한 반경 필터를 적용하지 않았습니다.")
    radius_applied = request["point"] is not None and request["radius"] is not None
    from .tourism_guides import enrich_tourism
    items=[enrich_tourism(root,item) for item in items]
    return {"status": "tourism_reference_search", "items": items, "total": total, "offset": offset, "limit": request["limit"], "next_offset": next_offset, "next_cursor": _cursor(next_offset, model) if next_offset is not None else None, "has_more": next_offset is not None, "available_categories": category_rows, "location_status": request["location_status"], "radius_km": request["radius"], "radius_applied": radius_applied, "distance_basis": "provided_location_straight_line" if request["point"] is not None else "not_available", "applied_filters": {"query": request["query"], "region": request["region"], "category": request["category"], "kind": request["kind"], "bbox_applied": request["bbox"] is not None, "radius_applied": radius_applied}, "model": {"algorithm": ALGORITHM, "model_version": model["model_version"], "training_rows": model["training_rows"], "training_rows_unit": model["training_rows_unit"], "kind_counts": model["kind_counts"], "source_counts": model["source_counts"], "candidate_policy_id": model["candidate_policy_id"], "source_overlap_verified": True, "overlap_validation": model["overlap_validation"], "source_period": model["source_period"], "vocabulary_terms": len(model["vocabulary"]), "learned_component": "corpus_document_frequency_idf_and_l2_document_vectors", "query_expansion_rules": expanded, "retrieval_accuracy_evaluated": False, "predicts_popularity": False, "predicts_satisfaction": False}, "attributions": [{"text": "© OpenStreetMap contributors", "license": "ODbL-1.0", "copyright_url": "https://www.openstreetmap.org/copyright"}] if "osm" in model["sources"] else [], "privacy": {"precise_location_persisted": False, "precise_location_echoed": False}, "warnings": warnings}


def _approved(item):
    evidence=item.get("cross_source") or {}
    return item.get("kind")=="attraction" and item.get("source_overlap_verified") is True and evidence.get("policy_id")==POLICY_ID and evidence.get("match_method")=="normalized_exact_name_and_distance" and isinstance(evidence.get("distance_m"),(int,float)) and not isinstance(evidence.get("distance_m"),bool) and 0<=evidence["distance_m"]<=250 and bool(evidence.get("hub",{}).get("id")) and bool(evidence.get("osm",{}).get("id"))


def resolve_tourism_place(root: Path, ident) -> dict | None:
    if not isinstance(ident,str) or len(ident)>160:return None
    root=Path(root);path=root/"data_reference/tourism.sqlite";model_path=root/"models_tourism/tourism_tfidf.json"
    if not path.is_file() or not model_path.is_file():return None
    try:
        _load_model(str(model_path.resolve()),model_path.stat().st_mtime_ns,str(path.resolve()),path.stat().st_mtime_ns)
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)) as db:
            row=db.execute("SELECT data_json FROM places WHERE id=COALESCE((SELECT place_id FROM aliases WHERE source_id=?),?)",(ident,ident)).fetchone()
    except (ValueError,sqlite3.DatabaseError):return None
    if row is None:return None
    item=json.loads(row[0])
    if not _approved(item) or _point(item.get("latitude"),item.get("longitude")) is None:return None
    item["requires_ferry"],item["requires_access_point"]=_flags(item)
    from .tourism_guides import enrich_tourism
    return enrich_tourism(root,item)


def get_model_info(root: Path) -> dict:
    root = Path(root)
    cards = []
    tourism = _read(root / "data_reference/tourism_profile.json", {})
    cards.append({"id": "tourism_tfidf", "title": "빅데이터·지도 교차확인 관광지 검색", "available": bool(tourism), "algorithm": tourism.get("algorithm"), "model_version": tourism.get("model_version"), "training_rows": tourism.get("training_rows"), "training_rows_unit": "교차확인 후 중복 정리한 관광 후보", "candidate_policy_id": tourism.get("candidate_policy_id"), "overlap_validation": tourism.get("overlap_validation"), "kind_counts": tourism.get("kind_counts"), "source_period": tourism.get("source_period"), "vocabulary_terms": tourism.get("vocabulary_terms"), "evaluation": {"retrieval_accuracy_evaluated": False, "note": "IDF를 실제 말뭉치에서 학습했습니다. 정답 추천·인기·만족도 정확도를 측정한 모델은 아닙니다."}, "model_sha256": tourism.get("model_sha256"), "limitations": tourism.get("limitations", [])})
    food = _read(root / "data_reference/discovery_profile.json", {})
    catalogue = _read(root / "data_reference/catalog_profile.json", {})
    cards.append({"id": "food_tfidf", "title": "음식 취향 문자 검색", "available": bool(food), "algorithm": food.get("algorithm"), "model_version": "food_tfidf_v1", "training_rows": food.get("training_documents"), "training_rows_unit": "인허가·독립 OSM 업소 기록", "source_period": {"hub_reference_date": catalogue.get("food_source_date"), "osm_snapshot_at": food.get("osm_source", {}).get("snapshot_at") if food.get("osm_source") else None}, "vocabulary_terms": food.get("vocabulary_terms"), "evaluation": {"retrieval_accuracy_evaluated": False, "note": "이름·업종·있는 cuisine 태그의 문자 표현을 학습했습니다. 메뉴·맛·인기도 검증이 아닙니다."}, "limitations": food.get("limitations", [])})
    audience = _read(root / "models_audience/audience_metrics.json", {})
    selection = audience.get("selection", {})
    selected = selection.get("selected")
    cards.append({"id": "audience_distribution", "title": "집단별 과거 소비 구성비", "available": bool(audience), "algorithm": "audience_group_mean_category_distribution" if selected == "audience_mean" else audience.get("algorithm"), "candidate_algorithm": audience.get("algorithm"), "selected_serving_model": selected, "model_version": audience.get("schema_version",1), "training_rows": audience.get("source", {}).get("aggregate_cells"), "training_rows_unit": "월·집단·업종 관측 셀", "source_rows_used": audience.get("source", {}).get("used_source_rows"), "source_period": audience.get("observation_period"), "validation": audience.get("validation"), "test": audience.get("test"), "selected_test_metrics": audience.get("test", {}).get("baseline" if selected == "audience_mean" else "model"), "selection": selection, "split": audience.get("split"), "limitations": audience.get("limitations", [])})
    mobility = _read(root / "models_mobility/mobility_metrics.json", {})
    serving = mobility.get("serving_selection", {})
    selected = serving.get("selected_serving_model")
    cards.append({"id": "mobility_pattern", "title": "과거 승차 시간대 패턴", "available": bool(mobility), "algorithm": "weekday_bucket_mean_hourly_regular_ticket_demand" if selected == "weekday_bucket_mean" else mobility.get("algorithm"), "candidate_algorithm": mobility.get("algorithm"), "selected_serving_model": selected, "model_version": mobility.get("schema_version",1), "training_rows": mobility.get("selection", {}).get("selected_rows"), "training_rows_unit": "일반승차 날짜·시간대 관측 셀", "source_period": mobility.get("observation_period"), "validation": mobility.get("validation"), "test": mobility.get("test"), "selected_test_metrics": mobility.get("test", {}).get("baseline" if selected == "weekday_bucket_mean" else "model"), "selection": serving, "split": mobility.get("split"), "limitations": mobility.get("limitations", [])})
    usage = {"tourism_tfidf": "교차확인 관광 후보의 명칭·관측 분류 문자 검색", "food_tfidf": "음식 이름과 관측 업종·있는 태그의 문자 검색", "audience_distribution": "집단별 과거 8업종 구성비 참고", "mobility_pattern": "일반승차의 과거 달력·시간대 패턴 참고"}
    for card in cards:
        card.update(sample_count=card.get("training_rows"), training_documents=card.get("training_rows") if card["id"] in {"tourism_tfidf", "food_tfidf"} else None, period=card.get("source_period"), metrics={"validation": card.get("validation"), "test": card.get("test"), "selected_test": card.get("selected_test_metrics"), "evaluation": card.get("evaluation")}, usage=usage[card["id"]], caveat=(card.get("limitations") or [card.get("evaluation", {}).get("note") or "관측 범위와 데이터의 한계를 확인하세요."])[0])
    return {"runtime": "offline_cpu", "cards": cards, "models": cards, "requires_cloud": False, "requires_gpu": False, "note": "실제 출처의 검색 TF-IDF와 소비·승차 집계 모델만 제공합니다. 실제 개별 장소 인기도 점수는 없습니다."}


def _write_report(root: Path, profile: dict):
    cards = get_model_info(root)["cards"]
    lines = ["# 관광 검색 모델 검증 v11", "", "관광 검색은 실제 명칭과 관측 분류의 TF-IDF 표현을 학습한 비지도 검색입니다. 점포나 관광지의 인기, 만족도, 방문량을 예측하지 않습니다.", "", "## 학습 자료", "", f"학습 문서 {profile['training_rows']:,}개 중 기본 관광·자연 기록은 {profile['kind_counts'].get('attraction', 0):,}개, 별도 여행장소 참조 명부는 {profile['kind_counts'].get('reference', 0):,}개입니다. 허브 명부와 지도 명칭·250m 교차확인 후 허브 장소별 중복 정리한 후보 수입니다.", "", f"어휘 {profile['vocabulary_terms']:,}개와 희소 가중치 {profile['postings']:,}개를 학습했습니다. IDF는 log((1+문서 수)/(1+문서 빈도))+1로 계산하고 문서 벡터를 L2 정규화했습니다.", "", "학습에는 이름, 알려진 분류, 주소, 실제 OSM 분류 태그와 있는 원문 설명만 사용합니다. 공식 참조 카드의 편집 태그와 편집 소개문은 관측 설명으로 학습하지 않습니다.", "", "## 검증 범위", "", "교차확인을 통과한 attraction만 색인에 포함합니다. 분류 미확인 reference는 관광 검색에서 제외합니다. 전체 지도 태그의 음식점·상점·숙박·일반 시설 검토와 음식 인허가 명칭 충돌 검토를 적용합니다. 문자 관련도는 추천 정확도 평가가 아니며 라벨이 있는 사용자 선호 검증은 아직 없습니다.", "", "검색은 지역·분류·지도 범위·테마·선택적 위치를 지원합니다. 원시 GPS를 로그나 파일에 남기거나 응답 및 cursor에 넣지 않습니다. cursor는 공개 모델 버전과 다음 offset만 포함합니다.", "", "## 과거 집계 모델 비교", "", "| 모델 | 서비스 선택 | 검증 및 테스트 근거 |", "|---|---|---|"]
    for card in cards:
        if card["id"] == "audience_distribution":
            test = card.get("test") or {}
            lines.append(f"| 집단 소비 | {card.get('selected_serving_model')} | 테스트 구성비 MAE 실험 {test.get('model', {}).get('mae_share')}, 평균 기준 {test.get('baseline', {}).get('mae_share')} |")
        if card["id"] == "mobility_pattern":
            test = card.get("test") or {}
            lines.append(f"| 승차 시간대 | {card.get('selected_serving_model')} | 테스트 시간당 MAE 실험 {test.get('model', {}).get('mae_per_hour')}, 평균 기준 {test.get('baseline', {}).get('mae_per_hour')} |")
    lines += ["", "선택은 각 모델의 기존 검증 구간 오차를 기준으로 했으며 기존 테스트를 재탐색하지 않았습니다. 관광 TF-IDF의 성능으로 위 집계 모델 수치를 제시하면 안 됩니다.", "", "## 출처와 제한", ""] + ["- " + note for note in profile["limitations"]] + ["", "OSM 구성요소는 © OpenStreetMap contributors, ODbL-1.0 및 https://www.openstreetmap.org/copyright 출처 조건을 보존합니다. 실제 입구, 개방, 요금, 예약, 접근 경로는 별도 확인이 필요합니다."]
    folder = root / "docs"
    folder.mkdir(exist_ok=True)
    (folder / "관광모델검증_v11.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
