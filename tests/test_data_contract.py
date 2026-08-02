import csv
import json
import math
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "public" / "data" / "etf-shares.json"
CSV_PATH = ROOT / "public" / "data" / "etf-shares.csv"
ARCHIVE_CSV_PATH = ROOT / "scripts" / "data" / "etf-shares-archive.csv"
HOLDER_JSON_PATH = ROOT / "public" / "data" / "holder-structure.json"
HOLDER_CSV_PATH = ROOT / "public" / "data" / "holder-structure.csv"
DAILY_AGGREGATE_CODES = {"510300", "510310", "510330", "159919"}
DAILY_STANDALONE_CODES = {"159915"}
DAILY_ALL_CODES = DAILY_AGGREGATE_CODES | DAILY_STANDALONE_CODES
HOLDER_STANDALONE_CODES = DAILY_STANDALONE_CODES
HOLDER_ALL_CODES = DAILY_ALL_CODES


class DataContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    def test_exact_fund_universe_and_complete_post_inception_dates(self):
        dates = self.data["dates"]
        metadata = self.data["metadata"]
        codes = {fund["code"] for fund in self.data["funds"]}

        self.assertEqual(codes, DAILY_ALL_CODES)
        self.assertEqual(set(self.data["series"]), DAILY_ALL_CODES)
        self.assertEqual(set(self.data["quality_series"]), DAILY_ALL_CODES)
        self.assertEqual(set(metadata["aggregate_fund_codes"]), DAILY_AGGREGATE_CODES)
        self.assertEqual(set(metadata["standalone_fund_codes"]), DAILY_STANDALONE_CODES)
        self.assertNotIn("159915", metadata["aggregate_fund_codes"])
        self.assertEqual(dates, sorted(set(dates)))
        self.assertEqual(len(dates), metadata["common_observations"])
        self.assertEqual(
            metadata["fund_observations"],
            sum(value is not None for values in self.data["series"].values() for value in values),
        )
        self.assertEqual(metadata["coverage_ratio"], 1)
        self.assertEqual(dates[0], metadata["actual_start_date"])
        self.assertEqual(dates[-1], metadata["latest_data_date"])
        self.assertEqual(metadata["requested_start_date"], "2012-01-01")
        self.assertEqual(dates[0], "2012-01-04")

        requested_span = (
            date.fromisoformat(dates[-1])
            - date.fromisoformat(metadata["requested_start_date"])
        )
        delayed_start = (
            date.fromisoformat(dates[0])
            - date.fromisoformat(metadata["requested_start_date"])
        )
        self.assertGreaterEqual(requested_span.days, 14 * 365)
        self.assertLessEqual(delayed_start.days, 7)

        fund_by_code = {fund["code"]: fund for fund in self.data["funds"]}
        for code, values in self.data["series"].items():
            self.assertEqual(len(values), len(dates))
            self.assertEqual(len(self.data["quality_series"][code]), len(dates))
            first_index = dates.index(fund_by_code[code]["first_data_date"])
            self.assertTrue(all(value is None for value in values[:first_index]))
            self.assertTrue(
                all(math.isfinite(value) and value > 0 for value in values[first_index:])
            )

    def test_aggregate_is_row_wise_sum(self):
        values = self.data["aggregate"]["values"]
        series = self.data["series"]

        self.assertEqual(len(values), len(self.data["dates"]))
        for index, aggregate in enumerate(values):
            members = [
                series[code][index]
                for code in DAILY_AGGREGATE_CODES
                if series[code][index] is not None
            ]
            self.assertEqual(self.data["aggregate"]["member_counts"][index], len(members))
            if members:
                self.assertAlmostEqual(aggregate, sum(members), places=6)
            else:
                self.assertIsNone(aggregate)
        self.assertEqual(self.data["aggregate"]["first_data_date"], "2012-05-28")
        self.assertEqual(self.data["aggregate"]["member_counts"][-1], 4)

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

    def test_csv_contains_all_daily_funds_and_quality_provenance(self):
        with CSV_PATH.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), self.data["metadata"]["fund_observations"])
        self.assertEqual({row["code"] for row in rows}, DAILY_ALL_CODES)
        self.assertTrue(all(float(row["shares_100m"]) > 0 for row in rows))
        self.assertEqual({row["quality"] for row in rows}, {"official", "estimated"})
        self.assertEqual(
            {row["method"] for row in rows},
            {"exchange_disclosure", "volume_turnover_inference"},
        )

    def test_chinext_daily_series_is_standalone_from_2012(self):
        fund = next(fund for fund in self.data["funds"] if fund["code"] == "159915")
        values = self.data["series"]["159915"]
        qualities = self.data["quality_series"]["159915"]

        self.assertFalse(fund["aggregate_member"])
        self.assertIsNone(fund["rank"])
        self.assertEqual(fund["first_data_date"], "2012-01-04")
        self.assertEqual(qualities[self.data["dates"].index("2016-08-02")], "免费行情推算")
        self.assertEqual(qualities[self.data["dates"].index("2016-08-03")], "交易所官方披露")
        self.assertGreater(values[-1], 0)

        with ARCHIVE_CSV_PATH.open(encoding="utf-8", newline="") as handle:
            archive_rows = list(csv.DictReader(handle))
        self.assertEqual({row["code"] for row in archive_rows}, DAILY_ALL_CODES)
        self.assertTrue(any(row["code"] == "159915" for row in archive_rows))


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
        self.assertEqual(metadata["report_count"], len(periods) * 5)
        self.assertEqual({fund["code"] for fund in self.data["funds"]}, HOLDER_ALL_CODES)
        self.assertEqual(set(metadata["aggregate_fund_codes"]), DAILY_AGGREGATE_CODES)
        self.assertEqual(set(metadata["standalone_fund_codes"]), HOLDER_STANDALONE_CODES)
        self.assertNotIn("159915", metadata["aggregate_fund_codes"])

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
                    for code in DAILY_AGGREGATE_CODES
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
        self.assertEqual({row["fund_code"] for row in rows}, HOLDER_ALL_CODES)
        self.assertEqual(
            {row["category"] for row in rows},
            {"national_team", "other_institution", "individual"},
        )
        self.assertTrue(all(int(row["holder_shares"]) > 0 for row in rows))
        self.assertTrue(
            all(
                row["official_pdf_url"].startswith(
                    ("http://eid.csrc.gov.cn/", "https://cdn.efunds.com.cn/")
                )
                for row in rows
            )
        )

    def test_chinext_fund_is_precise_and_standalone(self):
        series = self.data["series"]["159915"]

        self.assertEqual(series["total_shares_100m"][-1], 315.071236)
        self.assertEqual(
            series["categories"]["national_team"]["shares_100m"][-1],
            170.197842,
        )
        self.assertAlmostEqual(
            series["categories"]["individual"]["ratio_pct"][-1],
            21.16726,
            places=5,
        )


if __name__ == "__main__":
    unittest.main()
