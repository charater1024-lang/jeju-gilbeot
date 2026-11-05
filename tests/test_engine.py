from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jeju_agent import engine
from scripts.generate_demo import generate


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp_root = Path(__file__).resolve().parents[1] / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=temp_root)
        cls.root = Path(cls.temp.name)
        cls.data = cls.root / "data"
        generate(cls.data)
        cls.models = cls.root / "models"
        cls.metrics = engine.train(cls.data, cls.models)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def request(self, **overrides):
        request = {"date": "2026-10-27", "transport": "car", "start_lat": 33.506, "start_lon": 126.492, "end_lat": 33.506, "end_lon": 126.492, "start_minute": 540, "end_minute": 1080, "budget_krw": 80000, "interests": ["food", "nature"], "avoid_crowds": False, "max_stops": 5}
        request.update(overrides)
        return request

    def rec(self, **overrides):
        return engine.recommend(self.data, self.models / "model.json", self.request(**overrides))

    def test_model_is_fitted_and_evaluated_on_later_dates(self):
        model = json.loads((self.models / "model.json").read_text(encoding="utf-8"))
        self.assertTrue(any(abs(weight) > 0.01 for weight in model["weights"]))
        split = self.metrics["split"]
        self.assertLess(split["train_end"], split["validation_start"])
        self.assertEqual(split["validation_end"], "2026-10-25")
        self.assertEqual(self.metrics["data_mode"], "synthetic")
        self.assertGreater(self.metrics["model"]["n"], 0)

    def test_fit_never_receives_holdout_rows_during_evaluation(self):
        calls = []
        real_fit = engine._fit

        def spy(rows, *args, **kwargs):
            calls.append((min(row["date"] for row in rows), max(row["date"] for row in rows)))
            return real_fit(rows, *args, **kwargs)

        with mock.patch.object(engine, "_fit", side_effect=spy):
            metrics = engine.train(self.data, self.root / "audit_models")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], metrics["split"]["train_end"])
        self.assertLess(calls[0][1], metrics["split"]["validation_start"])
        self.assertEqual(calls[1][1], "2026-10-25")

    def test_route_obeys_budget_time_opening_and_return_leg(self):
        result = self.rec(budget_krw=42000, end_minute=990)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["stops"])
        total = result["totals"]
        self.assertLessEqual(total["cost_krw"], 42000)
        self.assertLessEqual(total["end_arrival_minute"], 990)
        self.assertEqual(total["end_arrival_minute"], result["stops"][-1]["departure_minute"] + total["return_travel_minutes"])
        self.assertEqual(total["cost_krw"], sum(stop["cost_krw"] + stop["travel_cost_krw"] for stop in result["stops"]) + total["return_travel_cost_krw"])
        pois, _, _ = engine.load_data(self.data)
        lookup = {poi["poi_id"]: poi for poi in pois}
        for stop in result["stops"]:
            self.assertGreaterEqual(stop["arrival_minute"], lookup[stop["poi_id"]]["open_minute"])
            self.assertLessEqual(stop["departure_minute"], lookup[stop["poi_id"]]["close_minute"])
        self.assertEqual(len(result["trace"]), 6)

    def test_unreachable_endpoint_prevents_fake_feasible_route(self):
        result = self.rec(end_lat=37.5665, end_lon=126.978, end_minute=560)
        self.assertEqual(result["status"], "infeasible")
        self.assertEqual(result["stops"], [])

    def test_bus_refuses_without_timetable(self):
        result = self.rec(transport="bus")
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["stops"], [])
        self.assertEqual(result["trace"][-2]["status"], "unsupported")

    def test_historical_request_rejected_to_prevent_future_leak(self):
        with self.assertRaisesRegex(ValueError, "미래 정보"):
            self.rec(date="2026-10-24")

    def test_invalid_requests_are_rejected(self):
        invalid = [{"budget_krw": -1}, {"end_minute": 500}, {"transport": "plane"}, {"start_lat": float("nan")}, {"max_stops": 3.2}, {"interests": "food"}, {"avoid_crowds": "false"}, {"date": "2026-02-30"}]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.rec(**overrides)

    def test_crowd_option_changes_learned_direction(self):
        popular = self.rec(max_stops=1)
        quiet = self.rec(max_stops=1, avoid_crowds=True)
        self.assertEqual(popular["status"], "ok")
        self.assertEqual(quiet["status"], "ok")
        self.assertGreater(popular["stops"][0]["predicted_visits"], quiet["stops"][0]["predicted_visits"])

    def test_unknown_poi_can_use_cold_start_and_is_disclosed(self):
        alternate = self.root / "cold_start"
        alternate.mkdir(exist_ok=True)
        for name in ["demand.csv", "demo_metadata.json"]:
            (alternate / name).write_bytes((self.data / name).read_bytes())
        with (self.data / "pois.csv").open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        extra = dict(rows[0], poi_id="COLD_START_TEST", name="[가상] 미학습 장소")
        rows.append(extra)
        with (alternate / "pois.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        # A cold-start POI must be present at fitting time, with no own history.
        # Changed input files always require a fresh model and new fingerprints.
        alternate_models = self.root / "cold_start_models"
        engine.train(alternate, alternate_models)
        result = engine.recommend(alternate, alternate_models / "model.json", self.request())
        self.assertTrue(any("학습 이력이 없는 장소" in warning for warning in result["warnings"]))

    def test_changed_data_requires_retraining(self):
        alternate = self.root / "changed_data"
        alternate.mkdir(exist_ok=True)
        for name in ["pois.csv", "demand.csv", "demo_metadata.json"]:
            (alternate / name).write_bytes((self.data / name).read_bytes())
        with (alternate / "pois.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            engine.recommend(alternate, self.models / "model.json", self.request())

    def test_new_demand_after_model_cutoff_requires_retraining(self):
        alternate = self.root / "updated_demand"
        alternate.mkdir(exist_ok=True)
        for name in ["pois.csv", "demand.csv", "demo_metadata.json"]:
            (alternate / name).write_bytes((self.data / name).read_bytes())
        with (alternate / "demand.csv").open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["2026-10-26", "DEMO001", 1, "SYNTHETIC_DEMAND_V1"])
        with self.assertRaisesRegex(ValueError, "학습 종료일 이후"):
            engine.recommend(alternate, self.models / "model.json", self.request())

    def test_invalid_model_dimensions_and_nonfinite_weights_are_rejected(self):
        original = json.loads((self.models / "model.json").read_text(encoding="utf-8"))
        for label, replacement in [("dimension", original["weights"][:-1]), ("nan", [float("nan")] + original["weights"][1:]), ("infinity", [float("inf")] + original["weights"][1:])]:
            with self.subTest(label=label):
                invalid_model = dict(original, weights=replacement)
                path = self.root / f"invalid_model_{label}.json"
                path.write_text(json.dumps(invalid_model), encoding="utf-8")
                with self.assertRaises(ValueError):
                    engine.recommend(self.data, path, self.request())

    def test_walking_has_no_vehicle_cost(self):
        result = self.rec(transport="walk", max_stops=2, end_minute=1200)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["totals"]["travel_cost_krw"], 0)


if __name__ == "__main__":
    unittest.main()
