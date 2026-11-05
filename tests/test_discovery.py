import json
import math
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest

from jeju_agent import discovery


class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = Path(__file__).resolve().parents[1] / ".test_tmp"
        scratch.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=scratch)
        cls.root = Path(cls.temp.name)
        reference = cls.root / "data_reference"
        reference.mkdir()
        foods = [
            ("f1", "흑돼지 가까운집", "한식", "제주시 해안로 1", "north", "자료상정상", "2025-09-02", "https://example.test/780"),
            ("f2", "흑돼지 먼집", "한식", "제주시 해안로 2", "north", "자료상정상", "2025-09-02", "https://example.test/780"),
            ("f3", "흑돼지 좌표없음", "한식", "제주시 해안로 3", "north", "자료상정상", "2025-09-02", "https://example.test/780"),
            ("f4", "가까운 카페", "커피숍", "제주시 해안로 4", "north", "자료상정상", "2025-09-02", "https://example.test/780"),
            ("f5", "바다 횟집", "횟집", "제주시 해안로 5", "north", "자료상정상", "2025-09-02", "https://example.test/780"),
            ("f6", "갈치 모호한집", "한식", "제주시 해안로 6", "north", "자료상정상", "2025-09-02", "https://example.test/780"),
            ("f7", "생선구이", "한식", "제주시 해안로 7", "north", "자료상정상", "2025-09-02", "https://example.test/780"),
        ]
        places = [
            ("p1", foods[0][1], foods[0][3], 33.501, 126.501, "2025-09-18", "https://example.test/1349", 0, 0),
            ("p2", foods[1][1], foods[1][3], 33.52, 126.52, "2025-09-18", "https://example.test/1349", 0, 0),
            ("p3", foods[2][1], "제주시 해안로 33", 33.501, 126.501, "2025-09-18", "https://example.test/1349", 0, 0),
            ("p4", foods[3][1], foods[3][3], 33.5001, 126.5001, "2025-09-18", "https://example.test/1349", 0, 0),
            ("p5", "바다횟집", foods[4][3], 33.502, 126.502, "2025-09-18", "https://example.test/1349", 0, 0),
            ("p6", foods[5][1], foods[5][3], 33.501, 126.501, "2025-09-18", "https://example.test/1349", 0, 0),
            ("p7", foods[5][1], foods[5][3], 33.6, 126.6, "2025-09-18", "https://example.test/1349", 0, 0),
            ("p8", "잘못된위치", "제주시 위도길 1", 37.5, 127, "2025-09-18", "https://example.test/1349", 0, 0),
        ]
        with sqlite3.connect(reference / "catalog.sqlite") as db:
            db.execute("CREATE TABLE restaurants(id,name,category,address,region,status,source_date,source_url)")
            db.execute("CREATE TABLE places(id,name,address,latitude,longitude,source_date,source_url,requires_ferry,requires_access_point)")
            db.executemany("INSERT INTO restaurants VALUES(?,?,?,?,?,?,?,?)", foods)
            db.executemany("INSERT INTO places VALUES(?,?,?,?,?,?,?,?,?)", places)
        db.close()
        featured = {"items": [{"id": "s1", "name": "참조 해변", "category": "nature", "region": "north", "latitude": 33.503, "longitude": 126.503, "image": None, "source_url": "https://example.test/tourism", "source_name": "공식 참조", "address": "제주시 해안길"}]}
        (reference / "destinations.json").write_text(json.dumps(featured, ensure_ascii=False), encoding="utf-8")
        from jeju_agent.tourism_overlap import POLICY_ID
        with sqlite3.connect(reference / 'tourism.sqlite') as db:
            db.execute('CREATE TABLE places(id TEXT,kind TEXT,data_json TEXT)')
            for p in featured['items']:
                fixture=dict(p,kind='attraction',source_overlap_verified=True,cross_source={'policy_id':POLICY_ID,'match_method':'normalized_exact_name_and_distance','distance_m':0,'hub':{'id':'hub_'+p['id']},'osm':{'id':'osm_'+p['id']}})
                db.execute('INSERT INTO places VALUES(?,?,?)',(p['id'],'attraction',json.dumps(fixture)))
        db.close()
        cls.profile = discovery.build_discovery(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def recommend(self, **kwargs):
        body = {"query": "흑돼지", "location": {"latitude": 33.5, "longitude": 126.5}, "radius_km": 15, "limit": 6, "region": "all"}
        body.update(kwargs)
        return discovery.discovery_recommend(self.root, body)

    def test_tfidf_is_fitted_on_corpus_document_frequencies(self):
        model = json.loads((self.root / "models_discovery/tfidf_model.json").read_text(encoding="utf-8"))
        self.assertEqual(model["documents"], 7)
        rare = model["idf"][model["vocabulary"]["w:커피숍"]]
        common = model["idf"][model["vocabulary"]["w:한식"]]
        self.assertAlmostEqual(rare, math.log(8 / 2) + 1)
        self.assertGreater(rare, common)
        self.assertFalse(model["labeled_recommendation_accuracy_evaluated"])

    def test_food_filter_precedes_distance_and_unmapped_is_preserved(self):
        result = self.recommend()
        ids = [item["id"] for item in result["restaurants"]]
        self.assertEqual(ids[:2], ["f1", "f2"])
        self.assertNotIn("f4", ids)  # Closer cafe is not a pork match.
        self.assertNotIn("f3", ids)
        self.assertIsNone(next(item for item in result["unmapped_restaurants"] if item["id"] == "f3")["distance_km"])
        self.assertEqual(result["unmapped_restaurants"][0]["id"], "f3")
        self.assertTrue(result["nearby_destinations"])

    def test_partial_address_or_ambiguous_coordinates_never_join(self):
        with sqlite3.connect(self.root / "data_reference/discovery.sqlite") as db:
            partial = db.execute("SELECT latitude,coordinate_match FROM restaurants WHERE id='f3'").fetchone()
            ambiguous = db.execute("SELECT latitude,coordinate_match FROM restaurants WHERE id='f6'").fetchone()
        db.close()
        self.assertIsNone(partial[0])
        self.assertEqual(partial[1], "unmatched")
        self.assertIsNone(ambiguous[0])
        self.assertEqual(ambiguous[1], "ambiguous_coordinates")
        self.assertEqual(self.profile["ambiguous_coordinate_matches_rejected"], 1)
        self.assertEqual(self.profile["invalid_or_outside_jeju_place_coordinates_rejected"], 1)

    def test_exact_whitespace_normalization_records_provenance(self):
        result = self.recommend(query="해산물")
        item = next(item for item in result["restaurants"] if item["id"] == "f5")
        self.assertIsNotNone(item["latitude"])
        self.assertEqual(item["coordinate_source"]["dataset_id"], "1349")
        self.assertEqual(item["coordinate_source"]["match_confidence"], "high_text_match")
        self.assertEqual(item["plan_place_id"], "p5")
        self.assertEqual(item["coordinate_source_url"], "https://example.test/1349")
        self.assertEqual(item["coordinate_quality"], "unverified_reference_coordinate")
        self.assertFalse(item["menu_verified"])
        self.assertFalse(item["coordinate_verified"])

    def test_radius_excludes_known_far_points_but_not_unknown_distances(self):
        result = self.recommend(radius_km=1)
        ids = [item["id"] for item in result["restaurants"]]
        self.assertIn("f1", ids)
        self.assertNotIn("f2", ids)
        self.assertIn("f3", [item["id"] for item in result["unmapped_restaurants"]])
        self.assertGreaterEqual(result["counts"]["mapped_outside_radius"], 1)

    def test_outside_jeju_location_is_not_presented_as_nearby(self):
        result = self.recommend(location={"latitude": 37.5665, "longitude": 126.978})
        self.assertEqual(result["location_status"], "outside_jeju")
        self.assertTrue(all(item["distance_km"] is None for item in result["restaurants"]))
        self.assertEqual(result["nearby_destinations"], [])
        self.assertTrue(any("제주 범위 밖" in warning for warning in result["warnings"]))

    def test_location_is_not_echoed_or_persisted(self):
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result = self.recommend(location={"latitude": 33.512345678, "longitude": 126.512345678, "accuracy_m": 25})
        self.assertNotIn("33.512345678", json.dumps(result))
        self.assertNotIn("126.512345678", json.dumps(result))
        self.assertFalse(result["privacy"]["precise_location_persisted"])
        after = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_invalid_inputs_rejected(self):
        invalid = [{"location": {"latitude": float("nan"), "longitude": 126.5}}, {"location": {"latitude": 91, "longitude": 126.5}}, {"location": {"latitude": 33.5}}, {"location": {"latitude": 33.5, "longitude": 126.5, "accuracy_m": -1}}, {"radius_km": 0}, {"radius_km": float("inf")}, {"limit": 1.5}, {"limit": 13}, {"region": "seoul"}, {"query": ["흑돼지"]}]
        for override in invalid:
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.recommend(**override)

    def test_empty_query_sorts_confirmed_coordinates_by_distance(self):
        result = self.recommend(query="", radius_km=15)
        known = [item for item in result["restaurants"] if item["distance_km"] is not None]
        self.assertEqual(known[0]["id"], "f4")
        self.assertEqual([item["distance_km"] for item in known], sorted(item["distance_km"] for item in known))

    def test_unknown_query_does_not_invent_recommendations(self):
        result = self.recommend(query="ㅁㄴㅇㄹㅂㅈㄷㄱ")
        self.assertEqual(result["restaurants"], [])

    def test_literal_food_name_precedes_broader_related_search_words(self):
        result = self.recommend(query="갈치", location=None)
        ids = [item["id"] for item in result["unmapped_restaurants"]]
        self.assertLess(ids.index("f6"), ids.index("f7"))
        self.assertTrue(result["unmapped_restaurants"][0]["direct_food_text_match"])

    def test_resolver_rejects_non_osm_unknown_and_coordinate_payloads(self):
        for value in ["f1", "osm_node_999999", "osm_way_1 OR 1=1", {"id": "osm_node_1", "latitude": 33.5, "longitude": 126.5}, None]:
            with self.subTest(value=value):
                self.assertIsNone(discovery.resolve_discovery_place(self.root, value))

    def test_osm_is_standalone_with_missing_cuisine_preserved_and_safe_resolver(self):
        alternate = self.root / "osm_case"
        reference = alternate / "data_reference"
        reference.mkdir(parents=True)
        shutil.copyfile(self.root / "data_reference/catalog.sqlite", reference / "catalog.sqlite")
        shutil.copyfile(self.root / "data_reference/destinations.json", reference / "destinations.json")
        snapshot = "2026-10-28T10:47:02Z"
        osm = {"data_license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors", "snapshot_at": snapshot, "items": [
            {"id": "osm_node_100", "name": "흑돼지 지도식당", "latitude": 33.5005, "longitude": 126.5005, "coordinate_kind": "mapped_node", "amenity": "restaurant", "category": "음식점", "cuisine": None, "address": None, "source_date": "2026-10-28"},
            {"id": "osm_way_101", "name": "해안카페", "latitude": 33.504, "longitude": 126.504, "coordinate_kind": "element_bbox_center", "amenity": "cafe", "category": "카페", "cuisine": "coffee_shop", "address": None, "source_date": "2026-10-28"},
            {"id": "osm_node_102", "name": "제주의 오후", "latitude": 33.505, "longitude": 126.505, "coordinate_kind": "mapped_node", "amenity": "restaurant", "category": "음식점", "cuisine": "korean", "address": None, "source_date": "2026-10-28"},
            {"id": "osm_node_103", "name": "우도음식점", "latitude": 33.508, "longitude": 126.958, "coordinate_kind": "mapped_node", "amenity": "restaurant", "category": "음식점", "cuisine": None, "address": None, "source_date": "2026-10-28"},
        ]}
        (reference / "osm_food_places.json").write_text(json.dumps(osm, ensure_ascii=False), encoding="utf-8")
        profile = discovery.build_discovery(alternate)
        self.assertEqual(profile["osm_documents"], 4)
        self.assertEqual(profile["coordinates_exact_name_full_address"], self.profile["coordinates_exact_name_full_address"])
        result = discovery.discovery_recommend(alternate, {"query": "흑돼지", "location": {"latitude": 33.5, "longitude": 126.5}, "radius_km": 5, "limit": 6})
        item = next(item for item in result["restaurants"] if item["id"] == "osm_node_100")
        self.assertEqual(item["source_platform"], "openstreetmap")
        self.assertIsNone(item["cuisine"])
        self.assertEqual(item["address"], "")
        self.assertEqual(item["plan_place_id"], "osm_node_100")
        self.assertFalse(item["menu_verified"])
        self.assertEqual(item["snapshot_at"], snapshot)
        self.assertEqual(result["attributions"][0]["license"], "ODbL-1.0")
        resolved = discovery.resolve_discovery_place(alternate, item["plan_place_id"])
        self.assertEqual(resolved["source_url"], "https://www.openstreetmap.org/node/100")
        self.assertEqual(resolved["latitude"], 33.5005)
        self.assertTrue(discovery.resolve_discovery_place(alternate, "osm_node_103")["requires_ferry"])
        korean = discovery.discovery_recommend(alternate, {"query": "한식", "limit": 12})
        self.assertIn("osm_node_102", [item["id"] for item in korean["restaurants"]])

    def test_noodles_cuisine_cannot_jump_ahead_of_related_noodle_names(self):
        alternate = self.root / "ranking_case"
        reference = alternate / "data_reference"
        reference.mkdir(parents=True)
        shutil.copyfile(self.root / "data_reference/catalog.sqlite", reference / "catalog.sqlite")
        records = [("osm_node_200", "직접 고기국수", 33.55, 126.55, None), ("osm_node_201", "고국수", 33.501, 126.501, None), ("osm_node_202", "올래국수", 33.502, 126.502, None), ("osm_node_203", "곶자왈손칼국수", 33.59, 126.59, "noodles"), ("osm_node_204", "Blue Saigon", 33.503, 126.503, "noodles")]
        osm = {"data_license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors", "snapshot_at": "2026-10-28T10:47:02Z", "items": [{"id": ident, "name": name, "latitude": lat, "longitude": lon, "coordinate_kind": "mapped_node", "amenity": "restaurant", "category": "음식점", "cuisine": cuisine, "address": None, "source_date": "2026-10-28"} for ident, name, lat, lon, cuisine in records]}
        (reference / "osm_food_places.json").write_text(json.dumps(osm, ensure_ascii=False), encoding="utf-8")
        discovery.build_discovery(alternate)
        request = {"query": "고기국수", "location": {"latitude": 33.5, "longitude": 126.5}, "radius_km": 20, "limit": 12}
        result = discovery.discovery_recommend(alternate, request)
        items = result["restaurants"]
        self.assertEqual([item["id"] for item in items], [row[0] for row in records])
        self.assertEqual([item["ranking_tier"] for item in items], [0, 1, 1, 1, 3])
        related = [item["distance_km"] for item in items if item["ranking_tier"] == 1]
        self.assertEqual(related, sorted(related))
        self.assertEqual(items[-1]["ranking_signal"], "broad_observed_cuisine_tag")
        self.assertFalse(result["model"]["category_affinity_changes_ranking"])
        without_location = discovery.discovery_recommend(alternate, dict(request, location=None))
        ids = [item["id"] for item in without_location["restaurants"]]
        self.assertEqual(ids[0], "osm_node_200")
        self.assertGreater(ids.index("osm_node_204"), ids.index("osm_node_203"))


if __name__ == "__main__":
    unittest.main()
