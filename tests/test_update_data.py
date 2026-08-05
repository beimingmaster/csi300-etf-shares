import unittest
from datetime import date
from unittest.mock import patch

from scripts import update_data


class TradingCalendarTest(unittest.TestCase):
    @patch("scripts.update_data.get_json")
    def test_calendar_uses_a_padded_query_and_discards_boundary_snapshot(self, get_json):
        get_json.return_value = {
            "code": "200",
            "data": [
                {
                    "tradeDate": "20111225",
                    "indexCode": "000300",
                    "indexNameCnAll": "沪深300指数",
                    "close": 2298.75,
                },
                {
                    "tradeDate": "20120104",
                    "indexCode": "000300",
                    "indexNameCnAll": "沪深300指数",
                    "close": 2298.75,
                },
                {
                    "tradeDate": "20120105",
                    "indexCode": "000300",
                    "indexNameCnAll": "沪深300指数",
                    "close": 2276.39,
                },
            ],
        }

        dates = update_data.fetch_trading_calendar(
            date(2012, 1, 1),
            date(2012, 1, 5),
        )

        self.assertEqual(dates, [date(2012, 1, 4), date(2012, 1, 5)])
        params = get_json.call_args.args[2]
        self.assertEqual(params["startDate"], "20111225")
        self.assertEqual(params["endDate"], "20120105")

    @patch("scripts.update_data.get_json")
    def test_calendar_rejects_a_weekend_inside_the_requested_window(self, get_json):
        get_json.return_value = {
            "code": "200",
            "data": [
                {
                    "tradeDate": "20120101",
                    "indexCode": "000300",
                    "indexNameCnAll": "沪深300指数",
                    "close": 2298.75,
                },
                {
                    "tradeDate": "20120104",
                    "indexCode": "000300",
                    "indexNameCnAll": "沪深300指数",
                    "close": 2298.75,
                },
            ],
        }

        with self.assertRaisesRegex(ValueError, "weekend trading date"):
            update_data.fetch_trading_calendar(
                date(2012, 1, 1),
                date(2012, 1, 5),
            )


class PublicationCompletenessTest(unittest.TestCase):
    @staticmethod
    def complete_rows(days):
        return {
            (day, fund.code): {"date": day, "code": fund.code}
            for day in days
            for fund in update_data.FUNDS
            if day >= update_data.parse_date(fund.daily_start_date)
        }

    def test_trims_only_incomplete_dates_at_the_tail(self):
        complete_day = date(2026, 8, 4)
        unpublished_day = date(2026, 8, 5)
        rows = self.complete_rows([complete_day])

        actual = update_data.trim_to_complete_prefix(
            rows,
            [complete_day, unpublished_day],
        )

        self.assertEqual(actual, [complete_day])

    def test_rejects_an_internal_gap(self):
        first = date(2026, 8, 3)
        gap = date(2026, 8, 4)
        last = date(2026, 8, 5)
        rows = self.complete_rows([first, last])

        with self.assertRaisesRegex(ValueError, "incomplete trading date before latest"):
            update_data.trim_to_complete_prefix(rows, [first, gap, last])


class SseResponseTest(unittest.TestCase):
    @patch("scripts.update_data.get_json")
    def test_rejects_a_snapshot_returned_for_the_wrong_date(self, get_json):
        get_json.return_value = {
            "result": [
                {
                    "STAT_DATE": "2026-08-04",
                    "SEC_CODE": code,
                    "TOT_VOL": "10000",
                }
                for code in update_data.SSE_CODES
            ]
        }

        with self.assertRaisesRegex(ValueError, "unexpected date"):
            update_data.fetch_sse_day(date(2026, 8, 5))


if __name__ == "__main__":
    unittest.main()
