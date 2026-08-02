import csv
import json
import math
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "public" / "data" / "etf-shares.json"
CSV_PATH = ROOT / "public" / "data" / "etf-shares.csv"
HOLDER_JSON_PATH = ROOT / "public" / "data" / "holder-structure.json"
HOLDER_CSV_PATH = ROOT / "public" / "data" / "holder-structure.csv"
EXPECTED_CODES = {"510300", "510310", "510330", "159919"}


class DataContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    def test_exact_fund_universe_and_complete_common_dates(self):
        dates = self.data["dates"]
        metadata = self.data["metadata"]
        codes = {fund["code"] for fund in self.data["funds"]}

        self.assertEqual(codes, EXPECTED_CODES)
        self.assertEqual(set(self.data["series"]), EXPECTED_CODES)
        self.assertEqual(dates, sorted(set(dates)))
        self.assertEqual(len(dates), metadata["common_observations"])
        self.assertEqual(metadata["fund_observations"], len(dates) * 4)
        self.assertEqual(metadata["coverage_ratio"], 1)
        self.assertEqual(dates[0], metadata["actual_start_date"])
        self.assertEqual(dates[-1], metadata["latest_data_date"])

        requested_span = (
            date.fromisoformat(dates[-1])
            - date.fromisoformat(metadata["requested_start_date"])
        )
        delayed_start = (
            date.fromisoformat(dates[0])
            - date.fromisoformat(metadata["requested_start_date"])
        )
        self.assertGreaterEqual(requested_span.days, 3650)
        self.assertLessEqual(delayed_start.days, 7)

        for values in self.data["series"].values():
            self.assertEqual(len(values), len(dates))
            self.assertTrue(all(math.isfinite(value) and value > 0 for value in values))

    def test_aggregate_is_row_wise_sum(self):
        values = self.data["aggregate"]["values"]
        series = self.data["series"]

        self.assertEqual(len(values), len(self.data["dates"]))
        for index, aggregate in enumerate(values):
            expected = sum(series[code][index] for code in EXPECTED_CODES)
            self.assertAlmostEqual(aggregate, expected, places=6)

    def test_reviewed_share_consolidation_is_recorded(self):
        event = next(
            item
            for item in self.data["reviewed_events"]
            if item["code"] == "510310" and item["date"] == "2024-09-20"
        )
        self.assertEqual(event["type"], "fund_share_consolidation")
        self.assertEqual(event["review_status"], "verified")
        self.assertLess(event["change_pct"], -20)
        self.assertTrue(event["source_url"].startswith("https://"))

    def test_csv_contains_only_selected_funds(self):
        with CSV_PATH.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertGreaterEqual(len(rows), self.data["metadata"]["fund_observations"])
        self.assertEqual({row["code"] for row in rows}, EXPECTED_CODES)
        self.assertTrue(all(float(row["shares_100m"]) > 0 for row in rows))


class HolderDataContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(HOLDER_JSON_PATH.read_text(encoding="utf-8"))

    def test_complete_semiannual_panel_and_latest_disclosure(self):
        periods = self.data["periods"]
        metadata = self.data["metadata"]

        self.assertEqual(len(periods), 9)
        self.assertEqual(periods, sorted(set(periods)))
        self.assertEqual(periods[0], "2021-12-31")
        self.assertEqual(periods[-1], "2025-12-31")
        self.assertEqual(metadata["latest_disclosure_date"], "2026-03-31")
        self.assertEqual(metadata["disclosure_frequency"], "semiannual")
        self.assertFalse(metadata["q1_2026_holder_data_available"])
        self.assertEqual(metadata["report_count"], len(periods) * 4)
        self.assertEqual({fund["code"] for fund in self.data["funds"]}, EXPECTED_CODES)

    def test_holder_categories_and_aggregate_are_consistent(self):
        categories = self.data["categories"]
        self.assertEqual(
            set(categories),
            {"national_team", "other_institution", "individual"},
        )
        self.assertEqual(categories["national_team"]["precision"], "lower_bound")
        self.assertEqual(categories["other_institution"]["precision"], "upper_bound")
        self.assertEqual(categories["individual"]["precision"], "exact")

        periods = self.data["periods"]
        aggregate = self.data["aggregate"]
        for category in categories:
            aggregate_series = aggregate["categories"][category]
            self.assertEqual(len(aggregate_series["shares_100m"]), len(periods))
            self.assertEqual(len(aggregate_series["ratio_pct"]), len(periods))
            for index in range(len(periods)):
                expected_shares = sum(
                    self.data["series"][code]["categories"][category]["shares_100m"][index]
                    for code in EXPECTED_CODES
                )
                self.assertAlmostEqual(
                    aggregate_series["shares_100m"][index],
                    expected_shares,
                    places=5,
                )
                self.assertGreaterEqual(aggregate_series["ratio_pct"][index], 0)
                self.assertLessEqual(aggregate_series["ratio_pct"][index], 100)

    def test_public_holder_csv_has_three_rows_per_report(self):
        with HOLDER_CSV_PATH.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), self.data["metadata"]["report_count"] * 3)
        self.assertEqual({row["fund_code"] for row in rows}, EXPECTED_CODES)
        self.assertEqual(
            {row["category"] for row in rows},
            {"national_team", "other_institution", "individual"},
        )
        self.assertTrue(all(int(row["holder_shares"]) > 0 for row in rows))
        self.assertTrue(all(row["official_pdf_url"].startswith("http://eid.csrc.gov.cn/") for row in rows))


if __name__ == "__main__":
    unittest.main()
