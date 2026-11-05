import base64
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from jeju_agent import tourism


class TourismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = Path(__file__).resolve().parents[1] / ".test_tmp"
        scratch.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=scratch)
        cls.root = Path(cls.temp.name)
        reference = cls.root / "data_reference"
        reference.mkdir()
        featured = {"items": [{"id": "official_beach", "name": "공식해변", "category": "해변", "region": "north", "latitude": 33.5, "longitude": 126.5, "address": "제주시 해안로 1", "tags": ["유아최고"], "description": "허구편집소개", "classification_note": "편집 태그와 소개", "source_url": "https://example.test/official", "source_name": "공식 참조", "verified_on": "2026-10-26"}]}
        (reference / "destinations.json").write_text(json.dumps(featured, ensure_ascii=False), encoding="utf-8")
        common = {"coordinate_kind": "mapped_node", "source_date": "2026-10-01", "individual_edit_timestamp": "2026-10-01T01:00:00Z", "snapshot_at": "2026-10-28T12:14:10Z"}
        raw = [
            dict(common, id="osm_tourism_node_1", name="관측해변", category="해변", latitude=33.51, longitude=126.51, observed_tags={"natural": "beach"}),
            dict(common, id="osm_tourism_node_2", name="관측박물관", category="박물관", latitude=33.53, longitude=126.53, observed_tags={"tourism": "museum"}),
            dict(common, id="osm_tourism_node_3", name="숙박업소", category="숙박", latitude=33.52, longitude=126.52, observed_tags={"tourism": "hotel", "historic": "building"}),
            dict(common, id="osm_tourism_node_4", name="관측오름", category="산봉우리·오름", latitude=33.36, longitude=126.53, observed_tags={"natural": "peak"}),
            dict(common, id="osm_tourism_node_5", name="분류확인안됨", category="관광 명소", latitude=33.52, longitude=126.52, observed_tags={"name": "분류확인안됨"}),
            dict(common, id="osm_tourism_node_6", name="제주밖해변", category="해변", latitude=37.5, longitude=126.5, observed_tags={"natural": "beach"}),
            dict(common, id="osm_tourism_node_7", name="공식해변", category="해변", latitude=33.5, longitude=126.5, observed_tags={"natural": "beach"}),
        ]
        cls.write_map_sources(cls.root,raw)
        with sqlite3.connect(reference / "catalog.sqlite") as db:
            db.execute("CREATE TABLE places(id,name,address,latitude,longitude,region,source_date,source_url,requires_ferry,requires_access_point)")
            db.executemany("INSERT INTO places VALUES(?,?,?,?,?,?,?,?,?,?)", [("hub1349_cafe", "명부카페", "제주시 해안로 2", 33.49, 126.49, "north", "2025-09-18", "https://example.test/1349", 0, 0), ("hub1349_hotel", "명부호텔", "제주시 해안로 3", 33.52, 126.52, "north", "2025-09-18", "https://example.test/1349", 0, 0)])
            db.executemany("INSERT INTO places VALUES(?,?,?,?,?,?,?,?,?,?)", [("hub1349_"+str(i),name,"오염 가능 명부 주소",lat,lon,"north","2025-09-18","https://example.test/1349",0,0) for i,name,lat,lon in [(1,"관측해변",33.51,126.51),(2,"관측박물관",33.53,126.53),(4,"관측오름",33.36,126.53),(7,"공식해변",33.5,126.5)]])
        db.close()
        cls.profile = tourism.build_tourism(cls.root)

    @staticmethod
    def write_map_sources(root,rows):
        raw_folder=root/'data_raw/osm';raw_folder.mkdir(parents=True,exist_ok=True)
        elements=[{'type':'node','id':int(row['id'].rsplit('_',1)[1]),'lat':row['latitude'],'lon':row['longitude'],'tags':{'name':row['name'],**row['observed_tags']}} for row in rows]
        raw_path=raw_folder/'source.json';raw_path.write_text(json.dumps({'elements':elements},ensure_ascii=False),encoding='utf-8')
        (root/'data_reference/osm_tourism_places.json').write_text(json.dumps({'items':rows,'raw_file':'data_raw/osm/source.json','raw_sha256':hashlib.sha256(raw_path.read_bytes()).hexdigest(),'data_license':'ODbL-1.0','attribution':'© OpenStreetMap contributors','snapshot_at':'2026-10-28T12:14:10Z'},ensure_ascii=False),encoding='utf-8')
        config=root/'config';config.mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parents[1]/'config/tourism_overlap_policy.json',config/'tourism_overlap_policy.json')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def search(self, **kwargs):
        return tourism.search_tourism(self.root, kwargs)

    def test_attractions_and_unclassified_references_are_separate(self):
        attractions = self.search(limit=100)
        references = self.search(kind="reference", limit=100)
        self.assertEqual(attractions["total"], 4)
        self.assertEqual(references["total"], 0)
        self.assertEqual(self.search(kind="all", limit=100)["total"], 4)
        self.assertTrue(all(item["kind"] == "attraction" for item in attractions["items"]))
        self.assertNotIn("hub1349_hotel", [item["id"] for item in attractions["items"]])
        self.assertTrue(all(item['source_overlap_verified'] for item in attractions['items']))
        self.assertTrue(any("관광 검색에서 제공하지" in warning for warning in references["warnings"]))

    def test_observed_classifications_and_lodging_are_checked(self):
        validation = self.profile["classification_validation"]
        self.assertEqual(validation["osm_accepted"], 4)
        self.assertEqual(validation["explicit_lodging_excluded"], 1)
        self.assertEqual(validation["unrecognized_classification_excluded"], 1)
        self.assertEqual(validation["invalid_id_or_coordinate_excluded"], 1)

    def test_tfidf_uses_corpus_idf_and_excludes_editorial_training_text(self):
        model = json.loads((self.root / "models_tourism/tourism_tfidf.json").read_text(encoding="utf-8"))
        self.assertEqual(model["training_rows"], 4)
        rare = model["idf"][model["vocabulary"]["w:박물관"]]
        common = model["idf"][model["vocabulary"]["w:해변"]]
        self.assertAlmostEqual(rare, math.log(5 / 2) + 1)
        self.assertGreater(rare, common)
        self.assertNotIn("w:유아최고", model["vocabulary"])
        self.assertNotIn("w:허구편집소개", model["vocabulary"])
        self.assertEqual(self.search(query="유아최고")["total"], 0)

    def test_theme_retrieval_has_actual_model_evidence_not_popularity(self):
        result = self.search(query="바다", limit=100)
        self.assertEqual({item["id"] for item in result["items"]}, {"official_beach", "osm_tourism_node_1"})
        self.assertTrue(all(item["evidence_terms"] for item in result["items"]))
        self.assertFalse(result["model"]["predicts_popularity"])
        self.assertFalse(result["model"]["retrieval_accuracy_evaluated"])
        self.assertTrue(all("인기도" in item["score_definition"] for item in result["items"]))

    def test_bbox_region_category_and_distance_filtering(self):
        box = self.search(bbox=[126.499, 33.499, 126.515, 33.515], category="해변", region="north", limit=100)
        self.assertEqual(box["total"], 2)
        result = self.search(location={"latitude": 33.509, "longitude": 126.509}, limit=100)
        distances = [item["distance_km"] for item in result["items"]]
        self.assertEqual(distances, sorted(distances))
        self.assertEqual(result["items"][0]["id"], "osm_tourism_node_1")
        outside = self.search(location={"latitude": 37.5, "longitude": 127.0})
        self.assertEqual(outside["location_status"], "outside_jeju")
        self.assertTrue(all(item["distance_km"] is None for item in outside["items"]))

    def test_cursor_pagination_is_stable_and_contains_no_location(self):
        request = {"limit": 2, "location": {"latitude": 33.512345678, "longitude": 126.512345678}}
        first = tourism.search_tourism(self.root, request)
        second = tourism.search_tourism(self.root, dict(request, cursor=first["next_cursor"]))
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(len(second["items"]), 2)
        self.assertFalse(second["has_more"])
        self.assertFalse({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})
        decoded = base64.urlsafe_b64decode(first["next_cursor"] + "=" * (-len(first["next_cursor"]) % 4)).decode()
        self.assertNotIn("latitude", decoded)
        self.assertNotIn("33.512345678", decoded)
        self.assertNotIn("33.512345678", json.dumps(first))

    def test_search_does_not_persist_precise_location(self):
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.root.rglob("*") if path.is_file()}
        self.search(query="해변", location={"latitude": 33.512345678, "longitude": 126.512345678})
        after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_invalid_inputs_and_cursors_are_rejected(self):
        invalid = [{"limit": 101}, {"limit": 3.2}, {"offset": -1}, {"bbox": [126, 34, 127, 33]}, {"bbox": [float("nan"), 33, 127, 34]}, {"location": {"latitude": 91, "longitude": 126}}, {"location": {"latitude": 33.5, "longitude": float("inf")}}, {"region": "seoul"}, {"kind": "food"}, {"cursor": "not-a-valid-cursor"}, {"query": ["해변"]}, {"radius_km": 0.9}, {"radius_km": 101}, {"radius_km": float("inf")}, {"radius_km": float("nan")}, {"radius_km": True}]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(ValueError):
                tourism.search_tourism(self.root, body)

    def test_radius_boundary_and_half_radius_filter_on_unrounded_distance(self):
        origin = {"latitude": 33.5, "longitude": 126.5}
        distance = tourism._distance((33.5, 126.5), (33.53, 126.53))
        boundary = self.search(category="박물관", location=origin, radius_km=distance)
        half = self.search(category="박물관", location=origin, radius_km=distance / 2)
        self.assertEqual(boundary["total"], 1)
        self.assertEqual(half["total"], 0)
        self.assertTrue(boundary["radius_applied"])
        self.assertEqual(boundary["distance_basis"], "provided_location_straight_line")
        self.assertFalse(self.search(location=origin)["radius_applied"])

    def test_radius_without_jeju_location_is_explicitly_unapplied(self):
        missing = self.search(radius_km=1)
        outside = self.search(radius_km=1, location={"latitude": 37.5, "longitude": 127.0})
        for result in [missing, outside]:
            self.assertFalse(result["radius_applied"])
            self.assertEqual(result["radius_km"], 1)
            self.assertEqual(result["total"], 4)
            self.assertTrue(all(item["distance_km"] is None for item in result["items"]))
            self.assertTrue(any("반경" in warning for warning in result["warnings"]))

    def test_immutable_resolver_and_conservative_access_flags(self):
        peak = tourism.resolve_tourism_place(self.root, "osm_tourism_node_4")
        self.assertTrue(peak["requires_access_point"])
        self.assertEqual(peak["source_url"], "https://www.openstreetmap.org/node/4")
        self.assertIsNone(tourism.resolve_tourism_place(self.root, {"id": "osm_tourism_node_4", "latitude": 33.5}))
        self.assertIsNone(tourism.resolve_tourism_place(self.root, "unknown' OR 1=1"))

    def test_food_tag_hidden_from_normalized_record_is_checked_from_raw_source(self):
        alternate = self.root / "theme_ranking"
        reference = alternate / "data_reference"
        reference.mkdir(parents=True)
        rows=[{'id':'osm_tourism_node_1','name':'관측해변','latitude':33.5,'longitude':126.5,'category':'해변','observed_tags':{'natural':'beach'}},{'id':'osm_tourism_node_2','name':'바다다 카페','latitude':33.501,'longitude':126.501,'category':'관광 명소','observed_tags':{'tourism':'attraction','amenity':'cafe'}}]
        self.write_map_sources(alternate,rows)
        # Simulate the old normalized format dropping the critical amenity tag.
        normalized_path=reference/'osm_tourism_places.json';normalized=json.loads(normalized_path.read_text(encoding='utf-8'));normalized['items'][1]['observed_tags'].pop('amenity');normalized_path.write_text(json.dumps(normalized,ensure_ascii=False),encoding='utf-8')
        with sqlite3.connect(reference/'catalog.sqlite') as db:
            db.execute('CREATE TABLE places(id,name,address,latitude,longitude,region,source_date,source_url,requires_ferry,requires_access_point)')
            db.executemany('INSERT INTO places VALUES(?,?,?,?,?,?,?,?,?,?)',[("hub1349_"+str(i),row['name'],'',row['latitude'],row['longitude'],'north','','https://example.test/hub',0,0) for i,row in enumerate(rows)])
        db.close()
        tourism.build_tourism(alternate)
        result = tourism.search_tourism(alternate, {"query": "바다"})
        self.assertEqual([item["id"] for item in result["items"]], ["osm_tourism_node_1"])
        self.assertTrue(result["items"][0]["theme_classification_match"])

    def test_model_cards_preserve_original_selected_metrics(self):
        audience_path = self.root / "models_audience"
        mobility_path = self.root / "models_mobility"
        audience_path.mkdir()
        mobility_path.mkdir()
        audience = {"algorithm": "candidate_algorithm", "source": {"aggregate_cells": 1440}, "selection": {"selected": "audience_mean"}, "test": {"model": {"mae_share": 0.25}, "baseline": {"mae_share": 0.125}}}
        mobility = {"algorithm": "ridge_algorithm", "selection": {"selected_rows": 4704}, "serving_selection": {"selected_serving_model": "weekday_bucket_mean"}, "test": {"model": {"mae_per_hour": 10.5}, "baseline": {"mae_per_hour": 8.25}}}
        (audience_path / "audience_metrics.json").write_text(json.dumps(audience), encoding="utf-8")
        (mobility_path / "mobility_metrics.json").write_text(json.dumps(mobility), encoding="utf-8")
        cards = {card["id"]: card for card in tourism.get_model_info(self.root)["cards"]}
        self.assertEqual(cards["audience_distribution"]["selected_test_metrics"]["mae_share"], 0.125)
        self.assertEqual(cards["audience_distribution"]["test"]["model"]["mae_share"], 0.25)
        self.assertEqual(cards["mobility_pattern"]["selected_test_metrics"]["mae_per_hour"], 8.25)
        self.assertEqual(cards["mobility_pattern"]["test"]["model"]["mae_per_hour"], 10.5)
        self.assertEqual(cards["tourism_tfidf"]["training_rows"], 4)


if __name__ == "__main__":
    unittest.main()
