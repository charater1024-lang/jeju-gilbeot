from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import shutil

from jeju_agent.route_demand import _eligible, _features, _load, _metrics, _window, fit, get_route_demand, list_route_options, predict, read_observations, write_artifact_integrity

ROOT = Path(__file__).resolve().parents[1]


class RouteDemandTests(unittest.TestCase):
    def test_duplicate_missing_invalid_and_virtual_cells(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.csv"
            header = "base_date,act_type,bus_number,user_type,user_count\n"
            path.write_text(header + "20250101,승차,101-1,일반,20\n20250103,승차,101-1,일반,30\n20250103,승차,가상정류소,일반,99\n20250103,하차,101-1,일반,15\n", encoding="utf-8")
            rows, audit = read_observations(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(audit["raw_missing_dates"], 1)
            self.assertEqual(audit["missing_cells_imputed"], 0)
            with path.open("a", encoding="utf-8") as handle:
                handle.write("20250103,승차,101-1,일반,30\n")
            with self.assertRaisesRegex(ValueError, "중복"):
                read_observations(path)
            path.write_text(header + "20250101,승차,101-1,일반,-1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_observations(path)

    def test_eligibility_uses_only_fit_cutoff_and_no_zero_fill(self):
        end = dt.date(2025, 1, 1)
        rows = [{"date": (end - dt.timedelta(days=i)).isoformat(), "route_id": "101-1", "count": 10} for i in range(180)]
        rows += [{"date": (end + dt.timedelta(days=i + 1)).isoformat(), "route_id": "999-1", "count": 100} for i in range(180)]
        self.assertEqual(_eligible(rows, end), ["101-1"])
        self.assertEqual(len(_window(rows, end, ["101-1"])), 180)

    def test_calendar_recovers_weekday_signal(self):
        first = dt.date(2024, 1, 1)
        rows = []
        for i in range(365):
            day = first + dt.timedelta(days=i)
            rows.append({"date": day.isoformat(), "route_id": "101-1", "count": 30 if day.weekday() >= 5 else 100})
        model = fit(rows, {"family": "calendar_ridge", "half_life_days": 180, "alpha": 0.01, "harmonics": 2})
        self.assertGreater(predict(model, "101-1", dt.date(2025, 1, 6)), predict(model, "101-1", dt.date(2025, 1, 5)) + 50)
        self.assertEqual(len(_features(first)), 13)
        with self.assertRaises(ValueError):
            predict(model, "999-1", first)

    def test_tolerance_denominator_excludes_zero(self):
        result = _metrics([0, 10, 100], [2, 12, 150])
        self.assertEqual(result["within_20_percent"]["hits"], 1)
        self.assertEqual(result["within_20_percent"]["denominator"], 2)
        self.assertEqual(result["within_20_percent"]["excluded_zero_actual"], 1)
        self.assertEqual(result["within_20_percent"]["percent"], 50)

    def test_shipped_model_lineage_temporal_split_and_metrics(self):
        folder = ROOT / "models_route_demand"
        report = json.loads((folder / "route_demand_metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(report["data_mode"], "observed_real_data")
        self.assertFalse(report["selection"]["test_used_for_selection"])
        self.assertLess(report["split"]["train"]["end"], report["split"]["validation"]["start"])
        self.assertLess(report["split"]["validation"]["end"], report["split"]["test"]["start"])
        self.assertEqual(report["audit"]["missing_cells_imputed"], 0)
        self.assertEqual(report["audit"]["raw_rows"], 14127952)
        self.assertEqual(report["test"]["selected"]["observations"], report["test"]["baseline"]["observations"])

    def test_service_pattern_identity_and_input_validation(self):
        result = get_route_demand(ROOT, date="2026-11-04", limit=2)
        self.assertEqual(result["estimate_type"], "historical_calendar_pattern")
        self.assertEqual(len(result["items"]), 2)
        self.assertFalse(result["runtime_llm"])
        self.assertEqual(result["metrics"]["evaluation_route_count"], 250)
        self.assertEqual(result["metrics"]["serving_route_count"], 202)
        self.assertLess(result["metrics"]["evaluated_cell_coverage_percent"], 100)
        first = result["items"][0]
        self.assertFalse(first["current_route_mapping_verified"])
        self.assertGreaterEqual(first["prediction"], 0)
        exact = get_route_demand(ROOT, route=first["route_id"], date="2026-11-04")
        self.assertEqual(exact["items"][0]["prediction"], first["prediction"])
        self.assertTrue(list_route_options(ROOT, 2))
        for bad in ("abc", "가상정류소", "101;", 100):
            with self.assertRaises(ValueError):
                get_route_demand(ROOT, route=bad)
        for bad in (True, 0, 51, "8"):
            with self.assertRaises(ValueError):
                get_route_demand(ROOT, limit=bad)
        for bad in ("2025-02-30", 20250101, "hello"):
            with self.assertRaises(ValueError):
                get_route_demand(ROOT, date=bad)

    def test_corrupt_model_and_invalid_coefficients_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "models_route_demand"
            target.mkdir()
            for name in ("route_demand_model.json", "route_demand_metrics.json", "selection_freeze.json", "artifact_integrity.json"):
                shutil.copyfile(ROOT / "models_route_demand" / name, target / name)
            _load(root)
            path = target / "route_demand_model.json"
            model = json.loads(path.read_text(encoding="utf-8"))
            key = next(iter(model["routes"]))
            model["routes"][key]["weekday_means"][0] = 999
            path.write_text(json.dumps(model), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "무결성"):
                _load(root)
            # Even a matching digest cannot make invalid numeric dimensions valid.
            model["routes"][key]["weekday_means"] = [float("nan")]
            path.write_text(json.dumps(model), encoding="utf-8")
            write_artifact_integrity(target)
            with self.assertRaisesRegex(ValueError, "차원"):
                _load(root)


if __name__ == "__main__":
    unittest.main()
