import csv
import json
import math
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "public" / "data" / "etf-shares.json"
CSV_PATH = ROOT / "public" / "data" / "etf-shares.csv"
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


if __name__ == "__main__":
    unittest.main()
