"""Grounded serving, temporal evaluation, and fail-closed model integrity."""
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from jeju_agent.dining_model import (
    ALGORITHM, EXCLUDED_PARENTS, _hash, _load_model, predict_dining, read_panels, train_dining,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data_raw/hub/hub_1047_5831.csv"


class DiningModelTests(unittest.TestCase):
    def test_actual_source_and_complete_panel_do_not_impute_missing_months(self):
        panels, categories, parents, indices, source = read_panels(SOURCE)
        self.assertEqual(source["raw_rows"], 14832)
        self.assertEqual(source["source_sha256"], hashlib.sha256(SOURCE.read_bytes()).hexdigest())
        self.assertEqual(len(panels), 69)
        self.assertEqual(len(categories), 94)
        self.assertEqual(len(indices), 12)
        self.assertEqual(source["missing_months"], ["2023-09", "2023-11", "2023-12"])
        self.assertEqual(source["missing_months_imputed"], 0)
        self.assertEqual(source["missing_cells_imputed"], 0)
        self.assertFalse(any(parents[name] in EXCLUDED_PARENTS for name in categories))
        self.assertNotIn("옻닭전문", categories)  # One missing sex-month is not silently zero-filled.
        for row in panels:
            self.assertAlmostEqual(sum(row["shares"]), 1.0, places=12)

    def test_selection_and_comparators_have_temporal_scopes_and_actual_denominators(self):
        metrics = json.loads((ROOT / "models_dining/dining_metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["algorithm"], ALGORITHM)
        self.assertFalse(metrics["selection"]["test_used_for_selection"])
        self.assertEqual(metrics["selection"]["candidate_count"], 288)
        self.assertEqual(metrics["split"]["train_end"], "2021-12")
        self.assertEqual(metrics["split"]["validation_end"], "2022-12")
        self.assertEqual(metrics["split"]["test_start"], "2023-01")
        self.assertEqual(metrics["split"]["test_fit_scope"], "training_plus_validation_for_all_comparators")
        self.assertEqual(metrics["split"]["serving_fit_scope"], "all_observed_months_after_evaluation")
        self.assertEqual(metrics["test"]["model"]["category_observations"], 94 * 21)
        for tolerance in metrics["test"]["model"]["within_tolerance"].values():
            self.assertEqual(tolerance["total"], 1974)
            self.assertLessEqual(tolerance["within"], tolerance["total"])
        receipt = metrics["selection"].pop("selection_sha256")
        self.assertEqual(receipt, _hash(metrics["selection"]))

    def test_every_month_has_bounded_distributions_and_uses_serialized_ml(self):
        distributions = []
        for month in range(1, 13):
            result = predict_dining(ROOT, month=month, limit=100)
            self.assertEqual(result["status"], "historical_pattern")
            self.assertEqual(result["model"]["selected_serving_model"], "direct_seasonal_ridge")
            self.assertFalse(result["model"]["runtime_llm"])
            self.assertEqual(result["returned_count"], 94)
            self.assertTrue(all(0 <= row["predicted_share_percent"] <= 100 for row in result["items"]))
            self.assertAlmostEqual(sum(row["predicted_share_percent"] for row in result["items"]), 100.0, places=4)
            self.assertEqual(result["observation_period"], {"start": "2019-01", "end": "2024-12"})
            self.assertFalse(result["scope_detail"]["region_available"])
            self.assertFalse(result["scope_detail"]["resident_tourist_available"])
            distributions.append(tuple((row["category"], row["predicted_share_percent"]) for row in result["items"]))
        self.assertGreater(len(set(distributions)), 1)

    def test_category_filter_does_not_renormalize_or_turn_composition_into_preferences(self):
        full = predict_dining(ROOT, month=6, limit=100)
        filtered = predict_dining(ROOT, month=6, category="한식", limit=100)
        expected = [row for row in full["items"] if "한식" in row["category"] or "한식" in row["parent_category"]]
        self.assertEqual(filtered["items"], expected)
        self.assertLess(filtered["filtered_share_percent"], 100)
        empty = predict_dining(ROOT, month=6, category="원자료에 없는 업종", limit=12)
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["total_matches"], 0)
        limited = predict_dining(ROOT, month=6, limit=3)
        self.assertEqual(limited["items"], full["items"][:3])
        self.assertLess(sum(row["predicted_share_percent"] for row in limited["items"]), 100)

    def test_observed_transaction_amounts_match_actual_2024_card_records(self):
        rows = list(csv.DictReader(io.StringIO(SOURCE.read_bytes().decode("cp949"))))
        result = predict_dining(ROOT, month=6, category="일반한식/백반", limit=1)
        item = result["items"][0]
        raw = [row for row in rows if row["연월"].startswith("2024") and row["소분류업종명"] == item["category"]]
        count = sum(int(row["이용건수"]) for row in raw)
        amount = sum(int(row["이용금액"]) for row in raw)
        self.assertEqual(item["observed_transaction_count"], count)
        self.assertEqual(item["historical_amount_per_transaction_krw"], round(amount / count))
        self.assertEqual(item["reference_period"], {"start": "2024-01", "end": "2024-12", "observed_months": 12})
        self.assertGreater(item["test_mae_percentage_points"], 0)
        self.assertTrue(result["scope_detail"]["amount_is_observed_not_predicted"])

    def test_invalid_inputs_are_not_silently_coerced(self):
        for value in (True, False, None, "06", "6.1", 0, 13, 1.5, float("inf")):
            with self.subTest(month=value), self.assertRaises(ValueError):
                predict_dining(ROOT, month=value)
        for value in (0, -1, 101, True, "1.0"):
            with self.subTest(limit=value), self.assertRaises(ValueError):
                predict_dining(ROOT, limit=value)
        for value in ([], 1, "x" * 101):
            with self.subTest(category=value), self.assertRaises(ValueError):
                predict_dining(ROOT, category=value)

    def test_broken_hash_and_rehashed_wrong_coefficients_fail_closed(self):
        original = json.loads((ROOT / "models_dining/dining_model.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "model.json"
            changed = json.loads(json.dumps(original))
            changed["fitted"]["coefficients"][0][0] += 0.1
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "무결성"):
                _load_model(str(path), 0, 0, str(SOURCE), 0, 0)
            changed = json.loads(json.dumps(original))
            changed["fitted"]["coefficients"][0].pop()
            changed.pop("model_sha256")
            changed["model_sha256"] = _hash(changed)
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "계수"):
                _load_model(str(path), 1, 0, str(SOURCE), 0, 0)

    def test_reproduction_uses_only_original_observations(self):
        with tempfile.TemporaryDirectory() as scratch:
            metrics = train_dining(SOURCE, scratch)
            rebuilt = Path(scratch) / "dining_model.json"
            expected = ROOT / "models_dining/dining_model.json"
            self.assertEqual(rebuilt.read_bytes(), expected.read_bytes())
            self.assertEqual(metrics["source"]["source_sha256"], hashlib.sha256(SOURCE.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
