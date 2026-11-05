from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from jeju_agent import mobility_model as mobility


class MobilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp_root = Path(__file__).resolve().parents[1] / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=temp_root)
        cls.root = Path(cls.temp.name)
        cls.csv_path = cls.root / "observations.csv"
        cls.rows = []
        start = dt.date(2025, 1, 1)
        for offset in range(140):
            day = start + dt.timedelta(days=offset)
            for index, label in enumerate(mobility.BUCKETS):
                rate = 25 + index * 20 + day.weekday() * 4 + day.month * 2
                cls.rows.append({"base_date": day.strftime("%Y%m%d"), "day_of_week": mobility.WEEKDAYS[day.weekday()], "base_hour": label, "user_type": "일반", "user_count": rate * mobility.HOURS[label]})
            if offset % 3 == 0:  # Deliberately incomplete other-ticket observations.
                cls.rows.append({"base_date": day.strftime("%Y%m%d"), "day_of_week": mobility.WEEKDAYS[day.weekday()], "base_hour": mobility.BUCKETS[1], "user_type": "경로", "user_count": 10})
        cls.write_rows(cls.csv_path, cls.rows)
        cls.output = cls.root / "models"
        cls.metrics = mobility.train_mobility(cls.csv_path, cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def write_rows(path, rows):
        with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["base_date", "day_of_week", "base_hour", "user_type", "user_count"])
            writer.writeheader()
            writer.writerows(rows)

    def alternate_csv(self, name, rows):
        path = self.root / name
        self.write_rows(path, rows)
        return path

    def test_temporal_partitions_and_train_only_evaluation(self):
        splits = self.metrics["split"]
        self.assertLess(splits["train"]["end"], splits["validation"]["start"])
        self.assertLess(splits["validation"]["end"], splits["test"]["start"])
        self.assertEqual(sum(splits[part]["days"] for part in ("train", "validation", "test")), 140)
        self.assertEqual(splits["baseline_fit_scope"], "training_partition_only")
        calls = []
        real_fit = mobility._fit

        def spy(rows, *args, **kwargs):
            calls.append(max(row["date"] for row in rows))
            return real_fit(rows, *args, **kwargs)

        with mock.patch.object(mobility, "_fit", side_effect=spy):
            mobility.train_mobility(self.csv_path, self.root / "leak_audit")
        self.assertEqual(calls, [splits["train"]["end"], self.metrics["observation_period"]["end"]])

    def test_holdout_labels_do_not_change_evaluation_fit(self):
        altered = [dict(row) for row in self.rows]
        cutoff = self.metrics["split"]["train"]["end"].replace("-", "")
        for row in altered:
            if row["base_date"] > cutoff:
                row["user_count"] *= 25
        first_fits = []
        real_fit = mobility._fit

        def spy(rows, *args, **kwargs):
            fitted = real_fit(rows, *args, **kwargs)
            first_fits.append(fitted)
            return fitted

        with mock.patch.object(mobility, "_fit", side_effect=spy):
            mobility.train_mobility(self.csv_path, self.root / "original_fit")
            mobility.train_mobility(self.alternate_csv("altered.csv", altered), self.root / "altered_fit")
        self.assertEqual(first_fits[0], first_fits[2])
        self.assertNotEqual(first_fits[1]["weights"], first_fits[3]["weights"])

    def test_hour_width_and_incomplete_other_ticket_types(self):
        rows, selection = mobility._read_rows(self.csv_path)
        self.assertEqual(len(rows), 140 * 7)
        self.assertEqual(selection["missing_cells_imputed"], 0)
        self.assertEqual(selection["excluded_types"], ["경로"])
        first = rows[0]
        self.assertEqual(first["hours"], 6)
        self.assertEqual(first["rate"], first["count"] / 6)
        self.assertEqual(rows[1]["hours"], 3)
        self.assertEqual(rows[1]["rate"], rows[1]["count"] / 3)

    def test_missing_regular_cell_is_not_imputed(self):
        altered = [dict(row) for row in self.rows]
        del altered[0]
        with self.assertRaisesRegex(ValueError, "완전하지"):
            mobility.train_mobility(self.alternate_csv("missing_cell.csv", altered), self.root / "missing_model")

    def test_duplicate_observation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "중복"):
            mobility.train_mobility(self.alternate_csv("duplicate.csv", self.rows + [self.rows[0]]), self.root / "duplicate_model")

    def test_missing_negative_nonfinite_or_fractional_counts_rejected(self):
        for value in ["", "NaN", "Infinity", "-1", "1.25", "not-a-number"]:
            with self.subTest(value=value):
                altered = [dict(row) for row in self.rows]
                altered[0]["user_count"] = value
                with self.assertRaises(ValueError):
                    mobility.train_mobility(self.alternate_csv("invalid_count.csv", altered), self.root / "invalid_model")

    def test_stale_historical_semantics_and_correct_age(self):
        with mock.patch.object(mobility, "_today_kst", return_value=dt.date(2026, 10, 27)):
            result = mobility.predict_mobility(self.output / "mobility_model.json", "2027-02-01")
        expected_age = (dt.date(2026, 10, 27) - dt.date.fromisoformat(self.metrics["observation_period"]["end"])).days
        self.assertEqual(result["data_age_days"], expected_age)
        self.assertTrue(result["is_stale"])
        self.assertEqual(result["status"], "historical_pattern")
        self.assertEqual(result["scope"], "제주 전체 일반승차 집계")
        self.assertEqual(len(result["slots"]), 7)
        self.assertTrue(any("실시간" in warning for warning in result["warnings"]))
        for slot in result["slots"]:
            self.assertAlmostEqual(slot["predicted_users_per_hour"] * slot["bucket_hours"], slot["predicted_bucket_users"], delta=0.04)
            self.assertGreaterEqual(slot["relative_demand"], 0)
            self.assertLessEqual(slot["relative_demand"], 1)

    def test_recommendation_respects_period_and_excludes_overnight(self):
        for period in mobility.PERIODS:
            with self.subTest(period=period):
                result = mobility.predict_mobility(self.output / "mobility_model.json", "2026-10-27", period)
                candidates = [slot for slot in result["slots"] if slot["within_preferred_period"] and slot["label"] != mobility.BUCKETS[0]]
                self.assertEqual(result["recommended_slot"], min(candidates, key=lambda slot: slot["predicted_users_per_hour"]))
                self.assertNotEqual(result["recommended_slot"]["label"], mobility.BUCKETS[0])

    def test_invalid_date_and_period_rejected(self):
        for day, period in [("2026-02-30", "daytime"), ("2026-10-27", "night"), (20261027, "daytime")]:
            with self.subTest(day=day, period=period), self.assertRaises(ValueError):
                mobility.predict_mobility(self.output / "mobility_model.json", day, period)

    def test_invalid_dimensions_nonfinite_hash_and_version_rejected(self):
        original = json.loads((self.output / "mobility_model.json").read_text(encoding="utf-8"))
        cases = [dict(original, weights=original["weights"][:-1]), dict(original, weights=[float("nan")] + original["weights"][1:]), dict(original, source_sha256="bad"), dict(original, model_version="unknown"), dict(original, scope="tampered")]
        for index, model in enumerate(cases):
            with self.subTest(index=index):
                path = self.root / "bad_model.json"
                path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    mobility.predict_mobility(path, "2026-10-27")

    def test_worse_model_result_is_reported_without_hiding_baseline(self):
        for partition in ("validation", "test"):
            report = self.metrics[partition]
            self.assertIn("model", report)
            self.assertIn("baseline", report)
            self.assertIn("wape_bucket_counts", report["model"])
            self.assertEqual(report["model_better_than_baseline_mae"], report["model"]["mae_per_hour"] < report["baseline"]["mae_per_hour"])

    def test_serving_gate_uses_validation_not_test_result(self):
        cases = [(3, 4, 5, "huber_calendar"), (5, 3, 4, "ridge"), (5, 4, 3, "weekday_bucket_mean"), (3, 3, 3, "weekday_bucket_mean")]
        for calendar, ridge, baseline, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(mobility._select_serving({"huber_calendar": calendar, "ridge": ridge, "weekday_bucket_mean": baseline}), expected)
        altered = [dict(row) for row in self.rows]
        cutoff = self.metrics["split"]["test"]["start"].replace("-", "")
        for row in altered:
            if row["base_date"] >= cutoff:
                row["user_count"] *= 100
        metrics = mobility.train_mobility(self.alternate_csv("test_labels_changed.csv", altered), self.root / "gate_test_labels")
        self.assertEqual(metrics["serving_selection"], self.metrics["serving_selection"])
        self.assertEqual(metrics["hyperparameter_search"], self.metrics["hyperparameter_search"])
        self.assertNotEqual(metrics["test"]["model"]["mae_per_hour"], self.metrics["test"]["model"]["mae_per_hour"])
        self.assertFalse(metrics["serving_selection"]["test_used_for_selection"])

    def test_baseline_serving_branch_uses_fitted_weekday_bucket_rates(self):
        model = json.loads((self.output / "mobility_model.json").read_text(encoding="utf-8"))
        model.update(selected_serving_model="weekday_bucket_mean", validation_mae_per_hour={"ridge": 10.0, "weekday_bucket_mean": 8.0, "huber_calendar": 12.0}, why="검증 오차로 평균 기준모델을 선택했습니다.")
        model["model_sha256"] = mobility._model_digest(model)
        path = self.root / "baseline_serving.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        day = dt.date(2026, 10, 27)
        result = mobility.predict_mobility(path, day.isoformat())
        self.assertEqual(result["model"]["algorithm"], mobility.BASELINE_ALGORITHM)
        self.assertEqual(result["model"]["candidate_algorithm"], mobility.ALGORITHM)
        self.assertEqual(len(result["slots"]), 7)
        self.assertTrue(any("서비스 기본" in warning for warning in result["warnings"]))
        for slot in result["slots"]:
            expected = model["baseline_weekday_bucket_means"][f"{day.weekday()}|{slot['label']}"]
            self.assertEqual(slot["predicted_users_per_hour"], round(expected, 2))
            self.assertEqual(slot["predicted_bucket_users"], round(expected * mobility.HOURS[slot["label"]], 2))

    def test_serving_gate_mismatch_is_rejected(self):
        model = json.loads((self.output / "mobility_model.json").read_text(encoding="utf-8"))
        model.update(selected_serving_model="ridge", validation_mae_per_hour={"ridge": 10.0, "weekday_bucket_mean": 8.0, "huber_calendar": 12.0})
        model["model_sha256"] = mobility._model_digest(model)
        path = self.root / "mismatched_gate.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "선택이 검증 오차"):
            mobility.predict_mobility(path, "2026-10-27")

    def test_calendar_serving_uses_serialized_fitted_weights(self):
        model = json.loads((self.output / "mobility_model.json").read_text(encoding="utf-8"))
        model.update(selected_serving_model="huber_calendar", validation_mae_per_hour={"ridge": 10.0, "weekday_bucket_mean": 8.0, "huber_calendar": 6.0})
        model["model_sha256"] = mobility._model_digest(model)
        path = self.root / "calendar_serving.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        day = dt.date(2026, 10, 27)
        result = mobility.predict_mobility(path, day.isoformat())
        self.assertEqual(result["model"]["algorithm"], mobility.ALGORITHM)
        for slot in result["slots"]:
            expected = mobility._predict_calendar(model["calendar"], day, slot["label"])
            self.assertEqual(slot["predicted_users_per_hour"], round(expected, 2))

    def test_corrupt_calendar_is_rejected_even_with_recomputed_hash(self):
        original = json.loads((self.output / "mobility_model.json").read_text(encoding="utf-8"))
        for field, value in [("coefficients", [1.0]), ("scale", float("nan"))]:
            model = json.loads(json.dumps(original))
            model["calendar"]["bucket_models"][mobility.BUCKETS[0]][field] = value
            if field == "coefficients":
                model["model_sha256"] = mobility._model_digest(model)
            with self.subTest(field=field), self.assertRaises(ValueError):
                mobility._validate_model(model)


if __name__ == "__main__":
    unittest.main()
