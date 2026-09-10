from __future__ import annotations

import base64
from html import escape
import json
import re
import threading
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import market_store

# Use an app-owned writable location for yfinance's timezone and cookie caches.
yf.set_tz_cache_location(str(Path(__file__).with_name(".yfinance-cache")))


LABELS = {"Close": "終値", "Low": "安値", "Open": "始値", "High": "高値"}
START_YEAR_OPTIONS = list(range(2000, 2030, 5))
SEARCH_HISTORY_FILE = Path(__file__).with_name(".search_history.json")
SEARCH_HISTORY_COOKIE = "stock_search_history"
RANKING_CACHE_FILE = Path(__file__).with_name(".light_pickling_ranking_cache.json")
JAPAN_TIMEZONE = timezone(timedelta(hours=9))
RANKING_REFRESH_TIME = time(16, 0)
TABLE_HEADER_STYLES = [
    {
        "selector": "th",
        "props": [("color", "#111111"), ("font-weight", "700")],
    }
]
NIKKEI225_CODES = [
    "4151", "4502", "4503", "4506", "4507", "4519", "4523", "4568", "4578",
    "285A", "4062", "6479", "6501", "6503", "6504", "6506", "6526", "6645",
    "6701", "6702", "6723", "6724", "6752", "6753", "6758", "6762", "6770",
    "6841", "6857", "6861", "6902", "6920", "6954", "6963", "6971", "6976",
    "6981", "7735", "7751", "7752", "8035",
    "543A", "7201", "7202", "7203", "7211", "7261", "7267", "7269", "7270",
    "7272", "4543", "4902", "6146", "7731", "7733", "7741",
    "9432", "9433", "9434", "9984",
    "5831", "7186", "8304", "8306", "8308", "8309", "8316", "8331", "8354",
    "8411", "8253", "8591", "8697", "8601", "8604", "8630", "8725", "8750",
    "8766", "8795", "1332",
    "2002", "2269", "2282", "2501", "2502", "2503", "2801", "2802", "2871",
    "2914", "3086", "3092", "3099", "3382", "7453", "7532", "8233", "8252",
    "8267", "9843", "9983",
    "2413", "2432", "3659", "3697", "4307", "4324", "4385", "4661", "4689",
    "4704", "4751", "4755", "6098", "6178", "6532", "7974", "9602", "9735",
    "9766", "1605", "3401", "3402", "3861",
    "3405", "3407", "4004", "4005", "4021", "4042", "4043", "4061", "4063",
    "4183", "4188", "4208", "4452", "4901", "4911", "6988", "5019", "5020",
    "5101", "5108", "5201", "5214", "5233", "5301", "5332", "5333", "5401",
    "5406", "5411", "3436", "5706", "5711", "5713", "5714", "5801", "5802",
    "5803", "2768", "8001", "8002", "8015", "8031", "8053", "8058",
    "1721", "1801", "1802", "1803", "1808", "1812", "1925", "1928", "1963",
    "5631", "6103", "6113", "6273", "6301", "6302", "6305", "6326", "6361",
    "6367", "6471", "6472", "6473", "7004", "7011", "7013", "7012",
    "7832", "7911", "7912", "7951", "3289", "8801", "8802", "8804", "8830",
    "9001", "9005", "9007", "9008", "9009", "9020", "9021", "9022", "9064",
    "9147", "9101", "9104", "9107", "9201", "9202", "9501", "9502", "9503",
    "9531", "9532",
]


def format_date_ja(value) -> str:
    return pd.Timestamp(value).strftime("%Y年%m月%d日")


def format_month_ja(value) -> str:
    timestamp = pd.Timestamp(value)
    return f"{timestamp.year}年{timestamp.month}月"


def format_price_with_change(value, base_price: float) -> str:
    if pd.isna(value):
        return "—"
    price = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if not base_price:
        return f"{price}円"
    change = (
        (Decimal(str(value)) / Decimal(str(base_price)) - Decimal("1"))
        * Decimal("100")
    ).quantize(Decimal("1"), rounding=ROUND_DOWN)
    change_text = format(change, "f")
    sign = "+" if change > 0 else ""
    return f"{price}円（{sign}{change_text}％）"


def format_ranking_lowest_for_responsive_display(value) -> str:
    """Keep the ranking value inline on desktop and split it on mobile."""
    text = str(value)
    match = re.fullmatch(r"(.+?円)（([+-]?\d+％)）", text)
    if not match:
        return escape(text)
    return (
        f'<span class="ranking-lowest-price">{escape(match.group(1))}</span>'
        '<span class="ranking-lowest-paren">（</span>'
        f'<span class="ranking-lowest-change">{escape(match.group(2))}</span>'
        '<span class="ranking-lowest-paren">）</span>'
    )


def render_ranking_table(frame: pd.DataFrame, key: str, bold_longest=False) -> None:
    """Render either ranking with exactly the same columns and styling."""
    display = frame.copy()
    display["最安値"] = display["最安値"].map(
        format_ranking_lowest_for_responsive_display
    )
    styles = pd.DataFrame(
        "background-color: #FFFFFF;", index=display.index, columns=display.columns
    )
    if bold_longest and "最長塩漬け期間" in styles:
        styles.loc[:, "最長塩漬け期間"] += " font-weight: 700;"
    for row_index, lowest_value in display["最安値"].items():
        percent_match = re.search(r"([+-]?\d+)％", str(lowest_value))
        if percent_match:
            change_percent = int(percent_match.group(1))
            text_color = "#2563EB" if change_percent >= -10 else "#DC2626"
            styles.loc[row_index, "最安値"] += (
                f" color: {text_color}; font-weight: 700;"
            )
    styled = display.style.apply(lambda _: styles, axis=None).set_table_styles(
        TABLE_HEADER_STYLES
    )
    with st.container(key=key):
        render_results_table(
            styled, 38 * (len(display) + 1) + 4, limit_vertical_height=False
        )


def normalize_prices(raw: pd.DataFrame) -> pd.DataFrame:
    """Return a date-indexed OHLC frame, accepting yfinance or ordinary CSV data."""
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).strip().title() for c in df.columns]
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.set_index("Date")
    df.index = pd.to_datetime(df.index, errors="coerce").tz_localize(None)
    df = df[~df.index.isna()].sort_index()
    for col in LABELS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def first_tradeable_date(df: pd.DataFrame, threshold: float):
    """Return the first day the selected price was within that day's trading range."""
    if "Low" not in df.columns or "High" not in df.columns:
        return None
    daily_range = df[["Low", "High"]].dropna()
    tradeable = daily_range[
        (daily_range["Low"] <= threshold) & (daily_range["High"] >= threshold)
    ]
    return tradeable.index[0] if not tradeable.empty else None


def find_streaks(df: pd.DataFrame, column: str, threshold: float) -> pd.DataFrame:
    prices = df[column].dropna()
    next_high_column = f"次の{threshold:,.0f}円までの最高値（円）"
    tradeable_start = first_tradeable_date(df, threshold)
    if tradeable_start is not None:
        prices = prices[prices.index >= tradeable_start]
    else:
        prices = prices.iloc[0:0]
    below = prices <= threshold
    group = below.ne(below.shift()).cumsum()
    rows = []
    for _, segment in prices[below].groupby(group[below]):
        start, end = segment.index[0], segment.index[-1]
        rows.append(
            {
                "開始日": start.date(),
                "終了日": end.date(),
                "下回った日数": (end - start).days + 1,
                "期間中最安値（円）": round(float(segment.min()), 2),
                "_開始日時": start,
                "_終了日時": end,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "開始日",
                "終了日",
                "下回った日数",
                "期間中最安値（円）",
                next_high_column,
            ]
        )

    high_prices = df["High"].dropna() if "High" in df.columns else prices
    for index, row in enumerate(rows):
        next_start = rows[index + 1]["_開始日時"] if index + 1 < len(rows) else None
        gap = high_prices[high_prices.index > row["_終了日時"]]
        if next_start is not None:
            gap = gap[gap.index < next_start]
        row[next_high_column] = round(float(gap.max()), 2) if not gap.empty else None

    result = pd.DataFrame(rows).sort_values(
        "開始日", ascending=False
    ).reset_index(drop=True)
    result = result.drop(columns=["_開始日時", "_終了日時"])
    return result


def find_light_pickling_price(
    df: pd.DataFrame, column: str, target_days: int = 30
) -> tuple[int, int]:
    """Find the highest whole-yen threshold whose longest streak is within target_days."""
    prices = df[column].dropna()
    if prices.empty:
        raise RuntimeError("浅漬け株価を計算できませんでした。")

    def longest_days(threshold: int) -> int:
        below = prices <= threshold
        if not below.any():
            return 0
        groups = below.ne(below.shift()).cumsum()
        return max(
            (segment.index[-1] - segment.index[0]).days + 1
            for _, segment in prices[below].groupby(groups[below])
        )

    low = int(prices.min())
    high = int(prices.max())
    best_price = low
    best_days = longest_days(low)
    while low <= high:
        candidate = (low + high) // 2
        duration = longest_days(candidate)
        if duration <= target_days:
            best_price, best_days = candidate, duration
            low = candidate + 1
        else:
            high = candidate - 1
    return best_price, best_days


@st.cache_data(ttl=300, show_spinner=False)
def saved_snapshot():
    return market_store.get_snapshot()


@st.cache_data(ttl=3600, show_spinner=False)
def saved_price_frame(revision, ticker, entry):
    return market_store.read_prices(revision, ticker, {"prices": {ticker: entry}})


@st.cache_data(ttl=3600, show_spinner=False)
def saved_ranking_frame(revision, ranking):
    return market_store.read_nikkei(revision, {"ranking": ranking})


def show_saved_data_status(entry):
    """Saved-data details are intentionally kept out of the user-facing UI."""
    return None


def download_prices(ticker: str, start: date, end: date) -> pd.DataFrame:
    revision, manifest = saved_snapshot()
    entry = manifest["prices"].get(ticker)
    if entry is None:
        raise RuntimeError("この銘柄の保存データはまだ取得できていません。次回の更新をお待ちください。")
    prices = saved_price_frame(revision, ticker, entry)
    prices = prices.loc[pd.Timestamp(start):pd.Timestamp(end)]
    if prices.empty:
        raise RuntimeError("指定期間の保存株価データがありません。")
    return prices


@st.cache_data(ttl=300, show_spinner=False)
def get_current_price(ticker: str) -> float:
    prices = download_prices(ticker, date(2000, 1, 1), date.today())
    if prices.empty or "Close" not in prices.columns:
        raise RuntimeError("現在の株価を取得できませんでした。")
    closes = prices["Close"].dropna()
    if closes.empty:
        raise RuntimeError("現在の株価を取得できませんでした。")
    return float(closes.iloc[-1])


def get_latest_close(prices: pd.DataFrame) -> float:
    """Use the latest close from the same history displayed in the result."""
    if prices.empty or "Close" not in prices.columns:
        raise RuntimeError("現在の株価を取得できませんでした。")
    closes = prices["Close"].dropna()
    if closes.empty:
        raise RuntimeError("現在の株価を取得できませんでした。")
    return float(closes.iloc[-1])


@st.cache_data(ttl=86400, show_spinner=False)
def get_company_info(ticker: str) -> dict:
    # Optional metadata must not block price analysis when the provider is limited.
    _, manifest = saved_snapshot()
    return manifest["prices"].get(ticker, {}).get("company_info", {})


def get_company_name(ticker: str, info: dict) -> str:
    security_code = ticker.removesuffix(".T")
    for option in load_company_options():
        code, name = option.split("｜", 1)
        if code == security_code:
            return name
    return info.get("longName") or info.get("shortName") or ticker.removesuffix(".T")


def format_market_cap(value) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return "情報なし"
    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:,.2f}兆円"
    return f"{value / 100_000_000:,.0f}億円"


def classify_company_size(market_cap) -> str:
    if not isinstance(market_cap, (int, float)) or market_cap <= 0:
        return "判定できません"
    if market_cap >= 1_000_000_000_000:
        return "大型（時価総額1兆円以上）"
    if market_cap >= 100_000_000_000:
        return "中型（時価総額1,000億円以上）"
    return "小型（時価総額1,000億円未満）"


def get_nukazuke_stage(longest_days: int) -> tuple[Path, str]:
    asset_dir = Path(__file__).with_name("assets")
    if longest_days <= 30:
        return asset_dir / "nukazuke-pixel-30.png", "浅漬かり（30日以下）"
    if longest_days <= 60:
        return asset_dir / "nukazuke-pixel-60.png", "中漬かり（60日以下）"
    return asset_dir / "nukazuke-pixel-90.png", "深漬かり（90日級）"


def render_nukazuke_summary(streaks: pd.DataFrame) -> None:
    longest_days = int(streaks["下回った日数"].max())
    illustration, stage_label = get_nukazuke_stage(longest_days)
    longest_days_color = "#2563EB" if longest_days <= 60 else "#DC2626"
    st.markdown(
        f"""
        <style>
        .st-key-nukazuke_summary [data-testid="stColumn"]:nth-child(2)
        [data-testid="stMetricValue"] {{
            color: {longest_days_color} !important;
            font-weight: 700 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="nukazuke_summary"):
        count_col, longest_col, illustration_col = st.columns([1, 1, 1.15], gap="small")
        count_col.metric("塩漬け", f"{len(streaks)}回")
        longest_col.metric("最長塩漬け", f"{longest_days}日")
        illustration_col.image(
            illustration,
            caption=stage_label,
            width=195,
        )


def render_company_info(company_name: str, ticker: str, info: dict) -> None:
    st.subheader("企業情報・会社規模")
    market_cap = info.get("marketCap")
    col1, col2, col3 = st.columns(3)
    col1.metric("企業名", company_name)
    col2.metric("時価総額", format_market_cap(market_cap))
    col3.metric("会社規模", classify_company_size(market_cap))

    details = [f"**証券コード:** {ticker.removesuffix('.T')}"]
    if info.get("fullTimeEmployees"):
        details.append(f"**従業員数:** {info['fullTimeEmployees']:,}人")
    st.markdown("　｜　".join(details))

    website = info.get("website")
    if website:
        st.link_button("公式サイト", website)
    if not info:
        st.caption(f"{ticker} の企業情報を取得できませんでした。")


def render_app_banners(
    security_code: str, key_prefix: str = "desktop", start_year: int | None = None
) -> None:
    """Show equal-size links to both stock tools and carry the company code."""
    assets = Path(__file__).with_name("assets")
    threshold = int(st.session_state.get(f"{key_prefix}_threshold", 320))
    use_current = bool(st.session_state.get(f"{key_prefix}_use_current_price", True))
    use_shallow = bool(st.session_state.get(f"{key_prefix}_light_pickling_price", False))
    if start_year is None:
        start_year = int(st.session_state.get(f"{key_prefix}_start_year_v2", 2015))
    reference_years = min(20, max(1, date.today().year - int(start_year)))
    common = f"app_code={escape(security_code, quote=True)}"
    nanpin_query = f"?{common}&amp;app_reference_years={reference_years}"
    salt_query = (
        f"?{common}&amp;app_threshold={threshold}&amp;app_current={int(use_current)}"
        f"&amp;app_shallow={int(use_shallow)}&amp;app_start_year={int(start_year)}"
    )
    banner_items = [
        (assets / "absolute-safe-nanpin-banner.png", f"http://127.0.0.1:8769/{nanpin_query}", "絶対安全ナンピン君"),
        (assets / "stock-bottom-days-banner.png", f"/{salt_query}", "塩漬け日数チェッカー"),
    ]
    cards = []
    for image_path, destination, label in banner_items:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        cards.append(
            f'<a class="app-banner" href="{destination}" target="_self" '
            f'aria-label="{label}"><img src="data:image/png;base64,{encoded}" '
            f'alt="{label}"></a>'
        )
    st.markdown(
        '<div class="app-banner-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


@st.cache_data
def load_company_options() -> list[str]:
    companies = pd.read_csv(
        Path(__file__).with_name("companies.csv"), dtype={"code": str}
    )
    return [f"{row.code}｜{row.name}" for row in companies.itertuples(index=False)]


def calculate_light_pickling_rankings(
    start_date: date, end_date: date, *, revision=None, manifest=None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    tickers = [f"{code}.T" for code in NIKKEI225_CODES]
    if revision is None:
        revision, manifest = saved_snapshot()
    raw = saved_ranking_frame(revision, manifest["ranking"])
    raw = raw.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
    company_names = {
        option.split("｜", 1)[0]: option.split("｜", 1)[1]
        for option in load_company_options()
    }
    rows = []
    for code, ticker in zip(NIKKEI225_CODES, tickers):
        try:
            ticker_raw = raw[ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
            prices = normalize_prices(ticker_raw)
            current_prices = prices["Close"].dropna()
            if current_prices.empty:
                continue
            current_price = float(current_prices.iloc[-1])
            three_year_cutoff = pd.Timestamp(end_date) - pd.DateOffset(years=3)
            older_highs = prices.loc[
                prices.index < three_year_cutoff, "High"
            ].dropna()
            streaks = find_streaks(prices, "Low", current_price)
            if streaks.empty:
                continue
            longest_days = int(streaks["下回った日数"].max())
            lowest_price = float(streaks["期間中最安値（円）"].min())
            ranking_lowest_price = float(prices["Low"].dropna().min())
            lowest_change_percent = (ranking_lowest_price / current_price - 1) * 100
            rounded_current = Decimal(str(current_price)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            rows.append(
                {
                    "最長塩漬け期間": f"{longest_days}日",
                    "銘柄": company_names.get(code, code),
                    "_証券コード": code,
                    "株価": f"{rounded_current:,}円",
                    "塩漬け回数": f"{len(streaks)}回",
                    "最安値": format_price_with_change(lowest_price, current_price),
                    "_最安値表示": format_price_with_change(
                        ranking_lowest_price, current_price
                    ),
                    "_最長日数": longest_days,
                    "_最安値騰落率": lowest_change_percent,
                    "_塩漬け順位対象": (
                        not older_highs.empty
                        and float(older_highs.max()) > current_price
                    ),
                }
            )
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    if not rows:
        empty_ranking = pd.DataFrame(
            columns=["最長塩漬け期間", "銘柄", "株価", "塩漬け回数", "最安値"]
        )
        return empty_ranking, empty_ranking.copy()

    all_rankings = pd.DataFrame(rows)
    duration_ranking = (
        all_rankings.loc[all_rankings["_塩漬け順位対象"]]
        .sort_values(["_最長日数", "銘柄"], ascending=[True, True])
        .head(10)
        .reset_index(drop=True)
    )
    lowest_price_ranking = (
        all_rankings.sort_values(
            ["_最安値騰落率", "銘柄"], ascending=[False, True]
        )
        .head(10)
        .reset_index(drop=True)
    )

    def finish_ranking(
        ranking: pd.DataFrame, use_all_period_lowest: bool = False
    ) -> pd.DataFrame:
        ranking = ranking.copy()
        if use_all_period_lowest:
            ranking["最安値"] = ranking["_最安値表示"]
        ranking["銘柄"] = ranking.apply(
            lambda row: (
                f'<a href="?ranking_code={row["_証券コード"]}'
                f'&ranking_start={start_date.year}" target="_self">'
                f'{escape(str(row["銘柄"]))}</a>'
            ),
            axis=1,
        )
        return ranking.drop(
            columns=[
                "_最長日数",
                "_最安値騰落率",
                "_最安値表示",
                "_塩漬け順位対象",
                "_証券コード",
            ]
        )

    finished_lowest_price_ranking = finish_ranking(
        lowest_price_ranking, use_all_period_lowest=True
    )[
        ["最安値", "銘柄", "最長塩漬け期間", "株価", "塩漬け回数"]
    ]
    return finish_ranking(duration_ranking), finished_lowest_price_ranking


def latest_ranking_refresh_date(now: datetime | None = None) -> date:
    """Return the latest weekday whose 16:00 JST refresh time has passed."""
    current = now.astimezone(JAPAN_TIMEZONE) if now else datetime.now(JAPAN_TIMEZONE)
    refresh_date = current.date()
    if current.weekday() < 5 and current.time() < RANKING_REFRESH_TIME:
        refresh_date -= timedelta(days=1)
    while refresh_date.weekday() >= 5:
        refresh_date -= timedelta(days=1)
    return refresh_date


@st.cache_resource
def ranking_cache_state() -> dict:
    return {"lock": threading.Lock(), "entries": None}


def load_ranking_cache() -> dict:
    try:
        stored = json.loads(RANKING_CACHE_FILE.read_text(encoding="utf-8"))
        return stored if isinstance(stored, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return {}


def save_ranking_cache(entries: dict) -> None:
    temporary_file = RANKING_CACHE_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps(entries, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary_file.replace(RANKING_CACHE_FILE)


def get_light_pickling_ranking(
    start_date: date, requested_end_date: date
) -> tuple[pd.DataFrame, pd.DataFrame, date, bool]:
    """Refresh once after 16:00 JST on weekdays and reuse the saved ranking."""
    revision, manifest = saved_snapshot()
    if not manifest.get("ranking"):
        raise RuntimeError("ランキング用データの初回更新がまだ完了していません。")
    refresh_date = date.fromisoformat(manifest["ranking"]["as_of"])
    effective_end_date = min(requested_end_date, refresh_date)
    cache_key = f"snapshot-v1:{revision}:{start_date.isoformat()}:{effective_end_date.isoformat()}"
    state = ranking_cache_state()

    with state["lock"]:
        if state["entries"] is None:
            state["entries"] = load_ranking_cache()
        cached = state["entries"].get(cache_key)
        if (
            isinstance(cached, dict)
            and isinstance(cached.get("duration_records"), list)
            and isinstance(cached.get("lowest_price_records"), list)
            and (cached["duration_records"] or cached["lowest_price_records"])
        ):
            duration_ranking = pd.DataFrame(
                cached["duration_records"],
                columns=cached.get("duration_columns"),
            )
            lowest_price_ranking = pd.DataFrame(
                cached["lowest_price_records"],
                columns=cached.get("lowest_price_columns"),
            )
            return duration_ranking, lowest_price_ranking, refresh_date, False

        duration_ranking, lowest_price_ranking = calculate_light_pickling_rankings(
            start_date, effective_end_date, revision=revision, manifest=manifest
        )
        if duration_ranking.empty and lowest_price_ranking.empty:
            raise RuntimeError(
                "株価データを取得できませんでした。通信状態を確認して再度お試しください。"
                "取得失敗の結果は保存していません。"
            )
        state["entries"][cache_key] = {
            "updated_at": datetime.now(JAPAN_TIMEZONE).isoformat(timespec="seconds"),
            "refresh_date": refresh_date.isoformat(),
            "start_date": start_date.isoformat(),
            "end_date": effective_end_date.isoformat(),
            "duration_columns": list(duration_ranking.columns),
            "duration_records": duration_ranking.to_dict(orient="records"),
            "lowest_price_columns": list(lowest_price_ranking.columns),
            "lowest_price_records": lowest_price_ranking.to_dict(orient="records"),
        }
        # Keep recent records only so the cache file does not grow without bound.
        state["entries"] = dict(list(state["entries"].items())[-30:])
        try:
            save_ranking_cache(state["entries"])
        except OSError:
            # The process-wide cache still prevents repeated aggregation if disk
            # persistence is temporarily unavailable.
            pass
        return duration_ranking, lowest_price_ranking, refresh_date, True


def add_desktop_search_history(search_values) -> None:
    security_code, threshold, use_current_price, light_pickling_price, start_date, _, _ = search_values
    company_label = next(
        (
            option
            for option in load_company_options()
            if option.startswith(f"{security_code}｜")
        ),
        security_code,
    )
    entry = {
        "company": company_label,
        "threshold": int(threshold),
        "use_current_price": use_current_price,
        "light_pickling_price": light_pickling_price,
        "start_year": start_date.year,
    }
    history = get_desktop_search_history()
    updated_history = [entry, *(item for item in history if item != entry)][:5]
    st.session_state.desktop_search_history = updated_history
    SEARCH_HISTORY_FILE.write_text(
        json.dumps(updated_history, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    cookie_value = base64.urlsafe_b64encode(
        json.dumps(updated_history, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).decode("ascii")
    components.html(
        f"""
        <script>
        const secure = window.parent.location.protocol === "https:" ? "; Secure" : "";
        window.parent.document.cookie =
            {json.dumps(SEARCH_HISTORY_COOKIE + "=" + cookie_value)} +
            "; Max-Age=31536000; Path=/; SameSite=Lax" + secure;
        </script>
        """,
        height=0,
    )


def get_desktop_search_history() -> list[dict]:
    if "desktop_search_history" in st.session_state:
        return st.session_state.desktop_search_history
    try:
        cookie_value = st.context.cookies.get(SEARCH_HISTORY_COOKIE, "")
        if cookie_value:
            padding = "=" * (-len(cookie_value) % 4)
            saved_history = json.loads(
                base64.urlsafe_b64decode(cookie_value + padding).decode("utf-8")
            )
        else:
            saved_history = (
                json.loads(SEARCH_HISTORY_FILE.read_text(encoding="utf-8"))
                if SEARCH_HISTORY_FILE.exists()
                else []
            )
        required_keys = {"company", "threshold", "use_current_price", "start_year"}
        history = (
            [
                entry
                for entry in saved_history
                if isinstance(entry, dict) and required_keys.issubset(entry)
            ]
            if isinstance(saved_history, list)
            else []
        )
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        history = []
    st.session_state.desktop_search_history = history[:5]
    return st.session_state.desktop_search_history


def restore_search(entry: dict, key_prefix: str) -> None:
    st.session_state[f"{key_prefix}_company"] = entry["company"]
    st.session_state[f"{key_prefix}_threshold"] = int(entry["threshold"])
    st.session_state[f"{key_prefix}_use_current_price"] = bool(
        entry["use_current_price"]
    )
    st.session_state[f"{key_prefix}_light_pickling_price"] = bool(
        entry.get("light_pickling_price", False)
    )
    st.session_state[f"{key_prefix}_start_year_v2"] = int(entry["start_year"])
    st.session_state[f"{key_prefix}_history_run"] = True


def render_search_history(key_prefix: str) -> None:
    st.markdown("### 検索履歴")
    history = get_desktop_search_history()
    if not history:
        st.caption("検索履歴はありません。")
        return
    for index, entry in enumerate(history):
        company_name = entry["company"].split("｜", 1)[-1]
        price_label = (
            "浅漬け株価"
            if entry.get("light_pickling_price", False)
            else "現在の株価"
            if entry["use_current_price"]
            else f"{entry['threshold']:,.0f}円以下"
        )
        st.button(
            f"{company_name}\n{price_label}｜{entry['start_year']}年1月～",
            key=f"{key_prefix}_history_{index}",
            on_click=restore_search,
            args=(entry, key_prefix),
            use_container_width=True,
        )


def render_results_table(
    styled_table, height: int, limit_vertical_height: bool = True
) -> None:
    table_html = styled_table.hide(axis="index").to_html()
    height_style = f"max-height:{min(height, 620)}px" if limit_vertical_height else ""
    st.markdown(
        f'<div class="results-table-scroll" '
        f'style="{height_style}">{table_html}</div>',
        unsafe_allow_html=True,
    )


def select_price_mode(key_prefix: str, selected_mode: str) -> None:
    selected_key = f"{key_prefix}_{selected_mode}"
    if not st.session_state.get(selected_key, False):
        return
    current_key = f"{key_prefix}_use_current_price"
    light_key = f"{key_prefix}_light_pickling_price"
    if selected_mode == "use_current_price":
        st.session_state[light_key] = False
    elif st.session_state.get(current_key, False):
        st.session_state[light_key] = False


def render_search_controls(
    key_prefix: str,
    show_end_date: bool = True,
    start_date_label: str = "開始日",
    current_price_after_dates: bool = False,
):
    company_options = load_company_options()
    default_index = next(
        (index for index, option in enumerate(company_options) if option.startswith("7201｜")),
        0,
    )
    selected_company = st.selectbox(
        "企業名",
        options=company_options,
        index=default_index,
        key=f"{key_prefix}_company",
        format_func=lambda option: option.split("｜", 1)[-1],
        accept_new_options=False,
        help="企業名を入力して、候補から選択してください。",
    )
    security_code = selected_company.split("｜", 1)[0].strip().upper()
    threshold = st.number_input(
        "この価格以下の塩漬け期間を調べます",
        min_value=0,
        value=320,
        step=1,
        key=f"{key_prefix}_threshold",
    )
    if not current_price_after_dates:
        use_current_price = st.checkbox(
            "現在の株価",
            value=True,
            key=f"{key_prefix}_use_current_price",
            on_change=select_price_mode,
            args=(key_prefix, "use_current_price"),
        )
        light_pickling_price = st.checkbox(
            "浅漬け株価",
            value=False,
            key=f"{key_prefix}_light_pickling_price",
            on_change=select_price_mode,
            args=(key_prefix, "light_pickling_price"),
        )
        st.markdown(
            '<div class="light-pickling-note">※塩漬けを避ける株価が分かります</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="start-date-spacer"></div>', unsafe_allow_html=True)
    end_date = (
        st.date_input("終了日", value=date.today(), key=f"{key_prefix}_end")
        if show_end_date
        else date.today()
    )
    start_year = st.selectbox(
        start_date_label,
        options=START_YEAR_OPTIONS,
        index=START_YEAR_OPTIONS.index(2015),
        format_func=lambda year: f"{year}年1月～",
        key=f"{key_prefix}_start_year_v2",
    )
    start_date = date(start_year, 1, 1)
    if current_price_after_dates:
        use_current_price = st.checkbox(
            "現在の株価",
            value=True,
            key=f"{key_prefix}_use_current_price",
            on_change=select_price_mode,
            args=(key_prefix, "use_current_price"),
        )
        light_pickling_price = st.checkbox(
            "浅漬け株価",
            value=False,
            key=f"{key_prefix}_light_pickling_price",
            on_change=select_price_mode,
            args=(key_prefix, "light_pickling_price"),
        )
        st.markdown(
            '<div class="light-pickling-note">※塩漬けを避ける株価が分かります</div>',
            unsafe_allow_html=True,
        )
    run = st.button(
        "集計する", type="primary", use_container_width=True, key=f"{key_prefix}_run"
    )
    if key_prefix == "desktop":
        st.button(
            "最安値ランキング",
            type="primary",
            use_container_width=True,
            key=f"{key_prefix}_light_pickling_ranking",
        )
    return (
        security_code,
        threshold,
        use_current_price,
        light_pickling_price,
        start_date,
        end_date,
        run,
    )


def scroll_to_result(anchor_id: str) -> None:
    """Scroll the app to a completed result section."""
    encoded_anchor = json.dumps(anchor_id)
    components.html(
        f"""
        <script>
        (() => {{
            if (!window.parent.matchMedia("(max-width: 768px)").matches) return;
            const anchorId = {encoded_anchor};
            let attempts = 0;
            const scrollWhenReady = () => {{
                try {{
                    const target = window.parent.document.getElementById(anchorId);
                    if (target) {{
                        target.scrollIntoView({{ behavior: "smooth", block: "start" }});
                        return;
                    }}
                }} catch (_) {{
                    return;
                }}
                attempts += 1;
                if (attempts < 20) window.setTimeout(scrollWhenReady, 100);
            }};
            window.setTimeout(scrollWhenReady, 100);
        }})();
        </script>
        """,
        height=0,
    )


st.set_page_config(page_title="塩漬け日数チェッカー", page_icon="📉", layout="wide")

# Older versions stored search history in the URL. Remove that legacy parameter
# now that history is persisted locally, so the address always stays clean.
if "history" in st.query_params:
    del st.query_params["history"]

# ランキングの企業名リンクから、同じ企業を現在値で自動集計する。
ranking_code = str(st.query_params.get("ranking_code", "")).strip().upper()
if ranking_code:
    ranking_company = next(
        (
            option
            for option in load_company_options()
            if option.split("｜", 1)[0].strip().upper() == ranking_code
        ),
        None,
    )
    if ranking_company:
        try:
            ranking_start_year = int(st.query_params.get("ranking_start", 2015))
        except (TypeError, ValueError):
            ranking_start_year = 2015
        if ranking_start_year not in START_YEAR_OPTIONS:
            ranking_start_year = 2015
        for prefix in ("mobile", "desktop"):
            st.session_state[f"{prefix}_company"] = ranking_company
            st.session_state[f"{prefix}_use_current_price"] = True
            st.session_state[f"{prefix}_light_pickling_price"] = False
            st.session_state[f"{prefix}_start_year_v2"] = ranking_start_year
        st.session_state["ranking_company_run"] = True
    del st.query_params["ranking_code"]
    if "ranking_start" in st.query_params:
        del st.query_params["ranking_start"]

# バナーから移動した場合は、同じ企業をこのアプリの初期設定で自動集計する。
linked_company_code = str(st.query_params.get("app_code", "")).strip().upper()
if linked_company_code:
    linked_company = next(
        (
            option
            for option in load_company_options()
            if option.split("｜", 1)[0].strip().upper() == linked_company_code
        ),
        None,
    )
    if linked_company:
        def linked_int(name: str, default: int) -> int:
            try:
                return int(float(st.query_params.get(name, default)))
            except (TypeError, ValueError):
                return default

        threshold = max(0, linked_int("app_threshold", 320))
        use_current = bool(linked_int("app_current", 1))
        use_shallow = bool(linked_int("app_shallow", 0))
        requested_start_year = linked_int("app_start_year", 2015)
        start_year = min(START_YEAR_OPTIONS, key=lambda year: abs(year - requested_start_year))
        for prefix in ("mobile", "desktop"):
            st.session_state[f"{prefix}_company"] = linked_company
            st.session_state[f"{prefix}_threshold"] = threshold
            st.session_state[f"{prefix}_use_current_price"] = use_current
            st.session_state[f"{prefix}_light_pickling_price"] = use_shallow
            st.session_state[f"{prefix}_start_year_v2"] = start_year
        st.session_state["ranking_company_run"] = True
    del st.query_params["app_code"]
    for linked_param in ("app_threshold", "app_current", "app_shallow", "app_start_year"):
        if linked_param in st.query_params:
            del st.query_params[linked_param]
components.html(
    """
    <script>
    function markAsJapanese(page) {
        page.documentElement.lang = "ja";
        page.documentElement.setAttribute("translate", "no");
        page.documentElement.classList.add("notranslate");
        if (page.body) {
            page.body.lang = "ja";
            page.body.setAttribute("translate", "no");
            page.body.classList.add("notranslate");
        }
        if (!page.head.querySelector('meta[name="google"]')) {
            const meta = page.createElement("meta");
            meta.name = "google";
            meta.content = "notranslate";
            page.head.appendChild(meta);
        }
    }
    for (const target of [window.parent, window.top]) {
        try {
            markAsJapanese(target.document);
        } catch (_) {
            // A cross-origin outer frame cannot be changed from the app.
        }
    }
    </script>
    """,
    height=0,
)
st.markdown(
    """
    <style>
    .st-key-mobile_filters { display: none; }
    .st-key-mobile_ranking_controls { display: none; }
    .st-key-mobile_results_table { display: none; }
    .st-key-mobile_search_history { display: none; }
    .st-key-mobile_full_period_graph { display: none; }
    .recent-period-short { display: none; }
    .recent-assessment-desktop { display: none; }
    .recent-assessment-mobile { display: block; }
    .review-statistics-line,
    .review-card-note { display: none; }
    .st-key-nukazuke_summary {
        max-width: 680px;
    }
    .st-key-nukazuke_summary img {
        max-width: 100%;
        height: auto;
    }
    .st-key-nukazuke_summary [data-testid="stMetricLabel"] p {
        font-size: 1.5rem !important;
        font-weight: 700 !important;
        line-height: 1.25;
        text-align: center;
    }
    .st-key-nukazuke_summary [data-testid="stMetricLabel"] {
        justify-content: center;
        width: 100%;
    }
    .st-key-nukazuke_summary [data-testid="stMetric"] {
        width: fit-content;
        min-width: 158px;
        padding: 1rem 1.25rem;
        background: linear-gradient(145deg, #FFFFFF 0%, #F8FAFC 100%);
        border: 1px solid #D8E1EC;
        border-radius: 14px;
        box-shadow: 0 7px 20px rgba(15, 23, 42, 0.09);
        overflow: hidden;
    }
    .st-key-nukazuke_summary [data-testid="stMetricValue"] {
        justify-content: center;
        text-align: center;
    }
    .st-key-nukazuke_summary [data-testid="stColumn"]:nth-child(1)
    [data-testid="stMetricValue"] {
        color: #111111 !important;
        font-weight: 700 !important;
    }
    .st-key-desktop_results_table [role="columnheader"],
    .st-key-mobile_results_table [role="columnheader"] {
        color: #111111 !important;
        font-weight: 700 !important;
    }
    .st-key-desktop_ranking_table .results-table-scroll th,
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th {
        background: #FCE3D2 !important;
    }
    .st-key-desktop_ranking_table,
    .st-key-desktop_lowest_price_ranking_table {
        max-width: 760px;
    }
    .st-key-desktop_ranking_table .results-table-scroll table,
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll table {
        min-width: 0;
        table-layout: fixed;
    }
    .st-key-desktop_ranking_table .results-table-scroll th,
    .st-key-desktop_ranking_table .results-table-scroll td,
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th,
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td {
        padding: 0.5rem 0.45rem;
        white-space: normal;
        overflow-wrap: anywhere;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(1),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(1),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(1),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(1) {
        width: 18%;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(2),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(2),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(2),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(2) {
        width: 32%;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(3),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(3),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(3),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(3) {
        width: 14%;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(4),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(4),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(4),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(4) {
        width: 15%;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(5),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(5),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(5),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(5) {
        width: 20%;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(1),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(1) { width: 17%; }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(2),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(2) { width: 29%; }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(3),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(3) { width: 13%; }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(4),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(4) { width: 14%; }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(5),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(5) { width: 27%; }
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(1),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(1) { width: 27%; }
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(2),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(2) { width: 29%; }
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(3),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(3) { width: 20%; }
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(4),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(4) { width: 13%; }
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(5),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(5) { width: 11%; }
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(5),
    .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(1) {
        white-space: nowrap;
        overflow-wrap: normal;
    }
    .ranking-lowest-price,
    .ranking-lowest-change,
    .ranking-lowest-paren {
        display: inline;
    }
    .results-table-scroll {
        width: 100%;
        overflow: auto;
        border: 1px solid #AEB5BF;
        border-radius: 0.55rem;
    }
    .results-table-scroll table {
        width: 100%;
        min-width: 720px;
        border-collapse: collapse;
        font-size: 0.9rem;
    }
    .results-table-scroll th {
        position: sticky;
        top: 0;
        z-index: 1;
        padding: 0.65rem 0.55rem;
        color: #111111 !important;
        background: #DDE1E7 !important;
        border: 1px solid #AEB5BF;
        font-weight: 700 !important;
        text-align: left;
        white-space: nowrap;
    }
    .results-table-scroll td {
        padding: 0.55rem;
        border: 1px solid #AEB5BF;
        white-space: nowrap;
    }
    .light-pickling-headings {
        margin-bottom: 2rem;
    }
    .light-pickling-note {
        margin-top: -0.8rem;
        color: #6B7280;
        font-size: 0.72rem;
        line-height: 1.15;
    }
    .start-date-spacer {
        height: 1rem;
    }
    .light-pickling-headings h3 {
        margin: 0 !important;
        line-height: 1.05;
    }
    .light-pickling-headings h3 + h3 {
        margin-top: 0 !important;
    }
    .light-pickling-result-note {
        margin: 0.35rem 0 0 !important;
        color: #8A919C;
        font-size: 0.78rem;
        font-weight: 400;
        line-height: 1.25;
    }
    .app-banner-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1rem;
        margin: 1.4rem 0;
        max-width: 860px;
    }
    .app-banner {
        display: flex;
        height: 90px;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        background: #FFFFFF;
        border: 2px solid #AEB5BF;
        border-radius: 0.65rem;
        box-sizing: border-box;
    }
    .app-banner:hover { border-color: #2563EB; }
    .app-banner img {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: contain;
    }
    .st-key-desktop_initial_banners { margin-top: 36vh; }
    .app-title {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        width: fit-content;
        margin: 0 0 1.4rem;
        font-family: "Hiragino Maru Gothic ProN", "Yu Gothic", sans-serif;
        font-size: clamp(2.25rem, 4vw, 3.25rem);
        font-weight: 900;
        line-height: 1.25;
        letter-spacing: 0.03em;
        color: #6f451f;
        text-shadow:
            0 3px 0 #f2d49b,
            2px 5px 0 rgba(75, 48, 22, 0.12);
    }
    .app-title::before,
    .app-title::after {
        font-size: 0.72em;
        filter: drop-shadow(0 2px 1px rgba(75, 48, 22, 0.18));
    }
    .app-title::before { content: "🥒"; transform: rotate(-12deg); }
    .app-title::after { content: "🥒"; transform: rotate(12deg); }
    .app-subtitle {
        max-width: 680px;
        margin: -1rem 0 2.5rem;
        color: #111111;
        font-size: 0.95rem;
        font-weight: 500;
        text-align: center;
    }
    .stAppViewBlockContainer { padding-bottom: 5rem; }
    .app-footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        z-index: 999;
        padding: 0.65rem 1rem;
        text-align: center;
        background: color-mix(in srgb, var(--background-color) 94%, transparent);
        border-top: 1px solid rgba(128, 128, 128, 0.25);
        backdrop-filter: blur(8px);
    }
    @media (max-width: 768px) {
        .app-banner-grid {
            grid-template-columns: 1fr;
            gap: 0.7rem;
            margin: 1rem 0 1.4rem;
        }
        .app-banner { height: 76px; }
        .st-key-desktop_initial_banners { display: none; }
        .stAppViewBlockContainer,
        .stMainBlockContainer,
        [data-testid="stAppViewBlockContainer"] {
            padding-top: 2.5rem !important;
        }
        .st-key-mobile_filters { display: block; }
        .st-key-mobile_ranking_controls { display: block; }
        .st-key-desktop_ranking_table .results-table-scroll table,
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll table {
            font-size: clamp(0.62rem, 2.7vw, 0.75rem);
        }
        .st-key-desktop_ranking_table .results-table-scroll th:nth-child(1),
        .st-key-desktop_ranking_table .results-table-scroll td:nth-child(1) { width: 17%; }
        .st-key-desktop_ranking_table .results-table-scroll th:nth-child(2),
        .st-key-desktop_ranking_table .results-table-scroll td:nth-child(2) { width: 29%; }
        .st-key-desktop_ranking_table .results-table-scroll th:nth-child(3),
        .st-key-desktop_ranking_table .results-table-scroll td:nth-child(3) { width: 13%; }
        .st-key-desktop_ranking_table .results-table-scroll th:nth-child(4),
        .st-key-desktop_ranking_table .results-table-scroll td:nth-child(4) { width: 14%; }
        .st-key-desktop_ranking_table .results-table-scroll th:nth-child(5),
        .st-key-desktop_ranking_table .results-table-scroll td:nth-child(5) { width: 27%; }
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(1),
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(1) { width: 27%; }
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(2),
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(2) { width: 29%; }
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(3),
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(3) { width: 20%; }
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(4),
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(4) { width: 13%; }
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll th:nth-child(5),
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(5) { width: 11%; }
        .st-key-desktop_ranking_table .results-table-scroll td:nth-child(3),
        .st-key-desktop_ranking_table .results-table-scroll td:nth-child(4),
        .st-key-desktop_ranking_table .results-table-scroll td:nth-child(5),
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(1),
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(4),
        .st-key-desktop_lowest_price_ranking_table .results-table-scroll td:nth-child(5) {
            white-space: nowrap;
            overflow-wrap: normal;
        }
        .ranking-lowest-price,
        .ranking-lowest-change {
            display: block;
        }
        .ranking-lowest-paren {
            display: none;
        }
        .mobile-ranking-note {
            margin: 0.45rem 0 0.9rem;
            color: #111111;
            font-size: 0.875rem;
            line-height: 1.5;
            text-align: center;
        }
        .st-key-nukazuke_summary {
            max-width: 100%;
        }
        .st-key-nukazuke_summary [data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: center;
            gap: 0.5rem !important;
        }
        .st-key-nukazuke_summary [data-testid="stColumn"] {
            flex: 1 1 0 !important;
            width: 0 !important;
            min-width: 0 !important;
        }
        .st-key-nukazuke_summary [data-testid="stColumn"]:nth-child(1),
        .st-key-nukazuke_summary [data-testid="stColumn"]:nth-child(2) {
            flex: 0 1 30% !important;
            width: 30% !important;
        }
        .st-key-nukazuke_summary [data-testid="stColumn"]:nth-child(3) {
            flex: 0 1 36% !important;
            width: 36% !important;
        }
        .st-key-nukazuke_summary [data-testid="stMetric"] {
            width: 100%;
            min-width: 0;
            padding: 0.75rem 0.2rem;
        }
        .st-key-nukazuke_summary [data-testid="stMetricLabel"] p {
            font-size: clamp(0.8rem, 3.7vw, 1rem) !important;
            white-space: nowrap;
        }
        .st-key-nukazuke_summary [data-testid="stMetricValue"] {
            font-size: clamp(1.6rem, 7vw, 2rem) !important;
        }
        .st-key-nukazuke_summary [data-testid="stImage"] {
            width: 100% !important;
            max-width: 100% !important;
            text-align: center;
        }
        .st-key-nukazuke_summary [data-testid="stImage"] > div,
        .st-key-nukazuke_summary [data-testid="stImage"] figure {
            width: 100% !important;
            max-width: 100% !important;
        }
        .st-key-nukazuke_summary [data-testid="stImage"] img {
            width: 100% !important;
            max-width: 100% !important;
            object-fit: contain;
        }
        .st-key-nukazuke_summary [data-testid="stImage"] small {
            font-size: clamp(0.68rem, 2.8vw, 0.8rem);
            white-space: nowrap;
        }
        .app-title {
            gap: 0.2rem;
            margin-bottom: 1.1rem;
            font-size: clamp(1.45rem, 6.3vw, 2rem);
            white-space: nowrap;
        }
        .app-subtitle {
            max-width: 100%;
            margin-top: -0.75rem;
            font-size: 0.9rem;
        }
        .st-key-mobile_use_current_price {
            width: fit-content;
            margin: 0.75rem 0 1rem auto;
        }
        .st-key-mobile_use_current_price [data-testid="stWidgetLabel"] p {
            font-size: 1.5rem !important;
            font-weight: 700 !important;
            line-height: 1.2;
        }
        .st-key-mobile_use_current_price [data-testid="stCheckbox"] label > div:first-of-type {
            transform: scale(1.5);
            transform-origin: center;
            margin-right: 0.5rem;
        }
        .st-key-mobile_light_pickling_price {
            width: fit-content;
            margin: -0.35rem 0 0 auto;
        }
        .st-key-mobile_light_pickling_price [data-testid="stWidgetLabel"] p {
            font-size: 1.5rem !important;
            font-weight: 700 !important;
            line-height: 1.2;
        }
        .st-key-mobile_light_pickling_price [data-testid="stCheckbox"] label > div:first-of-type {
            transform: scale(1.5);
            transform-origin: center;
            margin-right: 0.5rem;
        }
        .st-key-mobile_filters .light-pickling-note {
            width: fit-content;
            margin: 0.4rem 0 0 auto;
            padding-bottom: 1.15rem;
            text-align: right;
        }
        .st-key-mobile_run {
            margin-top: 0.65rem;
        }
        .st-key-mobile_results_table .results-table-scroll {
            overflow-x: hidden;
        }
        .st-key-mobile_results_table .results-table-scroll table {
            width: 100%;
            min-width: 0;
            table-layout: fixed;
            font-size: clamp(0.62rem, 2.7vw, 0.76rem);
        }
        .st-key-mobile_results_table .results-table-scroll th,
        .st-key-mobile_results_table .results-table-scroll td {
            padding: 0.38rem 0.2rem;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .st-key-mobile_results_table .results-table-scroll th:nth-child(1),
        .st-key-mobile_results_table .results-table-scroll td:nth-child(1) {
            width: 31%;
        }
        .st-key-mobile_results_table .results-table-scroll th:nth-child(2),
        .st-key-mobile_results_table .results-table-scroll td:nth-child(2) {
            width: 18%;
        }
        .st-key-mobile_results_table .results-table-scroll th:nth-child(3),
        .st-key-mobile_results_table .results-table-scroll td:nth-child(3) {
            width: 23%;
        }
        .st-key-mobile_results_table .results-table-scroll th:nth-child(4),
        .st-key-mobile_results_table .results-table-scroll td:nth-child(4) {
            width: 28%;
        }
        .st-key-desktop_results_table { display: none; }
        .st-key-mobile_results_table { display: block; }
        .st-key-mobile_full_period_graph { display: block; }
        .st-key-desktop_full_period_graph { display: none; }
        .recent-period-long { display: none; }
        .recent-period-short { display: inline; }
        .recent-assessment-desktop { display: none; }
        .recent-assessment-mobile {
            display: block;
        }
        .review-statistics-line { display: none; }
        .full-period-title {
            margin-bottom: 0.75rem;
            font-size: 16px !important;
            line-height: 1.4;
            white-space: nowrap;
        }
        .review-card {
            font-size: 16px !important;
        }
        .review-card-title {
            font-size: 20px !important;
        }
        .review-card-grade {
            font-size: 15px !important;
        }
        .review-card-note {
            display: none;
        }
        .st-key-mobile_search_history {
            display: block;
            margin-top: 1.25rem;
        }
        section[data-testid="stSidebar"] { display: none; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="app-title" role="heading" aria-level="1">塩漬け日数チェッカー</div>',
    unsafe_allow_html=True,
)

with st.container(key="mobile_filters"):
    st.header("検索条件")
    mobile_values = render_search_controls(
        "mobile",
        show_end_date=False,
        start_date_label="検索開始日",
        current_price_after_dates=True,
    )
    if st.session_state.pop("mobile_history_run", False):
        mobile_values = (*mobile_values[:-1], True)
    if mobile_values[-1]:
        add_desktop_search_history(mobile_values)

st.markdown(
    '<div class="app-subtitle">'
    "購入しようとしている株価が、過去に何日塩漬けしたかが分かります。"
    "</div>",
    unsafe_allow_html=True,
)
with st.container(key="mobile_ranking_controls"):
    mobile_ranking_requested = st.button(
        "最安値ランキング",
        type="primary",
        use_container_width=True,
        key="mobile_light_pickling_ranking",
    )
    if not mobile_ranking_requested:
        st.markdown(
            '<div class="mobile-ranking-note">'
            "現在の株価から最安値までの下落率が小さいランキングを表示します。"
            "</div>",
            unsafe_allow_html=True,
        )
ranking_placeholder = st.empty()

with st.sidebar:
    st.header("検索条件")
    desktop_values = render_search_controls("desktop", show_end_date=False)
    if st.session_state.pop("desktop_history_run", False):
        desktop_values = (*desktop_values[:-1], True)
    if desktop_values[-1]:
        add_desktop_search_history(desktop_values)
    if not st.session_state.get("desktop_light_pickling_ranking", False):
        render_search_history("desktop")

if st.session_state.pop("ranking_company_run", False):
    desktop_values = (*desktop_values[:-1], True)
    add_desktop_search_history(desktop_values)

desktop_ranking_requested = st.session_state.get(
    "desktop_light_pickling_ranking", False
)
if mobile_ranking_requested or desktop_ranking_requested:
    st.markdown(
        """
        <style>
        /* A ranking is a standalone view. Hide stale search output that may
           remain below it when Streamlit stops the current rerun early. */
        .st-key-ranking_only_view ~ *,
        .stVerticalBlock > div:has(> .st-key-ranking_only_view) ~ * {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    ranking_values = mobile_values if mobile_ranking_requested else desktop_values
    ranking_start_date = ranking_values[4]
    ranking_end_date = ranking_values[5]
    with st.container(key="ranking_only_view"):
        try:
            with st.spinner("最安値ランキングを集計しています…"):
                (
                    shallow_ranking,
                    lowest_price_ranking,
                    ranking_refresh_date,
                    ranking_was_refreshed,
                ) = get_light_pickling_ranking(ranking_start_date, ranking_end_date)
            st.markdown(
                '<div id="ranking-results-anchor" style="scroll-margin-top: 4rem;"></div>',
                unsafe_allow_html=True,
            )
            st.subheader("最安値ランキング")
            show_saved_data_status(saved_snapshot()[1]["ranking"])
            st.markdown(
                '<div style="color:#111111; font-size:0.875rem; margin-bottom:0.75rem;">'
                "現在の株価で購入した場合、<br>"
                f"{format_month_ja(ranking_start_date)}～現在の最安値までの"
                "下落率が小さい順に並べています。"
                "</div>",
                unsafe_allow_html=True,
            )
            if lowest_price_ranking.empty:
                st.warning("ランキングを作成できる株価データがありませんでした。")
            else:
                render_ranking_table(
                    lowest_price_ranking,
                    "desktop_lowest_price_ranking_table",
                )
            st.subheader("浅漬けランキング")
            st.markdown(
                '<div style="color:#111111; font-size:0.875rem; margin-bottom:0.75rem;">'
                "現在の株価で購入した場合、<br>"
                f"{format_month_ja(ranking_start_date)}～現在の塩漬け期間が"
                "短い順に並べています。<br>"
                "過去3年以前の株価が今の株価を上回らなかった場合、"
                "現在高値圏の可能性があるためランキングから除外します。"
                "</div>",
                unsafe_allow_html=True,
            )
            if shallow_ranking.empty:
                st.warning("ランキングを作成できる株価データがありませんでした。")
            else:
                render_ranking_table(
                    shallow_ranking,
                    "desktop_ranking_table",
                    bold_longest=True,
                )
            st.caption("対象：日経平均225（日本経済新聞社公表銘柄）")
            st.caption(
                f"更新基準：{format_date_ja(ranking_refresh_date)} 16:00"
                + ("（更新済み）" if ranking_was_refreshed else "（保存済み）")
            )
            render_app_banners(
                ranking_values[0],
                "mobile" if mobile_ranking_requested else "desktop",
                ranking_values[4].year,
            )
            scroll_to_result("ranking-results-anchor")
        except (RuntimeError, ValueError, KeyError) as error:
            st.error(f"ランキングを作成できませんでした: {error}")
    st.stop()

with st.container(key="mobile_search_history"):
    render_search_history("mobile")
    render_app_banners(mobile_values[0], "mobile", mobile_values[4].year)
if not mobile_values[-1] and not desktop_values[-1]:
    with st.container(key="desktop_initial_banners"):
        render_app_banners(desktop_values[0], "desktop", desktop_values[4].year)
st.markdown(
    '<div class="app-footer">制作者：木星在住　'
    '<a href="https://x.com/mokuseidayo" target="_blank">Twitter</a></div>',
    unsafe_allow_html=True,
)

if mobile_values[-1]:
    security_code, threshold, use_current_price, light_pickling_price, start_date, end_date, run = mobile_values
    active_search_prefix = "mobile"
else:
    security_code, threshold, use_current_price, light_pickling_price, start_date, end_date, run = desktop_values
    active_search_prefix = "desktop"
if use_current_price:
    light_pickling_price = False
label = "安値"
column = "Low"

if run:
    if not security_code:
        st.error("証券コードを入力してください。")
        st.stop()
    if start_date > end_date:
        st.error("開始日は終了日以前にしてください。")
        st.stop()
    try:
        with st.spinner("株価データを準備しています…"):
            ticker = security_code if "." in security_code else f"{security_code}.T"
            prices = download_prices(ticker, start_date, end_date)
            end_date = min(end_date, prices.index[-1].date())
            light_pickling_days = None
            current_market_price = None
            if light_pickling_price:
                threshold, light_pickling_days = find_light_pickling_price(
                    prices, column, target_days=30
                )
                current_market_price = get_latest_close(prices)
            elif use_current_price:
                threshold = get_latest_close(prices)
            company_info = get_company_info(ticker)
            company_name = get_company_name(ticker, company_info)
        if column not in prices.columns:
            raise ValueError(f"{label}列がデータにありません。")

        st.markdown(
            '<div id="search-results-anchor" style="scroll-margin-top: 4rem;"></div>',
            unsafe_allow_html=True,
        )
        streaks = find_streaks(prices, column, threshold)
        show_saved_data_status(saved_snapshot()[1]["prices"][ticker])
        if light_pickling_price:
            st.info(
                f"浅漬け株価：{threshold:,.0f}円（最長{light_pickling_days}日）を基準にしています。"
            )
        if light_pickling_price:
            price_difference = current_market_price - threshold
            difference_percent = (
                abs(price_difference) / threshold * 100 if threshold else 0
            )
            if price_difference > 0:
                difference_html = (
                    f'浅漬け株価より<span style="color:#DC2626;">'
                    f"{difference_percent:.1f}％高い</span>です。"
                )
            elif price_difference < 0:
                difference_html = (
                    f'浅漬け株価より<span style="color:#2563EB;">'
                    f"{difference_percent:.1f}％安い</span>です。"
                )
            else:
                difference_html = "浅漬け株価と同じです。"
            st.markdown(
                '<div class="light-pickling-headings">'
                f"<h3>{format_month_ja(start_date)}から{format_month_ja(end_date)}まで"
                f"【{company_name}】の浅漬け価格は{threshold:,.0f}円です。</h3>"
                f"<h3>現在の株価は{current_market_price:,.0f}円です。"
                f"{difference_html}</h3>"
                '<p class="light-pickling-result-note">'
                "※浅漬け株価は長期塩漬けを避けるための買い時目安となります"
                "</p></div>",
                unsafe_allow_html=True,
            )
        else:
            st.subheader(
                f"{format_month_ja(start_date)}から{format_month_ja(end_date)}まで"
                f"{company_name}が{threshold:,.0f}円以下の塩漬け期間"
            )
        if streaks.empty:
            st.warning("該当する取引日はありませんでした。")
            recent_graph_slot = st.empty()
            full_graph_slot = st.empty()
        else:
            render_nukazuke_summary(streaks)
            recent_graph_slot = st.empty()
            full_graph_slot = st.empty()
            display_streaks = streaks.copy()
            display_streaks["開始日"] = display_streaks["開始日"].map(format_date_ja)
            display_streaks["終了日"] = display_streaks["終了日"].map(format_date_ja)
            latest_prices = prices[column].dropna()
            ongoing_rows = pd.Series(False, index=streaks.index)
            if (
                not use_current_price
                and not latest_prices.empty
                and latest_prices.iloc[-1] < threshold
            ):
                latest_date = latest_prices.index[-1].date()
                ongoing_rows = streaks["終了日"].eq(latest_date)
                display_streaks.loc[ongoing_rows, "終了日"] = "—"
            display_streaks["下回った日数"] = display_streaks["下回った日数"].map(
                lambda value: f"{int(value)}日"
            )
            display_streaks["期間中最安値（円）"] = display_streaks[
                "期間中最安値（円）"
            ].map(lambda value: format_price_with_change(value, threshold))
            next_high_column = f"次の{threshold:,.0f}円までの最高値（円）"
            display_streaks[next_high_column] = display_streaks[next_high_column].map(
                lambda value: format_price_with_change(value, threshold)
            )
            display_streaks.loc[ongoing_rows, next_high_column] = "現在塩漬中"
            cell_styles = pd.DataFrame(
                "", index=display_streaks.index, columns=display_streaks.columns
            )
            start_months = pd.to_datetime(streaks["開始日"]).dt.month
            even_month_rows = start_months.mod(2).eq(0)
            yellow_columns = ["開始日", "終了日", "下回った日数"]
            cell_styles.loc[even_month_rows, yellow_columns] = (
                "background-color: #FFFAE8;"
            )
            cell_styles.loc[~even_month_rows, yellow_columns] = (
                "background-color: #FFFDF5;"
            )
            cell_styles.loc[even_month_rows, "期間中最安値（円）"] = (
                "background-color: #FEF1F1;"
            )
            cell_styles.loc[~even_month_rows, "期間中最安値（円）"] = (
                "background-color: #FFF9F9;"
            )
            cell_styles.loc[even_month_rows, next_high_column] = (
                "background-color: #F2F7FF;"
            )
            cell_styles.loc[~even_month_rows, next_high_column] = (
                "background-color: #FAFCFF;"
            )
            longest_rows = streaks["下回った日数"].eq(
                streaks["下回った日数"].max()
            )
            cell_styles.loc[longest_rows, :] += " font-weight: 700;"
            cell_styles.loc[
                streaks["下回った日数"].gt(30), "下回った日数"
            ] += " color: #DC2626; font-weight: 700;"
            cell_styles.loc[
                streaks["下回った日数"].le(7), "下回った日数"
            ] += " color: #2563EB; font-weight: 700;"
            cell_styles.loc[
                streaks["期間中最安値（円）"].lt(threshold * 0.9),
                "期間中最安値（円）",
            ] += " color: #DC2626; font-weight: 700;"
            cell_styles.loc[
                streaks[next_high_column].gt(threshold * 1.1), next_high_column
            ] += " color: #2563EB; font-weight: 700;"
            cell_styles.loc[ongoing_rows, next_high_column] += (
                " color: #DC2626; font-weight: 700;"
            )
            table_height = 38 * (len(streaks) + 1) + 4
            with st.container(key="desktop_results_table"):
                desktop_column_names = {
                    "開始日": f"{threshold:,.0f}円塩漬開始日",
                    "下回った日数": "塩漬日数",
                    "期間中最安値（円）": "塩漬中最安値",
                    next_high_column: "塩漬後の最高値",
                }
                desktop_display = display_streaks.rename(columns=desktop_column_names)
                desktop_styles = cell_styles.rename(columns=desktop_column_names)
                styled_streaks = desktop_display.style.apply(
                    lambda _: desktop_styles, axis=None
                ).set_table_styles(TABLE_HEADER_STYLES)
                render_results_table(
                    styled_streaks, table_height, limit_vertical_height=False
                )

            with st.container(key="mobile_results_table"):
                mobile_column_names = {
                    "開始日": f"{threshold:,.0f}円塩漬開始日",
                    "下回った日数": "塩漬日数",
                    "期間中最安値（円）": "塩漬中最安値",
                    next_high_column: "塩漬後の最高値",
                }
                mobile_display = display_streaks.drop(columns=["終了日"]).rename(
                    columns=mobile_column_names
                )
                mobile_styles = cell_styles.drop(columns=["終了日"]).rename(
                    columns=mobile_column_names
                )
                styled_mobile = mobile_display.style.apply(
                    lambda _: mobile_styles, axis=None
                ).set_table_styles(TABLE_HEADER_STYLES)
                render_results_table(styled_mobile, table_height)
            csv = display_streaks.to_csv(index=False).encode("utf-8-sig")
            st.download_button("結果をCSVで保存", csv, "nissan_price_streaks.csv", "text/csv")
            render_app_banners(security_code, active_search_prefix, start_date.year)

        chart = prices[[column]].dropna().reset_index()
        chart.columns = ["日付", "株価"]
        tradeable_start = first_tradeable_date(prices, threshold)
        chart["基準以下"] = chart["株価"] <= threshold
        if tradeable_start is None:
            chart["基準以下"] = False
        else:
            chart["基準以下"] &= chart["日付"] >= tradeable_start
        changes = chart["基準以下"].ne(chart["基準以下"].shift()).cumsum()
        chart["連続区間"] = changes.where(chart["基準以下"])

        base = alt.Chart(chart).encode(
            x=alt.X(
                "日付:T",
                title=None,
                axis=alt.Axis(format="%Y年", tickCount="year", labelAngle=0),
                scale=alt.Scale(
                    domain=[pd.Timestamp(start_date), pd.Timestamp(end_date)]
                ),
            ),
            y=alt.Y("株価:Q", title=f"{label}（円）", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("日付:T", title="日付", format="%Y年%m月%d日"),
                alt.Tooltip("株価:Q", title=f"{label}（円）", format=",.2f"),
            ],
        )
        normal_line = base.mark_line(color="#2563EB", strokeWidth=2)
        below = base.transform_filter(alt.datum["基準以下"] == True)
        below_line = below.mark_line(color="#DC2626", strokeWidth=3).encode(
            detail="連続区間:N"
        )
        below_points = below.mark_circle(color="#DC2626", size=45)
        year_boundaries = pd.DataFrame(
            {
                "年初": pd.date_range(
                    start=pd.Timestamp(start_date).normalize(),
                    end=pd.Timestamp(end_date).normalize(),
                    freq="YS",
                )
            }
        )
        year_lines = alt.Chart(year_boundaries).mark_rule(
            color="#94A3B8", strokeWidth=1, opacity=0.45
        ).encode(x="年初:T")
        threshold_line = alt.Chart(pd.DataFrame({"基準価格": [threshold]})).mark_rule(
            color="#DC2626", strokeDash=[6, 4], opacity=0.65
        ).encode(y="基準価格:Q")
        recent_end = chart["日付"].max()
        recent_start = recent_end - pd.DateOffset(years=1)
        recent_chart = chart[chart["日付"] >= recent_start].copy()
        recent_base = alt.Chart(recent_chart).encode(
            x=alt.X(
                "日付:T",
                title=None,
                axis=alt.Axis(
                    format="%m月",
                    tickCount="month",
                    labelAngle=0,
                    labelOverlap=False,
                    domain=True,
                    domainColor="#94A3B8",
                    domainWidth=1,
                ),
                scale=alt.Scale(domain=[recent_start, recent_end]),
            ),
            y=alt.Y(
                "株価:Q",
                title=f"{label}（円）",
                axis=alt.Axis(
                    domain=True,
                    domainColor="#94A3B8",
                    domainWidth=1,
                ),
                scale=alt.Scale(zero=False),
            ),
            tooltip=[
                alt.Tooltip("日付:T", title="日付", format="%Y年%m月%d日"),
                alt.Tooltip("株価:Q", title=f"{label}（円）", format=",.2f"),
            ],
        )
        recent_normal_line = recent_base.mark_line(color="#2563EB", strokeWidth=2)
        recent_below = recent_base.transform_filter(alt.datum["基準以下"] == True)
        recent_below_line = recent_below.mark_line(
            color="#DC2626", strokeWidth=3
        ).encode(detail="連続区間:N")
        recent_below_points = recent_below.mark_circle(color="#DC2626", size=45)
        month_boundaries = pd.DataFrame(
            {
                "月初": pd.date_range(
                    start=recent_start.normalize(),
                    end=recent_end.normalize(),
                    freq="MS",
                )
            }
        )
        month_lines = alt.Chart(month_boundaries).mark_rule(
            color="#94A3B8", strokeWidth=1, opacity=0.45
        ).encode(x="月初:T")
        recent_threshold_line = alt.Chart(
            pd.DataFrame({"基準価格": [threshold]})
        ).mark_rule(color="#DC2626", strokeDash=[6, 4], opacity=0.65).encode(
            y="基準価格:Q"
        )

        recent_pickling = recent_chart[recent_chart["基準以下"]].copy()
        has_recent_pickling = not recent_pickling.empty
        if has_recent_pickling:
            recent_longest_days = max(
                (
                    pd.Timestamp(segment["日付"].iloc[-1])
                    - pd.Timestamp(segment["日付"].iloc[0])
                ).days
                + 1
                for _, segment in recent_pickling.groupby("連続区間")
            )
            recent_evaluation_start = pd.Timestamp(recent_pickling["日付"].min())
            recent_evaluation_chart = recent_chart[
                recent_chart["日付"] >= recent_evaluation_start
            ]
        else:
            recent_longest_days = 0
            recent_evaluation_start = recent_start
            recent_evaluation_chart = recent_chart

        recent_low = float(recent_evaluation_chart["株価"].min())
        recent_high = float(recent_evaluation_chart["株価"].max())
        recent_low_date = pd.Timestamp(
            recent_evaluation_chart.loc[
                recent_evaluation_chart["株価"].idxmin(), "日付"
            ]
        )
        recent_high_date = pd.Timestamp(
            recent_evaluation_chart.loc[
                recent_evaluation_chart["株価"].idxmax(), "日付"
            ]
        )
        extrema_annotations = pd.DataFrame(
            [
                {
                    "日付": recent_low_date,
                    "株価": recent_low,
                    "種別": "最安値",
                    "注記": f"最安値 {recent_low_date.month}/{recent_low_date.day}",
                },
                {
                    "日付": recent_high_date,
                    "株価": recent_high,
                    "種別": "最高値",
                    "注記": f"最高値 {recent_high_date.month}/{recent_high_date.day}",
                },
            ]
            if has_recent_pickling
            else [],
            columns=["日付", "株価", "種別", "注記"],
        )
        extrema_color = alt.Color(
            "種別:N",
            scale=alt.Scale(
                domain=["最安値", "最高値"],
                range=["#16A34A", "#16A34A"],
            ),
            legend=None,
        )
        extrema_rules = alt.Chart(extrema_annotations).mark_rule(
            strokeDash=[4, 3], strokeWidth=2, opacity=0.65
        ).encode(x="日付:T", color=extrema_color)
        extrema_points = alt.Chart(extrema_annotations).mark_point(
            filled=True, size=130, stroke="#FFFFFF", strokeWidth=2
        ).encode(
            x="日付:T",
            y="株価:Q",
            color=extrema_color,
            tooltip=[
                alt.Tooltip("種別:N", title="区分"),
                alt.Tooltip("日付:T", title="日付", format="%Y年%m月%d日"),
                alt.Tooltip("株価:Q", title=f"{label}（円）", format=",.2f"),
            ],
        )
        extrema_high_label = alt.Chart(extrema_annotations).transform_filter(
            alt.datum["種別"] == "最高値"
        ).mark_text(
            dy=-14, fontSize=12, fontWeight="bold", color="#16A34A"
        ).encode(
            x="日付:T",
            y="株価:Q",
            text="注記:N",
        )
        extrema_low_label = alt.Chart(extrema_annotations).transform_filter(
            alt.datum["種別"] == "最安値"
        ).mark_text(
            dy=16,
            baseline="top",
            fontSize=12,
            fontWeight="bold",
            color="#16A34A",
        ).encode(
            x="日付:T",
            y="株価:Q",
            text="注記:N",
        )
        full_period_title = (
            '<div class="full-period-title" style="font-size:20px;font-weight:700;">'
            f"期間：{format_month_ja(start_date)}～{format_month_ja(end_date)}"
            "</div>"
        )
        full_period_chart = (
            year_lines
            + normal_line
            + below_line
            + below_points
            + threshold_line
        ).properties(height=320)
        mobile_base = base.encode(
            x=alt.X(
                "日付:T",
                title=None,
                axis=alt.Axis(
                    format="%y年",
                    tickCount="year",
                    labelAngle=0,
                    labelOverlap=False,
                    labelFontSize=9,
                ),
                scale=alt.Scale(
                    domain=[pd.Timestamp(start_date), pd.Timestamp(end_date)]
                ),
            )
        )
        mobile_normal_line = mobile_base.mark_line(color="#2563EB", strokeWidth=2)
        mobile_below = mobile_base.transform_filter(alt.datum["基準以下"] == True)
        mobile_below_line = mobile_below.mark_line(
            color="#DC2626", strokeWidth=3
        ).encode(detail="連続区間:N")
        mobile_below_points = mobile_below.mark_circle(color="#DC2626", size=45)
        mobile_full_period_chart = (
            year_lines
            + mobile_normal_line
            + mobile_below_line
            + mobile_below_points
            + threshold_line
        ).properties(height=320)
        with full_graph_slot.container():
            with st.container(key="desktop_full_period_graph"):
                st.markdown(full_period_title, unsafe_allow_html=True)
                st.altair_chart(full_period_chart, use_container_width=True)
        full_statistics_period = (
            f"{format_month_ja(start_date)}～{format_month_ja(end_date)}"
        )
        recent_statistics_period = (
            f"{format_month_ja(recent_evaluation_start)}～"
            f"{format_month_ja(recent_end)}"
        )
        recent_low_percent = int((recent_low / threshold - 1) * 100)
        recent_high_percent = int((recent_high / threshold - 1) * 100)
        recent_longest_days_color = (
            "#DC2626" if recent_longest_days >= 30 else "#2563EB"
        )
        if recent_low_percent >= 0:
            low_assessment = "下落による被害はなし"
        elif recent_low_percent >= -5:
            low_assessment = "被害はごく少なめ"
        elif recent_low_percent >= -10:
            low_assessment = "被害は少なめ"
        elif recent_low_percent >= -20:
            low_assessment = "下落の影響はやや大きめ"
        elif recent_low_percent >= -40:
            low_assessment = "下落の影響は大きめ"
        else:
            low_assessment = "下落の影響は非常に大きめ"
        if recent_high_percent >= 20:
            high_assessment = "利益は高め"
        elif recent_high_percent >= 10:
            high_assessment = "利益はやや高め"
        elif recent_high_percent > 0:
            high_assessment = "利益は小さめ"
        elif recent_high_percent == 0:
            high_assessment = "利益はほぼない水準"
        else:
            high_assessment = "基準価格まで未回復"
        if streaks.empty:
            review_grade = "S"
            streak_summary = (
                f"{full_statistics_period}の統計では、この条件の塩漬け期間は"
                "確認されませんでした。"
            )
            outlook_summary = (
                f"過去データ上、{threshold:,.0f}円以下では塩漬けを避けられています。"
            )
            outlook_color = "#2563EB"
        else:
            longest_days = int(streaks["下回った日数"].max())
            streak_count = len(streaks)
            outside_recent_year_streaks = streaks[
                pd.to_datetime(streaks["開始日"]) < recent_start
            ]
            outside_recent_year_longest_days = (
                int(outside_recent_year_streaks["下回った日数"].max())
                if not outside_recent_year_streaks.empty
                else None
            )
            if longest_days <= 7:
                review_grade = "S"
            elif longest_days <= 30:
                review_grade = "A"
            elif longest_days <= 90:
                review_grade = "B"
            elif longest_days <= 180:
                review_grade = "C"
            elif longest_days <= 365:
                review_grade = "D"
            else:
                review_grade = "E"
            longest_days_color = "#2563EB" if longest_days <= 60 else "#DC2626"
            streak_summary = (
                f"{full_statistics_period}の統計では、"
                f'<strong style="color:{longest_days_color};">'
                f"最長塩漬けは{longest_days}日</strong>、"
                f"塩漬け回数は{streak_count}回です。"
            )
            if longest_days <= 30 and recent_high_percent > 0:
                outlook_summary = (
                    f"過去データ上、{threshold:,.0f}円以下では比較的短期間で"
                    "基準価格を回復した傾向があります。"
                )
                outlook_color = "#2563EB"
            elif longest_days <= 90:
                outlook_summary = (
                    f"{threshold:,.0f}円以下では塩漬け期間が比較的短い傾向ですが、"
                    "相場状況によって長期化する可能性があります。"
                )
                outlook_color = "#DC2626"
            else:
                if (
                    outside_recent_year_longest_days is not None
                    and outside_recent_year_longest_days > recent_longest_days
                ):
                    outlook_summary = (
                        f"直近一年外で{outside_recent_year_longest_days}日の"
                        "塩漬け実績があるため、購入時期には注意が必要です。"
                    )
                elif has_recent_pickling:
                    outlook_summary = (
                        f"直近一年で{recent_longest_days}日の"
                        "塩漬け実績があるため、購入時期には注意が必要です。"
                    )
                else:
                    outlook_summary = (
                        f"{threshold:,.0f}円以下でも塩漬けが長期化した実績があるため、"
                        "購入時期には注意が必要です。"
                    )
                outlook_color = "#DC2626"
        grade_colors = {
            "S": "#B7791F",
            "A": "#15803D",
            "B": "#2563EB",
            "C": "#0891B2",
            "D": "#EA580C",
            "E": "#DC2626",
        }
        prices_before_recent_year = prices.loc[
            prices.index < recent_start, "High"
        ].dropna()
        current_high_warning = (
            use_current_price
            and not prices_before_recent_year.empty
            and float(prices_before_recent_year.max()) < threshold
        )
        if current_high_warning:
            grade_label = "評価不可"
            grade_color = "#64748B"
            recent_assessment_html = (
                f'<div>直近1年の最長塩漬けは'
                f'<strong style="color:{recent_longest_days_color};">'
                f'{recent_longest_days}日</strong></div>'
                f'<div>最安値は<strong style="color:#DC2626;">'
                f'{recent_low_percent:+d}％（{recent_low:,.0f}円）</strong>で'
                f'<strong style="color:#DC2626;">{low_assessment}</strong></div>'
                f'<div>最高値は<strong style="color:#2563EB;">'
                f'{recent_high_percent:+d}％（{recent_high:,.0f}円）</strong>で'
                f'<strong style="color:#2563EB;">{high_assessment}</strong></div>'
                '<br>'
                '<div>現在高値の可能性があるため評価不可です。</div>'
            )
        elif not has_recent_pickling:
            grade_label = "評価不可"
            grade_color = "#64748B"
            recent_assessment_html = (
                "<div>直近1年に塩漬けが始まっていないため評価不可です。</div>"
            )
        else:
            grade_label = f"{review_grade}評価"
            grade_color = grade_colors[review_grade]
            recent_assessment_html = (
                f'<div class="recent-assessment-desktop">直近1年の塩漬け開始後'
                f'（{recent_statistics_period}）の'
                f"<br>最安値は"
                f'<strong style="color:#DC2626;">'
                f"{recent_low_percent:+d}％（{recent_low:,.0f}円）</strong>で"
                f'<strong style="color:#DC2626;">{low_assessment}</strong>、<br>'
                f"最高値は"
                f'<strong style="color:#2563EB;">'
                f"{recent_high_percent:+d}％（{recent_high:,.0f}円）</strong>で"
                f'<strong style="color:#2563EB;">{high_assessment}</strong>です。</div>'
                f'<div class="recent-assessment-mobile">'
                f'<div>直近1年の最長塩漬けは'
                f'<strong style="color:{recent_longest_days_color};">'
                f'{recent_longest_days}日</strong></div>'
                f'<div>最安値は<strong style="color:#DC2626;">'
                f'{recent_low_percent:+d}％（{recent_low:,.0f}円）</strong>で'
                f'<strong style="color:#DC2626;">{low_assessment}</strong></div>'
                f'<div>最高値は<strong style="color:#2563EB;">'
                f'{recent_high_percent:+d}％（{recent_high:,.0f}円）</strong>で'
                f'<strong style="color:#2563EB;">{high_assessment}</strong></div>'
                f'<br>'
                f'</div>'
                f'<div><strong style="color:{outlook_color};">'
                f"{outlook_summary}</strong></div>"
            )
        purchase_context = (
            f"現在の株価{threshold:,.0f}円で購入した場合、"
            if use_current_price
            else f"{threshold:,.0f}円で購入した場合、"
        )
        review_html = (
            '<div class="review-card" style="margin:36px 16px 0;padding:18px 20px;border:1px solid #CBD5E1;'
            'border-radius:10px;background:#F8FAFC;line-height:1.8;font-size:18px;">'
            '<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">'
            '<span class="review-card-title" style="font-size:22px;font-weight:700;">総評</span>'
            f'<span class="review-card-grade" style="display:inline-block;padding:1px 12px;border-radius:999px;'
            f'background:{grade_color};color:#FFFFFF;font-size:17px;font-weight:700;">'
            f"{grade_label}</span></div>"
            f"<div>{purchase_context}</div>"
            f'<div class="review-statistics-line">{streak_summary}</div>'
            f"{recent_assessment_html}"
            '<div class="review-card-note" style="font-size:14px;color:#64748B;margin-top:8px;">'
            "※過去の株価に基づく傾向であり、将来の利益を保証するものではありません。"
            "</div></div>"
        )
        with recent_graph_slot.container():
            recent_chart_column, review_column = st.columns([12, 13])
            with recent_chart_column:
                st.markdown(
                    '<div style="font-size:20px;font-weight:700;margin-left:48px;">'
                    f"直近1年　【{escape(company_name)}】</div>",
                    unsafe_allow_html=True,
                )
                st.altair_chart(
                    (
                        month_lines
                        + recent_normal_line
                        + recent_below_line
                        + recent_below_points
                        + recent_threshold_line
                        + extrema_rules
                        + extrema_points
                        + extrema_high_label
                        + extrema_low_label
                    ).properties(height=320),
                    use_container_width=True,
                )
                with st.container(key="mobile_full_period_graph"):
                    st.markdown(full_period_title, unsafe_allow_html=True)
                    st.altair_chart(mobile_full_period_chart, use_container_width=True)
            with review_column:
                st.markdown(review_html, unsafe_allow_html=True)
        render_company_info(company_name, ticker, company_info)
        scroll_to_result("search-results-anchor")
    except Exception as exc:
        st.error(f"処理できませんでした: {exc}")
        st.caption("証券コードとインターネット接続をご確認のうえ、もう一度お試しください。")
