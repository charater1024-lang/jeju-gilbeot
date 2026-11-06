"""Offline TF-IDF discovery with explicit food rules and conservative coordinates.

TF-IDF is fitted on names, permit categories, and addresses. It is an unsupervised
text representation, not a learned menu, taste, quality, or popularity predictor.
Only exact normalized name AND full-address matches may transfer coordinates
from source 1349 to a source 780 permit record. User coordinates are never saved.
"""
from __future__ import annotations

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
import unicodedata


VERSION = 1
ALGORITHM = "corpus_fitted_tfidf_cosine_with_explicit_food_rules"
REGIONS = {"all", "east", "west", "south", "north"}
RULES = {
    "흑돼지": ["흑돼지", "흑돈", "돼지", "삼겹", "오겹"],
    "갈치": ["갈치", "은갈치", "생선조림", "생선구이"],
    "고기국수": ["고기국수", "국수", "국시"],
    "해산물": ["해산물", "해물", "횟집", "회센터", "수산", "전복"],
    "한식": ["한식"],
    "카페": ["카페", "커피", "coffee", "cafe", "커피숍", "다방", "전통찻집"],
}
RULE_TRIGGERS = {
    "흑돼지": ["흑돼지", "흑돈", "돼지", "삼겹", "오겹"],
    "갈치": ["갈치"], "고기국수": ["고기국수", "국수", "국시"],
    "해산물": ["해산물", "해물", "횟집", "전복"],
    "한식": ["한식"], "카페": ["카페", "커피", "coffee", "cafe"],
}
CATEGORY_SUPPORT = {"흑돼지": ["한식", "식육(숯불구이)"], "갈치": ["한식", "횟집"], "고기국수": ["한식", "분식"], "해산물": ["한식", "횟집", "일식"], "한식": ["한식"], "카페": ["커피숍", "다방", "전통찻집", "제과점영업"]}
CUISINE_HINTS = {"흑돼지": ["black_pork", "pork"], "갈치": ["cutlassfish", "hairtail"], "고기국수": ["noodles", "korean_noodles"], "해산물": ["seafood", "fish", "sushi"], "한식": ["korean"], "카페": ["coffee", "coffee_shop", "cafe"]}
OSM_QUALITY = "OSM 공동편집 지도 좌표 · 입구·메뉴·현재 영업 미확인"


def _normalized(value) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


def _reference_terms(query: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", query).casefold()
    return list(dict.fromkeys(re.findall(r"[가-힣a-z0-9]+", normalized)))


def _reference_profile(database: Path, profile: Path) -> dict:
    return _checked_profile(str(database.resolve()), database.stat().st_mtime_ns, database.stat().st_size,
                            str(profile.resolve()), profile.stat().st_mtime_ns, profile.stat().st_size)


@lru_cache(maxsize=4)
def _checked_profile(database: str, database_mtime: int, database_size: int,
                     profile: str, profile_mtime: int, profile_size: int) -> dict:
    metadata = json.loads(Path(profile).read_text(encoding="utf-8"))
    if metadata.get("status") != "built" or metadata.get("database_sha256") != _hash(database):
        raise ValueError("검색 자료의 SHA256이 일치하지 않습니다.")
    return metadata


def _tokens(value, character_ngrams=True) -> list[str]:
    words = re.findall(r"[가-힣a-z0-9]+", unicodedata.normalize("NFKC", str(value or "")).casefold())
    result = []
    for word in words:
        result.append("w:" + word)
        if character_ngrams:
            result.extend("c:" + word[index:index + 2] for index in range(min(len(word) - 1, 79)))
    return result


def _document_terms(item) -> Counter:
    # Field weights are transparent retrieval rules, separate from corpus IDF.
    terms = Counter(_tokens(item["name"]) * 3)
    terms.update(_tokens(item["category"]) * 2)
    terms.update(_tokens(item["address"], character_ngrams=False))
    terms.update(_tokens(item.get("cuisine"), character_ngrams=False) * 2)
    return terms


def _point(lat, lon) -> tuple[float, float] | None:
    try:
        if isinstance(lat, bool) or isinstance(lon, bool):
            return None
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lon) or not (32.9 <= lat <= 33.7 and 126.0 <= lon <= 127.0):
        return None
    return lat, lon


def _generic_place_label(name) -> bool:
    compact = _normalized(name)
    return bool(re.search(r"\d+일차|\d+일째|첫째날|둘째날|셋째날", compact)) or compact in {"렌트카반납", "렌터카반납", "숙소", "아침", "점심", "저녁", "공항도착", "체크인", "체크아웃", "출발", "도착", "휴식"}


def _distance(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _hash(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(model) -> str:
    return hashlib.sha256(json.dumps({key: value for key, value in model.items() if key != "model_sha256"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _osm_documents(root: Path) -> tuple[list[dict], dict | None]:
    source = root / "data_reference" / "osm_food_places.json"
    if not source.is_file():
        return [], None
    dataset = json.loads(source.read_text(encoding="utf-8"))
    if dataset.get("data_license") != "ODbL-1.0" or not dataset.get("attribution"):
        raise ValueError("OSM 자료에는 ODbL-1.0 이용조건과 출처 표시가 필요합니다.")
    from .catalog_store import access_flags, region_for
    result, seen, excluded = [], set(), 0
    for raw in dataset.get("items", []):
        ident = raw.get("id")
        match = re.fullmatch(r"osm_(node|way|relation)_([1-9][0-9]*)", ident or "")
        point = _point(raw.get("latitude"), raw.get("longitude"))
        name = str(raw.get("name") or "").strip()
        if match is None or point is None or not name or raw.get("amenity") not in {"restaurant", "cafe", "fast_food"}:
            excluded += 1
            continue
        if ident in seen:
            raise ValueError("OSM 자료에 중복 element 식별자가 있습니다.")
        seen.add(ident)
        address = str(raw.get("address") or "").strip()
        has_region_address = any(token in address for token in ["제주시", "서귀포시", "읍", "면"])
        region = region_for(address) if has_region_address else "east" if point[1] >= 126.75 else "west" if point[1] <= 126.4 else "south" if point[0] <= 33.36 else "north"
        ferry, access = access_flags(name, address, point[0], point[1])
        cuisine = raw.get("cuisine")
        if cuisine is not None and not isinstance(cuisine, str):
            raise ValueError("OSM cuisine 태그는 문자열 또는 null이어야 합니다.")
        source_url = f"https://www.openstreetmap.org/{match.group(1)}/{match.group(2)}"
        category = str(raw.get("category") or {"restaurant": "음식점", "cafe": "카페", "fast_food": "패스트푸드"}[raw["amenity"]])
        tags = [raw["amenity"]] + [value.strip() for value in (cuisine or "").split(";") if value.strip()]
        provenance = {"dataset_id": "OpenStreetMap", "source_url": source_url, "source_date": raw.get("source_date"), "snapshot_at": raw.get("snapshot_at") or dataset.get("snapshot_at"), "coordinate_kind": raw.get("coordinate_kind"), "join_method": "standalone_osm_element_no_permit_registry_join", "match_confidence": "standalone_map_record", "quality": OSM_QUALITY, "region_quality": "address_reference" if has_region_address else "coordinate_sector_heuristic", "license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors", "copyright_url": "https://www.openstreetmap.org/copyright"}
        result.append({"id": ident, "name": name, "category": category, "address": address, "region": region, "status": "현재 영업 미확인", "source_date": raw.get("source_date") or str(dataset.get("snapshot_at", ""))[:10], "source_url": source_url, "latitude": point[0], "longitude": point[1], "coordinate_source": json.dumps(provenance, ensure_ascii=False), "coordinate_match": "standalone_osm_map_record", "requires_ferry": int(ferry), "requires_access_point": int(access), "source_platform": "openstreetmap", "tags_json": json.dumps(tags, ensure_ascii=False), "cuisine": cuisine, "snapshot_at": provenance["snapshot_at"], "data_license": "ODbL-1.0"})
    return result, {"source_path": "data_reference/osm_food_places.json", "sha256": _hash(source), "documents": len(result), "excluded_invalid_records": excluded, "cuisine_tags_present": sum(bool(item["cuisine"]) for item in result), "addresses_present": sum(bool(item["address"]) for item in result), "snapshot_at": dataset.get("snapshot_at"), "data_license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors", "copyright_url": "https://www.openstreetmap.org/copyright"}


def build_discovery(root: Path) -> dict:
    """Fit the corpus vocabulary/IDF and build an independent read-only index."""
    started = time.perf_counter()
    root = Path(root)
    source = root / "data_reference" / "catalog.sqlite"
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        foods = [dict(row) for row in db.execute("SELECT id,name,category,address,region,status,source_date,source_url FROM restaurants ORDER BY id")]
        places = [dict(row) for row in db.execute("SELECT id,name,address,latitude,longitude,source_date,source_url,requires_ferry,requires_access_point FROM places ORDER BY id")]
    if not foods:
        raise ValueError("음식점 학습 말뭉치가 비어 있습니다.")
    hub_documents = len(foods)
    for food in foods:
        food.update(source_platform="jeju_datahub", tags_json="[]", cuisine=None, snapshot_at=None, data_license=None)
    osm_foods, osm_profile = _osm_documents(root)
    foods.extend(osm_foods)
    matches = {}
    invalid_points = 0
    generic_places = 0
    for place in places:
        if _generic_place_label(place["name"]):
            generic_places += 1
            continue
        point = _point(place["latitude"], place["longitude"])
        if point is None:
            invalid_points += 1
            continue
        key = (_normalized(place["name"]), _normalized(place["address"]))
        if not all(key):
            continue
        matches.setdefault(key, []).append(place)
    documents, frequencies = [], Counter()
    coordinate_count, ambiguous_count = 0, 0
    for food in foods:
        if not food["id"] or not food["name"] or (food["source_platform"] != "openstreetmap" and not food["address"]):
            raise ValueError("음식점 말뭉치의 식별자, 이름, 주소는 비어 있으면 안 됩니다.")
        candidates = matches.get((_normalized(food["name"]), _normalized(food["address"])), []) if food["source_platform"] != "openstreetmap" else []
        coordinates = {(round(float(item["latitude"]), 6), round(float(item["longitude"]), 6)) for item in candidates}
        if food["source_platform"] == "openstreetmap":
            pass  # Retain standalone OSM coordinates; never attach them to 780.
        elif len(coordinates) == 1:
            place = candidates[0]
            food.update(latitude=float(place["latitude"]), longitude=float(place["longitude"]), coordinate_source=json.dumps({"dataset_id": "1349", "place_id": place["id"], "source_url": place["source_url"], "source_date": place["source_date"], "join_method": "exact_name_and_full_address_after_nfkc_whitespace_normalization", "match_confidence": "high_text_match", "quality": "unverified_reference_coordinate"}, ensure_ascii=False), coordinate_match="exact_name_and_full_address", requires_ferry=int(bool(place.get("requires_ferry"))), requires_access_point=int(bool(place.get("requires_access_point"))))
            coordinate_count += 1
        else:
            food.update(latitude=None, longitude=None, coordinate_source=None, coordinate_match="ambiguous_coordinates" if len(coordinates) > 1 else "unmatched", requires_ferry=0, requires_access_point=0)
            ambiguous_count += int(len(coordinates) > 1)
        terms = _document_terms(food)
        documents.append(terms)
        frequencies.update(terms.keys())
    vocabulary = {term: index for index, term in enumerate(sorted(frequencies))}
    idf = [0.0] * len(vocabulary)
    for term, index in vocabulary.items():
        idf[index] = math.log((1 + len(foods)) / (1 + frequencies[term])) + 1
    models = root / "models_discovery"
    models.mkdir(parents=True, exist_ok=True)
    temporary = models / "discovery.building.sqlite"
    if temporary.exists():
        temporary.unlink()
    posting_count = 0
    with closing(sqlite3.connect(temporary)) as db:
        db.executescript("""PRAGMA journal_mode=OFF;PRAGMA synchronous=OFF;
            CREATE TABLE restaurants(doc_id INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,name TEXT NOT NULL,category TEXT,address TEXT,region TEXT,status TEXT,source_date TEXT,source_url TEXT,latitude REAL,longitude REAL,coordinate_source TEXT,coordinate_match TEXT,requires_ferry INTEGER,requires_access_point INTEGER,source_platform TEXT,tags_json TEXT,cuisine TEXT,snapshot_at TEXT,data_license TEXT);
            CREATE TABLE postings(term_id INTEGER NOT NULL,doc_id INTEGER NOT NULL,weight REAL NOT NULL,PRIMARY KEY(term_id,doc_id)) WITHOUT ROWID;
            CREATE INDEX food_region ON restaurants(region,name);
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);""")
        columns = ["id", "name", "category", "address", "region", "status", "source_date", "source_url", "latitude", "longitude", "coordinate_source", "coordinate_match", "requires_ferry", "requires_access_point", "source_platform", "tags_json", "cuisine", "snapshot_at", "data_license"]
        db.executemany("INSERT INTO restaurants VALUES(" + ",".join("?" for _ in range(len(columns) + 1)) + ")", [(index,) + tuple(food[key] for key in columns) for index, food in enumerate(foods)])
        for index, terms in enumerate(documents):
            values = [(vocabulary[term], (1 + math.log(count)) * idf[vocabulary[term]]) for term, count in terms.items()]
            norm = math.sqrt(sum(value * value for _, value in values)) or 1
            rows = [(term_id, index, value / norm) for term_id, value in values]
            db.executemany("INSERT INTO postings VALUES(?,?,?)", rows)
            posting_count += len(rows)
        db.executemany("INSERT INTO meta VALUES(?,?)", [("algorithm", ALGORITHM), ("version", str(VERSION)), ("source_sha256", _hash(source))])
        db.commit()
    database = root / "data_reference" / "discovery.sqlite"
    temporary.replace(database)
    model = {"schema_version": VERSION, "algorithm": ALGORITHM, "documents": len(foods), "vocabulary": vocabulary, "idf": idf, "idf_formula": "log((1+document_count)/(1+document_frequency))+1", "tf_formula": "1+log(term_count)", "normalization": "l2", "tokenization": "word_and_character_bigrams_names_categories_word_tokens_addresses_observed_cuisine", "field_weights": {"name": 3, "category": 2, "address": 1, "observed_osm_cuisine": 2}, "source_dataset_ids": ["780", "1349"] + (["OpenStreetMap"] if osm_foods else []), "source_catalog_sha256": _hash(source), "osm_source": osm_profile, "database_sha256": _hash(database), "labeled_recommendation_accuracy_evaluated": False}
    model["model_sha256"] = _digest(model)
    model_path = models / "tfidf_model.json"
    model_path.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    profile = {"status": "built", "algorithm": ALGORITHM, "training_documents": len(foods), "hub_permit_documents": hub_documents, "osm_documents": len(osm_foods), "osm_source": osm_profile, "vocabulary_terms": len(vocabulary), "postings": posting_count, "coordinates_exact_name_full_address": coordinate_count, "coordinates_standalone_osm": len(osm_foods), "coordinates_unavailable": len(foods) - coordinate_count - len(osm_foods), "ambiguous_coordinate_matches_rejected": ambiguous_count, "invalid_or_outside_jeju_place_coordinates_rejected": invalid_points, "generic_place_records_rejected": generic_places, "database_bytes": database.stat().st_size, "model_bytes": model_path.stat().st_size, "source_catalog_sha256": model["source_catalog_sha256"], "database_sha256": model["database_sha256"], "build_seconds": round(time.perf_counter() - started, 3), "rules": RULES, "cuisine_related_search_rules": CUISINE_HINTS, "limitations": ["실제 명부의 비지도 TF-IDF 표현이며 메뉴 추천 정확도를 검증한 모델이 아닙니다.", "상호·업종 문자 일치는 검색 근거이며 실제 제공 메뉴·맛·인기도·현재 영업을 확인한 근거가 아닙니다.", "780 인허가 기록의 좌표는 상호와 전체주소가 정규화 후 모두 일치하고 좌표가 하나로 정해진 1349 기록만 연결했습니다. 유사 상호·주소 근접·부분주소만으로 연결하지 않았습니다.", "OSM은 독립 공동편집 지도 기록이며 780과 동일 업소로 병합하거나 인허가 좌표를 강제로 추가하지 않았습니다. ODbL 출처와 조건을 유지합니다.", "OSM cuisine은 있는 태그만 원문 그대로 사용하며 없는 메뉴 분류를 채우지 않았습니다. 스냅샷 기준일은 개별 업소의 최신 수정일이 아닙니다.", "연결된 좌표도 원자료의 대표 위치입니다. 실제 입구와 현재 주소·운영은 검증하지 않았습니다.", "지리 거리는 직선거리이며 도로 경로·교통·도보 접근 가능성을 뜻하지 않습니다."]}
    (root / "data_reference" / "discovery_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    _load_model.cache_clear()
    return profile


@lru_cache(maxsize=4)
def _load_model(path: str, model_mtime: int, database_path: str, database_mtime: int) -> dict:
    model = json.loads(Path(path).read_text(encoding="utf-8"))
    if model.get("schema_version") != VERSION or model.get("algorithm") != ALGORITHM:
        raise ValueError("지원하지 않는 음식 검색 모델입니다. 검색 색인을 다시 만드세요.")
    vocabulary, idf = model.get("vocabulary"), model.get("idf")
    if not isinstance(vocabulary, dict) or not isinstance(idf, list) or not vocabulary or len(vocabulary) != len(idf) or set(vocabulary.values()) != set(range(len(idf))):
        raise ValueError("TF-IDF 사전과 계수 차원이 일치하지 않습니다.")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in idf):
        raise ValueError("TF-IDF 계수는 양수 유한값이어야 합니다.")
    if model.get("model_sha256") != _digest(model) or model.get("database_sha256") != _hash(database_path):
        raise ValueError("검색 모델 또는 명부의 SHA256이 일치하지 않습니다.")
    return model


def _validate(body) -> dict:
    if not isinstance(body, dict):
        raise ValueError("요청은 JSON 객체여야 합니다.")
    query = body.get("query", "")
    if not isinstance(query, str) or len(query) > 100:
        raise ValueError("query는 100자 이내 문자열이어야 합니다.")
    region = body.get("region", "all")
    if not isinstance(region, str) or region not in REGIONS:
        raise ValueError("지원하지 않는 지역입니다.")
    radius, limit = body.get("radius_km", 15), body.get("limit", 6)
    if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not 1 <= radius <= 100:
        raise ValueError("반경은 1~100km 사이 유한한 숫자여야 합니다.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 12:
        raise ValueError("검색 개수는 1~12 정수여야 합니다.")
    raw = body.get("location")
    location, state, accuracy = None, "not_provided", None
    if raw is not None:
        if not isinstance(raw, dict):
            raise ValueError("location은 위도·경도 객체 또는 null이어야 합니다.")
        values = []
        for key, lower, upper in [("latitude", -90, 90), ("longitude", -180, 180)]:
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper:
                raise ValueError("위도와 경도는 허용 범위 안의 유한한 숫자여야 합니다.")
            values.append(float(value))
        if raw.get("accuracy_m") is not None:
            accuracy = raw["accuracy_m"]
            if isinstance(accuracy, bool) or not isinstance(accuracy, (int, float)) or not 0 <= accuracy <= 100000:
                raise ValueError("위치 정확도는 0~100000m 사이 유한한 숫자여야 합니다.")
        location = _point(*values)
        state = "outside_jeju" if location is None else "low_accuracy" if accuracy is not None and accuracy > 5000 else "provided"
    return {"query": query.strip(), "region": region, "radius": float(radius), "limit": limit, "location": location, "location_status": state}


def _food_rules(query: str) -> tuple[list[str], list[str]]:
    compact = _normalized(query)
    groups = [group for group, triggers in RULE_TRIGGERS.items() if any(_normalized(value) in compact for value in triggers)]
    expanded = sorted({term for group in groups for term in RULES[group] + CUISINE_HINTS[group]})
    return groups, expanded


def _query_vector(query: str, model: dict) -> tuple[dict, list[str], list[str]]:
    groups, expanded = _food_rules(query)
    terms = Counter(_tokens(query + " " + " ".join(expanded)))
    values = {model["vocabulary"][term]: (1 + math.log(count)) * model["idf"][model["vocabulary"][term]] for term, count in terms.items() if term in model["vocabulary"]}
    norm = math.sqrt(sum(value * value for value in values.values())) or 1
    return {index: value / norm for index, value in values.items()}, groups, expanded


def _food_reference_clauses(query):
    clauses = []
    for term in _reference_terms(query):
        groups = [group for group, values in RULE_TRIGGERS.items() if term in {_normalized(v) for v in values}]
        words = tuple(_normalized(value) for group in groups for value in RULES[group])
        tags = tuple(_normalized(value) for group in groups for value in CUISINE_HINTS[group])
        clauses.append((term, words, tags))
    return clauses


def _food_reference_match(clauses, name, category, address, cuisine):
    for term, words, tags in clauses:
        if words or tags:
            match = any(word in name or word in category for word in words) or any(tag in cuisine for tag in tags)
        else:
            match = term in name or term in category or term in address or term in cuisine
        if not match:
            return False
    return bool(clauses)


def discovery_recommend(root: Path, body: dict, *, learned: bool = True) -> dict:
    started = time.perf_counter()
    root = Path(root)
    request = _validate(body)
    database, model_path = root / "data_reference" / "discovery.sqlite", root / "models_discovery" / "tfidf_model.json"
    if learned:
        model = _load_model(str(model_path.resolve()), model_path.stat().st_mtime_ns, str(database.resolve()), database.stat().st_mtime_ns)
        vector, groups, expanded = _query_vector(request["query"], model)
    else:
        model = _reference_profile(database, root / "data_reference" / "discovery_profile.json")
        groups, expanded = _food_rules(request["query"])
        vector = {}
    reference_clauses = _food_reference_clauses(request["query"]) if not learned else []
    direct_terms = sorted({term for group in groups for term in RULE_TRIGGERS[group] if _normalized(term) in _normalized(request["query"])})
    direct_terms = [term for term in direct_terms if not any(term != other and term in other for other in direct_terms)]
    scores = {}
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if vector:
            placeholders = ",".join("(?,?)" for _ in vector)
            parameters = [value for item in vector.items() for value in item]
            sql = f"WITH query_terms(term_id,weight) AS (VALUES {placeholders}) SELECT p.doc_id,SUM(p.weight*q.weight) AS score FROM postings p JOIN query_terms q ON p.term_id=q.term_id GROUP BY p.doc_id"
            scores = {row["doc_id"]: row["score"] for row in db.execute(sql, parameters)}
        sql = "SELECT * FROM restaurants" + (" WHERE region=?" if request["region"] != "all" else "")
        foods = [dict(row) for row in db.execute(sql, [request["region"]] if request["region"] != "all" else [])]
    candidates = []
    for item in foods:
        score = scores.get(item["doc_id"], 0.0)
        name_text = _normalized(item["name"])
        category_text = _normalized(item["category"])
        food_text = name_text + category_text
        cuisine_text = _normalized(item.get("cuisine"))
        rule_terms = sorted({term for group in groups for term in RULES[group] if _normalized(term) in food_text} | {term for group in groups for term in CUISINE_HINTS[group] if _normalized(term) in cuisine_text})
        if request["query"]:
            if learned and (not rule_terms if groups else score <= 0):
                continue
            if not learned and not _food_reference_match(reference_clauses, name_text, category_text,
                                                        _normalized(item.get("address")), cuisine_text):
                continue
        item.pop("doc_id")
        item["coordinate_source"] = json.loads(item["coordinate_source"]) if item["coordinate_source"] else None
        item["plan_place_id"] = item["id"] if item["source_platform"] == "openstreetmap" else item["coordinate_source"].get("place_id") if item["coordinate_source"] else None
        item["coordinate_source_url"] = item["coordinate_source"]["source_url"] if item["coordinate_source"] else None
        item["coordinate_quality"] = item["coordinate_source"]["quality"] if item["coordinate_source"] else "unavailable"
        item["tags"] = json.loads(item.pop("tags_json"))
        item["source_name"] = "OpenStreetMap" if item["source_platform"] == "openstreetmap" else "제주데이터허브 음식점 인허가 기록"
        item["attribution"] = "© OpenStreetMap contributors" if item["source_platform"] == "openstreetmap" else None
        item["copyright_url"] = "https://www.openstreetmap.org/copyright" if item["source_platform"] == "openstreetmap" else None
        item["source_date_kind"] = "osm_database_snapshot_not_individual_business_update" if item["source_platform"] == "openstreetmap" else "permit_dataset_reference_date"
        direct_name = [term for term in direct_terms if _normalized(term) in name_text]
        related_name = sorted({term for group in groups for term in RULES[group] if _normalized(term) in name_text})
        category_terms = sorted({term for group in groups for term in RULES[group] if _normalized(term) in category_text})
        direct_category = [term for group in groups if group in {"카페", "한식"} for term in direct_terms if _normalized(term) in category_text]
        item["direct_food_text_match"] = bool(direct_name or direct_category)
        if direct_name:
            tier, reason, signal = 0, "상호에 요청 음식어 " + ", ".join(direct_name) + " 직접 일치", "direct_food_name"
        elif direct_category:
            tier, reason, signal = 0, "원자료 업종에 요청 분류 " + ", ".join(sorted(set(direct_category))) + " 직접 일치", "direct_general_category"
        elif related_name:
            tier, reason, signal = 1, "상호에 연관 음식어 " + ", ".join(related_name) + " 일치", "related_food_name"
        elif category_terms:
            tier, reason, signal = 2, "원자료 업종에 연관 검색어 " + ", ".join(category_terms) + " 일치", "related_source_category"
        elif groups:
            tier, reason, signal = 3, "공동편집 cuisine 태그의 넓은 연관어 일치 · 해당 메뉴 확인 아님", "broad_observed_cuisine_tag"
        elif request["query"]:
            tier = 4
            reason, signal = ("말뭉치에서 학습한 TF-IDF 문자 관련도", "tfidf_text") if learned else ("원자료 상호·업종·주소·태그에서 검색어 확인", "source_text_match")
        else:
            tier, reason, signal = 0, "음식어 없음 · 위치가 있으면 직선거리순", "no_food_query"
        item["food_match_tier"] = tier
        item["ranking_tier"] = tier
        item["ranking_reason"] = reason
        item["ranking_signal"] = signal
        item["category_affinity_rule_match"] = any(item["category"] in CATEGORY_SUPPORT[group] + (["카페"] if group == "카페" else []) or any(_normalized(term) in cuisine_text for term in CUISINE_HINTS[group]) for group in groups)
        point = _point(item["latitude"], item["longitude"])
        distance = _distance(request["location"], point) if request["location"] is not None and point is not None else None
        if rule_terms:
            match_reason = "상호·업종·있는 경우 cuisine 태그에서 연관 검색어 " + ", ".join(rule_terms) + " 일치. 실제 메뉴 확인은 아닙니다."
        elif request["query"]:
            match_reason = "상호·업종·주소의 학습된 TF-IDF 문자 관련도입니다. 실제 메뉴 확인은 아닙니다." if learned else "원자료 상호·업종·주소·태그의 명시 일치입니다. 실제 메뉴 확인은 아닙니다."
        else:
            match_reason = "자료에 기록된 후보입니다. 메뉴·맛·현재 영업은 별도 확인이 필요합니다."
        item.update(distance_km=round(distance, 3) if distance is not None else None, within_radius=distance <= request["radius"] if distance is not None else None, similarity_score=round(score, 6) if learned else None, matched_search_terms=rule_terms, menu_verified=False, current_opening_verified=False, coordinate_verified=False, requires_ferry=bool(item["requires_ferry"]), requires_access_point=bool(item["requires_access_point"]), match_reason=match_reason, geographic_scope="within_radius_straight_line" if distance is not None and distance <= request["radius"] else "outside_radius" if distance is not None else "distance_unknown")
        candidates.append(item)
    unmapped = [item for item in candidates if item["latitude"] is None or item["longitude"] is None]
    relevance_key = lambda item: (item["food_match_tier"], -(item["similarity_score"] or 0), item["name"], item["id"])
    unmapped.sort(key=relevance_key)
    if request["location"] is not None:
        mapped = [item for item in candidates if item["within_radius"] is True]
        mapped.sort(key=lambda item: (item["food_match_tier"], item["distance_km"], -(item["similarity_score"] or 0), item["name"], item["id"]))
        result_items = mapped[:request["limit"]]
    else:
        mapped = [item for item in candidates if item["latitude"] is not None]
        mapped.sort(key=relevance_key)
        result_items = mapped[:request["limit"]]
    # The source restaurant coordinate is preferred as the sightseeing anchor.
    anchor_food = next((item for item in result_items if _point(item["latitude"], item["longitude"]) is not None), None)
    anchor = _point(anchor_food["latitude"], anchor_food["longitude"]) if anchor_food else request["location"]
    if request["location_status"] == "outside_jeju":
        anchor = None
    nearby = []
    if anchor:
        from .tourism_access import approved_places
        featured = approved_places(root)
        for item in featured:
            point = _point(item.get("latitude"), item.get("longitude"))
            if point is None or item.get("requires_ferry") or item.get("requires_access_point") or (request["region"] != "all" and item.get("region") != request["region"]):
                continue
            distance = _distance(anchor, point)
            if distance <= request["radius"]:
                nearby.append({key: item.get(key) for key in ["id", "name", "category", "region", "latitude", "longitude", "image", "source_url", "source_name", "address", "source_overlap_verified", "cross_source", "kind", "data_license", "source_platform", "description", "tourism_guide", "tourism_guide_available"]} | {"distance_km": round(distance, 3), "distance_basis": "restaurant_reference_coordinate" if anchor_food else "provided_location", "anchor_restaurant_id": anchor_food["id"] if anchor_food else None, "route_verified": False, "current_opening_verified": False})
        nearby.sort(key=lambda item: (item["distance_km"], item["name"]))
        nearby = nearby[:min(6, request["limit"])]
    warnings = ["상호·업종·주소 검색 결과이며 실제 제공 메뉴·맛·개별 점포 인기도·현재 영업을 검증하지 않았습니다.", "동의어·연관어 확장은 명시적 검색 규칙이며, TF-IDF는 실제 명부에서 학습한 비지도 문자 표현입니다. 추천 정확도를 검증한 모델은 아닙니다.", "좌표가 없는 음식점은 거리 미상으로 남겼습니다. 반경 안에 있다고 보장할 수 없습니다.", "연결된 좌표도 과거 명부와 여행장소의 상호·전체주소가 일치하는 참조 위치입니다. 실제 입구와 현재 주소는 확인이 필요합니다.", "거리는 직선거리이며 도로·도보 경로·섬 이동·교통편을 확인한 결과가 아닙니다."]
    if not learned:
        warnings[1] = "상호·업종·주소·지도 태그의 명시적 검색어 일치와 정해진 음식 연관어 규칙을 적용합니다."
    if model.get("osm_source"):
        warnings.append("OSM 공동편집 지도 기록은 인허가 명부와 별개이며 등록·운영·메뉴를 보장하지 않습니다. cuisine 태그가 없는 업소는 메뉴를 채우지 않았습니다. node는 지도점, way/relation은 경계상자 중심일 수 있습니다. © OpenStreetMap contributors · ODbL-1.0.")
    if request["location_status"] == "outside_jeju":
        warnings.insert(0, "제공 위치가 제주 범위 밖이므로 반경·근처 추천을 적용하지 않았습니다. 음식 문자 관련도 결과만 표시합니다.")
    if request["location_status"] == "low_accuracy":
        warnings.insert(0, "제공 위치의 정확도가 낮아 거리와 반경 판단에 큰 오차가 있을 수 있습니다.")
    if not result_items and not unmapped:
        warnings.append("조건에 맞는 명부를 찾지 못했습니다. 다른 음식명이나 더 넓은 지역을 선택해 주세요.")
    if learned:
        model_info = {"algorithm": ALGORITHM, "schema_version": VERSION, "training_documents": model["documents"], "vocabulary_terms": len(model["vocabulary"]), "learned_component": "corpus_document_frequency_idf_and_normalized_document_vectors", "rule_component": {"groups": groups, "direct_search_terms": direct_terms, "expanded_search_terms": expanded, "field_weights": model["field_weights"], "category_affinity_rules": {group: CATEGORY_SUPPORT[group] for group in groups}, "observed_cuisine_related_terms": {group: CUISINE_HINTS[group] for group in groups}}, "ranking": "direct_food_name_related_name_category_cuisine_tiers_then_distance_then_tfidf" if request["location"] is not None else "direct_food_name_related_name_category_cuisine_tiers_then_tfidf", "ranking_tiers": {"0": "상호 직접 음식어 또는 일반 분류 직접 일치", "1": "상호 연관 음식어", "2": "원자료 업종 연관어", "3": "공동편집 cuisine 넓은 태그", "4": "기타 TF-IDF 문자 관련도"}, "category_affinity_changes_ranking": False, "labeled_recommendation_accuracy_evaluated": False}
    else:
        model_info = {"algorithm": "verified_food_reference_lookup", "learned_component": None,
                      "source_records": model["training_documents"],
                      "rule_component": {"groups": groups, "direct_search_terms": direct_terms,
                                         "expanded_search_terms": expanded},
                      "ranking": "explicit_food_terms_then_distance_then_name"}
    return {"status": "reference_search", "query": request["query"], "region": request["region"], "radius_km": request["radius"], "location_status": request["location_status"], "restaurants": result_items, "unmapped_restaurants": unmapped[:request["limit"]], "nearby_destinations": nearby, "nearby_basis": {"type": "restaurant_reference_coordinate", "restaurant_id": anchor_food["id"], "restaurant_name": anchor_food["name"]} if anchor and anchor_food else {"type": "provided_location"} if anchor else {"type": "unavailable"}, "counts": {"food_text_matches": len(candidates), "mapped_within_radius": len(mapped) if request["location"] is not None else None, "unmapped": len(unmapped), "mapped_outside_radius": sum(item["within_radius"] is False for item in candidates), "displayed": len(result_items), "displayed_unmapped": min(len(unmapped), request["limit"])}, "model": model_info, "attributions": [{"source_platform": "openstreetmap", "text": "© OpenStreetMap contributors", "license": "ODbL-1.0", "copyright_url": "https://www.openstreetmap.org/copyright", "snapshot_at": model["osm_source"]["snapshot_at"]}] if model.get("osm_source") else [], "privacy": {"precise_location_persisted": False, "request_body_echoed": False}, "warnings": warnings, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}


def resolve_discovery_place(root: Path, ident: str) -> dict | None:
    """Resolve only immutable, server-indexed OSM IDs for itinerary planning.

    Coordinates are never accepted from a client payload. Until an OSM corpus is
    present, or for an unknown/non-OSM identifier, this safely returns None.
    """
    if not isinstance(ident, str):
        return None
    match = re.fullmatch(r"osm_(node|way|relation)_([1-9][0-9]*)", ident)
    if match is None:
        return None
    database = Path(root) / "data_reference" / "discovery.sqlite"
    if not database.is_file():
        return None
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM restaurants WHERE id=?", (ident,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    point = _point(item.get("latitude"), item.get("longitude"))
    if point is None:
        return None
    from .catalog_store import access_flags
    ferry, access = access_flags(item["name"], item["address"], point[0], point[1])
    tags = []
    if item.get("tags_json"):
        parsed = json.loads(item["tags_json"])
        tags = parsed if isinstance(parsed, list) else []
    return {"id": ident, "name": item["name"], "address": item["address"], "latitude": point[0], "longitude": point[1], "region": item["region"], "category": "지도 음식점 참조", "tags": tags, "cuisine": item.get("cuisine"), "source_name": "OpenStreetMap", "source_platform": "openstreetmap", "source_url": f"https://www.openstreetmap.org/{match.group(1)}/{match.group(2)}", "source_date": item.get("source_date"), "snapshot_at": item.get("snapshot_at"), "coordinate_quality": OSM_QUALITY, "image": None, "featured": False, "requires_ferry": ferry, "requires_access_point": access, "metadata_verified": False, "current_opening_verified": False, "menu_verified": False, "license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors"}
