import csv
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from jeju_agent.context_model import forecast_context, train_context


class ContextModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent, prefix="context_test_")
        self.root = Path(self.tmp.name)
        self.csv_path = self.root / "monthly.csv"
        self.rows = []
        for i in range(30):
            self.rows.append({"month": f"{2023 + i // 12:04d}-{i % 12 + 1:02d}", "region": "jeju", "category": "food", "value": str(100 + i * 3), "measure": "transactions", "source_id": "synthetic_region"})

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["month", "region", "category", "value", "measure", "source_id"])
            writer.writeheader()
            writer.writerows(self.rows)

    def test_time_split_forecast_and_cutoff(self):
        self.write()
        result = train_context(self.csv_path, self.root / "model")
        self.assertEqual(result["metrics"]["validation_training_through"], "2024-12")
        self.assertEqual(result["metrics"]["validation_from"], "2025-01")
        predicted = forecast_context(result["model_path"], "2025-07")
        self.assertEqual(predicted[0]["scope"], "region_category_month")
        self.assertEqual(predicted[0]["measure"], "transactions")
        self.assertEqual(predicted[0]["data_provenance"], "synthetic")
        self.assertTrue(math.isfinite(predicted[0]["predicted_value"]))
        with self.assertRaises(ValueError):
            forecast_context(result["model_path"], "2025-06")
        with self.assertRaises(ValueError):
            forecast_context(result["model_path"], "2024-01")
        long_forecast = forecast_context(result["model_path"], "2025-10")
        self.assertTrue(any("3개월" in w for w in long_forecast[0]["warnings"]))

    def test_duplicate_group_month_refused_even_different_source(self):
        duplicate = dict(self.rows[0], source_id="different")
        self.rows.append(duplicate)
        self.write()
        with self.assertRaises(ValueError):
            train_context(self.csv_path, self.root / "model")

    def test_mixed_measures_refused(self):
        self.rows[0]["measure"] = "users"
        self.write()
        with self.assertRaises(ValueError):
            train_context(self.csv_path, self.root / "model")

    def test_negative_and_non_finite_refused(self):
        for invalid in ("-1", "nan", "inf"):
            self.rows[0]["value"] = invalid
            self.write()
            with self.assertRaises(ValueError):
                train_context(self.csv_path, self.root / "model")

    def test_holdout_cannot_change_prior_only_baseline(self):
        self.write()
        first = train_context(self.csv_path, self.root / "first")
        # Validation actuals change; reconstruct baseline absolute error to
        # ensure it cannot learn the changed held-out values.
        for row in self.rows[24:]:
            row["value"] = "10000"
        self.write()
        changed = train_context(self.csv_path, self.root / "changed")
        # Same-month training observations span 2023 and 2024, so mean both.
        seasonal_means = [(100 + i * 3 + 100 + (i + 12) * 3) / 2 for i in range(6)]
        expected = sum(10000 - b for b in seasonal_means) / 6
        self.assertAlmostEqual(changed["metrics"]["baseline"]["mae"], expected)
        self.assertEqual(first["metrics"]["validation_training_through"], changed["metrics"]["validation_training_through"])

    def test_source_hash_and_mixed_synthetic_provenance(self):
        self.rows[0]["source_id"] = "SYNTHETIC_REGION"
        self.rows[1]["source_id"] = "real_unverified_source"
        self.write()
        result = train_context(self.csv_path, self.root / "model")
        model = json.loads(Path(result["model_path"]).read_text(encoding="utf-8"))
        self.assertEqual(model["training_csv_sha256"], hashlib.sha256(self.csv_path.read_bytes()).hexdigest())
        self.assertEqual(model["data_provenance"], "synthetic_with_mixed")
        self.assertEqual(result["metrics"]["data_provenance"], "synthetic_with_mixed")
        forecast = forecast_context(result["model_path"], "2025-07")
        self.assertTrue(any("합성" in w for w in forecast[0]["warnings"]))

    def test_saved_model_schema_refuses_corruption(self):
        self.write()
        result = train_context(self.csv_path, self.root / "model")
        model_path = Path(result["model_path"])
        original = json.loads(model_path.read_text(encoding="utf-8"))
        corruptions = [
            {"weights": original["weights"][:-1]},
            {"weights": [True] + original["weights"][1:]},
            {"weights": [float("nan")] + original["weights"][1:]},
            {"weights": [float("inf")] + original["weights"][1:]},
            {"version": True}, {"version": 2}, {"algorithm": "other"},
            {"groups": []}, {"groups": [["", "food"]]},
            {"groups": [["jeju", "food"], ["jeju", "food"]]},
            {"groups": [["jeju", "food", "extra"]]},
            {"data_provenance": "unverified"}, {"training_csv_sha256": "not-a-hash"},
        ]
        for corruption in corruptions:
            with self.subTest(corruption=corruption):
                model_path.write_text(json.dumps(dict(original, **corruption)), encoding="utf-8")
                with self.assertRaises(ValueError):
                    forecast_context(model_path, "2025-07")


if __name__ == "__main__":
    unittest.main()
