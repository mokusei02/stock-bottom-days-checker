"""Japan market refresh-day helpers shared by the apps and updater."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import holidays


JAPAN_TIMEZONE = timezone(timedelta(hours=9))
MARKET_REFRESH_TIME = time(16, 0)
JAPAN_HOLIDAYS = holidays.country_holidays("JP")


def is_japan_business_day(day: date) -> bool:
    """Return whether *day* is a weekday and not a Japanese public holiday."""
    return day.weekday() < 5 and day not in JAPAN_HOLIDAYS


def latest_refresh_date(now: datetime | None = None) -> date:
    """Return the latest Japanese business day whose 16:00 refresh has passed."""
    current = now.astimezone(JAPAN_TIMEZONE) if now else datetime.now(JAPAN_TIMEZONE)
    refresh_date = current.date()
    if current.time() < MARKET_REFRESH_TIME or not is_japan_business_day(refresh_date):
        refresh_date -= timedelta(days=1)
    while not is_japan_business_day(refresh_date):
        refresh_date -= timedelta(days=1)
    return refresh_date
