from __future__ import annotations

from datetime import date

import pandas as pd


AFTER365_COLUMNS = [
    "年数",
    "最安値",
    "その後1年間の最高高値",
    "その後1年間の最高安値",
]


def build_after365_summary(
    prices: pd.DataFrame, start_date: date, end_date: date
) -> pd.DataFrame:
    """Summarize each year's low and the next 365 days' highest high and lowest low."""
    if prices.empty or not {"Low", "High"}.issubset(prices.columns):
        return pd.DataFrame(columns=AFTER365_COLUMNS)

    frame = prices.sort_index()
    rows: list[dict[str, object]] = []
    for year in range(start_date.year, end_date.year + 1):
        year_start = max(pd.Timestamp(start_date), pd.Timestamp(year=year, month=1, day=1))
        year_end = min(pd.Timestamp(end_date), pd.Timestamp(year=year, month=12, day=31))
        yearly = frame.loc[year_start:year_end]
        yearly_lows = yearly["Low"].dropna()
        if yearly_lows.empty:
            continue

        lowest_date = pd.Timestamp(yearly_lows.idxmin())
        following = frame.loc[
            (frame.index > lowest_date)
            & (frame.index <= lowest_date + pd.Timedelta(365, unit="D"))
        ]
        following_highs = following["High"].dropna()
        low_window = frame.loc[
            (frame.index >= lowest_date)
            & (frame.index <= lowest_date + pd.Timedelta(365, unit="D"))
        ]
        following_lows = low_window["Low"].dropna()
        rows.append(
            {
                "年数": f"{year}年",
                "最安値": float(yearly_lows.loc[lowest_date]),
                "その後1年間の最高高値": (
                    float(following_highs.max()) if not following_highs.empty else None
                ),
                "その後1年間の最高安値": (
                    float(following_lows.min()) if not following_lows.empty else None
                ),
            }
        )

    return pd.DataFrame(rows, columns=AFTER365_COLUMNS)


def calculate_after365_average(
    summary: pd.DataFrame,
    current_year: int,
    tolerance: float = 0.5,
    method: str = "median",
) -> dict[str, float | int] | None:
    """Aggregate percentage outcomes for comparable past lows."""
    if method not in {"median", "mean"}:
        raise ValueError("method must be 'median' or 'mean'")
    if summary.empty:
        return None
    current_rows = summary.loc[summary["年数"].eq(f"{current_year}年")]
    if current_rows.empty or pd.isna(current_rows.iloc[-1]["最安値"]):
        return None

    current_lowest = float(current_rows.iloc[-1]["最安値"])
    comparable = summary.loc[
        ~summary["年数"].eq(f"{current_year}年")
        & summary["最安値"].between(
            current_lowest * (1 - tolerance),
            current_lowest * (1 + tolerance),
            inclusive="both",
        )
    ]
    if comparable.empty:
        return None

    # Take the median of each comparable year's percentage move from its own
    # low, then apply that median rate to this year's low.  This avoids mixing absolute
    # yen moves from years with different share-price levels.
    valid_comparable = comparable.loc[comparable["最安値"].ne(0)]
    high_change_rates = (
        valid_comparable["その後1年間の最高高値"]
        / valid_comparable["最安値"]
        - 1
    ).dropna()
    low_change_rates = (
        valid_comparable["その後1年間の最高安値"]
        / valid_comparable["最安値"]
        - 1
    ).dropna()
    aggregate = "mean" if method == "mean" else "median"
    average_high_rate = getattr(high_change_rates, aggregate)()
    average_low_rate = getattr(low_change_rates, aggregate)()
    average_high = current_lowest * (1 + average_high_rate)
    average_low = current_lowest * (1 + average_low_rate)
    return {
        "current_lowest": current_lowest,
        "average_high": float(average_high) if not pd.isna(average_high) else float("nan"),
        "average_low": float(average_low) if not pd.isna(average_low) else float("nan"),
        "sample_count": int(len(comparable)),
    }


def find_yearly_low_month(prices: pd.DataFrame, year: int) -> int | None:
    """Return the calendar month containing a year's lowest Low value."""
    if prices.empty or "Low" not in prices.columns:
        return None
    frame = prices.sort_index()
    yearly_lows = frame.loc[
        (frame.index >= pd.Timestamp(year=year, month=1, day=1))
        & (frame.index <= pd.Timestamp(year=year, month=12, day=31)),
        "Low",
    ].dropna()
    if yearly_lows.empty:
        return None
    return int(pd.Timestamp(yearly_lows.idxmin()).month)
