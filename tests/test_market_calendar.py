from datetime import datetime, timedelta, timezone
import unittest

from market_calendar import latest_refresh_date


JST = timezone(timedelta(hours=9))


class MarketCalendarTests(unittest.TestCase):
    def test_before_16_uses_previous_business_day(self):
        self.assertEqual(
            latest_refresh_date(datetime(2026, 9, 11, 15, 59, tzinfo=JST)).isoformat(),
            "2026-09-10",
        )

    def test_after_16_uses_same_business_day(self):
        self.assertEqual(
            latest_refresh_date(datetime(2026, 9, 11, 16, 0, tzinfo=JST)).isoformat(),
            "2026-09-11",
        )

    def test_weekend_uses_previous_friday(self):
        self.assertEqual(
            latest_refresh_date(datetime(2026, 9, 12, 18, 0, tzinfo=JST)).isoformat(),
            "2026-09-11",
        )

    def test_japanese_holiday_is_skipped(self):
        # 2026-09-21 is Respect for the Aged Day.
        self.assertEqual(
            latest_refresh_date(datetime(2026, 9, 21, 18, 0, tzinfo=JST)).isoformat(),
            "2026-09-18",
        )


if __name__ == "__main__":
    unittest.main()
