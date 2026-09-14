from datetime import date
import unittest

import pandas as pd

from after365_analysis import (
    build_after365_summary,
    calculate_after365_average,
    find_yearly_low_month,
)


class After365SummaryTests(unittest.TestCase):
    def test_groups_by_year_and_uses_days_after_each_low(self):
        prices = pd.DataFrame(
            {
                "Low": [100, 80, 90, 130, 70, 120],
                "High": [110, 85, 100, 150, 75, 140],
            },
            index=pd.to_datetime(
                [
                    "2023-01-10",
                    "2023-06-01",
                    "2023-07-01",
                    "2024-05-30",
                    "2024-08-01",
                    "2025-01-15",
                ]
            ),
        )

        result = build_after365_summary(
            prices, date(2023, 1, 1), date(2025, 12, 31)
        )

        self.assertEqual(result.iloc[0].to_dict(), {
            "年数": "2023年",
            "最安値": 80.0,
            "その後1年間の最高高値": 150.0,
            "その後1年間の最高安値": 80.0,
        })
        self.assertEqual(result.iloc[1].to_dict(), {
            "年数": "2024年",
            "最安値": 70.0,
            "その後1年間の最高高値": 140.0,
            "その後1年間の最高安値": 70.0,
        })
        self.assertTrue(pd.isna(result.iloc[2]["その後1年間の最高高値"]))

    def test_averages_past_years_within_fifty_percent_of_current_low(self):
        summary = pd.DataFrame(
            [
                ["2023年", 80.0, 144.0, 70.0],
                ["2024年", 140.0, 210.0, 120.0],
                ["2022年", 100.0, 300.0, 50.0],
                ["2025年", 220.0, 330.0, 200.0],
                ["2026年", 100.0, 125.0, 100.0],
            ],
            columns=[
                "年数",
                "最安値",
                "その後1年間の最高高値",
                "その後1年間の最高安値",
            ],
        )

        result = calculate_after365_average(summary, 2026)

        self.assertEqual(result["current_lowest"], 100.0)
        self.assertAlmostEqual(result["average_high"], 180.0)
        self.assertAlmostEqual(result["average_low"], 85.71428571428572)
        self.assertEqual(result["sample_count"], 3)

        mean_result = calculate_after365_average(summary, 2026, method="mean")
        self.assertAlmostEqual(mean_result["average_high"], 210.0)
        self.assertAlmostEqual(mean_result["average_low"], 74.4047619047619)

    def test_finds_month_of_yearly_low(self):
        prices = pd.DataFrame(
            {"Low": [120.0, 90.0, 100.0]},
            index=pd.to_datetime(["2026-01-10", "2026-08-03", "2026-09-01"]),
        )

        self.assertEqual(find_yearly_low_month(prices, 2026), 8)


if __name__ == "__main__":
    unittest.main()
