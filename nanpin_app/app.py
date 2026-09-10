from __future__ import annotations

import base64
from html import escape
import json
from math import pi
import re
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from nanpin_plan import build_nanpin_plan

# Keep this copy's Yahoo Finance cache independent of the original app.
yf.set_tz_cache_location(str(Path(__file__).with_name(".yfinance-cache")))


LABELS = {"Close": "終値", "Low": "安値", "Open": "始値", "High": "高値"}
START_YEAR_OPTIONS = list(range(2000, 2030, 5))
SEARCH_HISTORY_FILE = Path(__file__).with_name(".search_history.json")
SEARCH_HISTORY_COOKIE = "stock_search_history_clone_8769"
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


def calculate_nanpin_gap_percent(
    average_price: float, investment_price: float
) -> int:
    change = (
        (
            Decimal(str(investment_price))
            / Decimal(str(average_price))
            - Decimal("1")
        )
        * Decimal("100")
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(change)


def format_nanpin_price(average_price: float, investment_price: float) -> str:
    price = Decimal(str(average_price)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    change = calculate_nanpin_gap_percent(average_price, investment_price)
    sign = "-" if change < 0 else "+" if change > 0 else ""
    return f"{price:,}円（{sign}{abs(change)}％）"


def format_yen(value: float) -> str:
    price = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{price:,}円"


def format_man_yen(value_yen: float) -> str:
    return f"{value_yen / 10_000:,.1f}".rstrip("0").rstrip(".") + "万円"


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


@st.cache_data(ttl=3600, show_spinner=False)
def download_prices(ticker: str, start: date, end: date) -> pd.DataFrame:
    # yfinance's end is exclusive.
    raw = yf.download(ticker, start=start, end=end + pd.Timedelta(days=1), progress=False, auto_adjust=False)
    if raw.empty:
        raise RuntimeError("株価データを取得できませんでした。")
    return normalize_prices(raw)


@st.cache_data(ttl=300, show_spinner=False)
def get_current_price(ticker: str) -> float:
    raw = yf.download(
        ticker, period="5d", progress=False, auto_adjust=False
    )
    prices = normalize_prices(raw)
    if prices.empty or "Close" not in prices.columns:
        raise RuntimeError("現在の株価を取得できませんでした。")
    closes = prices["Close"].dropna()
    if closes.empty:
        raise RuntimeError("現在の株価を取得できませんでした。")
    return float(closes.iloc[-1])


@st.cache_data(ttl=86400, show_spinner=False)
def get_company_info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).get_info() or {}
    except Exception:
        return {}


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
    security_code: str,
    key_prefix: str = "desktop",
    start_year: int | None = None,
    *,
    carry_conditions: bool = True,
) -> None:
    """Show equal-size, clickable links to both stock tools."""
    assets = Path(__file__).with_name("assets")
    reference_years = int(st.session_state.get(f"{key_prefix}_bottom_reference_years", 5))
    budget = float(st.session_state.get(f"{key_prefix}_investment_budget_man_yen", 100))
    count = int(st.session_state.get(f"{key_prefix}_averaging_down_count", 3))
    gap = int(st.session_state.get(f"{key_prefix}_maximum_bottom_gap_percent", 10))
    if start_year is None:
        start_year = date.today().year - reference_years
    if carry_conditions:
        common = f"app_code={escape(security_code, quote=True)}"
        nanpin_destination = (
            f"/nanpin?{common}&amp;app_budget={budget:g}&amp;app_count={count}"
            f"&amp;app_reference_years={reference_years}&amp;app_gap={gap}"
        )
        salt_destination = f"/?{common}&amp;app_start_year={int(start_year)}"
    else:
        nanpin_destination = "/nanpin"
        salt_destination = "/"
    banner_items = [
        (assets / "absolute-safe-nanpin-banner.png", nanpin_destination, "絶対安全ナンピン君"),
        (assets / "stock-bottom-days-banner.png", salt_destination, "塩漬け日数チェッカー"),
    ]
    cards = []
    for image_path, destination, label in banner_items:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        cards.append(
            f'<a class="app-banner" href="{destination}" target="_top" '
            f'aria-label="{label}"><img src="data:image/png;base64,{encoded}" '
            f'alt="{label}"></a>'
        )
    st.markdown(
        '<div class="app-banner-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def render_bottom_price_form(threshold: float) -> None:
    with st.form(
        "nanpin_bottom_price_form", border=False, enter_to_submit=False
    ):
        bottom_input_column, recalculate_column = st.columns(
            [1.5, 1.1], vertical_alignment="bottom"
        )
        with bottom_input_column:
            st.number_input(
                "円に底値変更",
                min_value=1,
                max_value=max(1, int(round(threshold))),
                step=1,
                key="nanpin_bottom_price_draft",
                label_visibility="collapsed",
            )
        with recalculate_column:
            if st.form_submit_button(
                "底値再計算", type="primary", use_container_width=True
            ):
                st.session_state["nanpin_bottom_price_committed"] = int(
                    st.session_state["nanpin_bottom_price_draft"]
                )
                st.rerun()


@st.cache_data
def load_company_options() -> list[str]:
    companies = pd.read_csv(
        Path(__file__).with_name("companies.csv"), dtype={"code": str}
    )
    return [f"{row.code}｜{row.name}" for row in companies.itertuples(index=False)]


@st.cache_data(ttl=900, show_spinner=False)
def build_light_pickling_ranking(
    start_date: date, end_date: date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    tickers = [f"{code}.T" for code in NIKKEI225_CODES]
    history_start_date = (
        pd.Timestamp(start_date) - pd.DateOffset(years=3)
    ).date()
    raw = yf.download(
        tickers,
        start=history_start_date,
        end=end_date + pd.Timedelta(days=1),
        progress=False,
        auto_adjust=False,
        group_by="ticker",
        threads=True,
    )
    company_names = {
        option.split("｜", 1)[0]: option.split("｜", 1)[1]
        for option in load_company_options()
    }
    rows = []
    for code, ticker in zip(NIKKEI225_CODES, tickers):
        try:
            ticker_raw = raw[ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
            all_prices = normalize_prices(ticker_raw)
            prices = all_prices.loc[all_prices.index >= pd.Timestamp(start_date)]
            current_prices = prices["Close"].dropna()
            if current_prices.empty:
                continue
            current_price = float(current_prices.iloc[-1])
            three_year_cutoff = pd.Timestamp(end_date) - pd.DateOffset(years=3)
            older_highs = all_prices.loc[
                all_prices.index < three_year_cutoff, "High"
            ].dropna()
            streaks = find_streaks(prices, "Low", current_price)
            if streaks.empty:
                continue
            longest_days = int(streaks["下回った日数"].max())
            lowest_price = float(prices["Low"].dropna().min())
            streak_lowest_price = float(streaks["期間中最安値（円）"].min())
            lowest_change_percent = (lowest_price / current_price - 1) * 100
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
                    "_浅漬け最安値": format_price_with_change(
                        streak_lowest_price, current_price
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
        empty = pd.DataFrame(
            columns=["最安値", "銘柄", "最長塩漬け期間", "株価", "塩漬け回数"]
        )
        return empty, empty.copy()
    all_rankings = pd.DataFrame(rows)
    lowest_ranking = (
        all_rankings
        .sort_values(["_最安値騰落率", "銘柄"], ascending=[False, True])
        .head(10)
        .reset_index(drop=True)
    )
    shallow_ranking = (
        all_rankings.loc[all_rankings["_塩漬け順位対象"]]
        .sort_values(["_最長日数", "銘柄"], ascending=[True, True])
        .head(10)
        .reset_index(drop=True)
    )

    def finish(frame: pd.DataFrame, shallow=False) -> pd.DataFrame:
        frame = frame.copy()
        if shallow:
            frame["最安値"] = frame["_浅漬け最安値"]
        frame["銘柄"] = frame.apply(
            lambda row: (
                f'<a href="?ranking_code={row["_証券コード"]}'
                f'&ranking_start={start_date.year}" target="_self">'
                f'{escape(str(row["銘柄"]))}</a>'
            ),
            axis=1,
        )
        return frame.drop(
            columns=["_最長日数", "_最安値騰落率", "_証券コード", "_浅漬け最安値", "_塩漬け順位対象"]
        )

    return (
        finish(lowest_ranking)[["最安値", "銘柄", "最長塩漬け期間", "株価", "塩漬け回数"]],
        finish(shallow_ranking, shallow=True)[["最長塩漬け期間", "銘柄", "株価", "塩漬け回数", "最安値"]],
    )


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


def request_gap_recalculation(key_prefix: str) -> None:
    """Re-run an existing result immediately after its gap setting changes."""
    if "nanpin_result_signature" in st.session_state:
        st.session_state[f"{key_prefix}_gap_changed_run"] = True


def render_search_controls(
    key_prefix: str,
    show_end_date: bool = True,
):
    company_options = load_company_options()
    default_index = next(
        (index for index, option in enumerate(company_options) if option.startswith("7211｜")),
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
    # The original price-mode controls are intentionally hidden while the
    # nanpin inputs are being designed. Keep their old defaults internally so
    # the existing aggregation code continues to run unchanged.
    threshold = 320
    use_current_price = True
    light_pickling_price = False
    st.number_input(
        "投資資金（万円）",
        min_value=1,
        value=100,
        step=1,
        placeholder="金額を入力",
        key=f"{key_prefix}_investment_budget_man_yen",
    )
    st.selectbox(
        "ナンピン回数",
        options=list(range(2, 11)),
        index=1,
        format_func=lambda count: f"{count}回",
        key=f"{key_prefix}_averaging_down_count",
    )
    bottom_reference_years = st.selectbox(
        "底値基準",
        options=list(range(1, 21)),
        index=4,
        format_func=lambda years: f"{years}年前",
        key=f"{key_prefix}_bottom_reference_years",
    )
    st.markdown(
        '<div class="nanpin-gap-label">最終ナンピンで<br>'
        "底値から離されたくない％は</div>",
        unsafe_allow_html=True,
    )
    st.selectbox(
        "最終ナンピンで底値から離されたくない％は",
        options=[5, 10, 20, 30],
        index=1,
        format_func=lambda percent: f"{percent}％",
        key=f"{key_prefix}_maximum_bottom_gap_percent",
        on_change=request_gap_recalculation,
        args=(key_prefix,),
        label_visibility="collapsed",
    )
    end_date = (
        st.date_input("終了日", value=date.today(), key=f"{key_prefix}_end")
        if show_end_date
        else date.today()
    )
    start_date = (
        pd.Timestamp(end_date) - pd.DateOffset(years=bottom_reference_years)
    ).date()
    run = st.button(
        "集計する", type="primary", use_container_width=True, key=f"{key_prefix}_run"
    )
    run = run or st.session_state.pop(f"{key_prefix}_gap_changed_run", False)
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


st.set_page_config(page_title="絶対安全ナンピン君", page_icon="📉", layout="wide")

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
linked_company_code = str(st.query_params.get("app_code", "")).strip().upper()
if linked_company_code:
    linked_company = next(
        (
            option for option in load_company_options()
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

        budget = max(1, linked_int("app_budget", 100))
        count = min(10, max(2, linked_int("app_count", 3)))
        reference_years = min(20, max(1, linked_int("app_reference_years", 5)))
        gap = linked_int("app_gap", 10)
        if gap not in (5, 10, 20, 30):
            gap = 10
        for prefix in ("mobile", "desktop"):
            st.session_state[f"{prefix}_company"] = linked_company
            st.session_state[f"{prefix}_investment_budget_man_yen"] = budget
            st.session_state[f"{prefix}_averaging_down_count"] = count
            st.session_state[f"{prefix}_bottom_reference_years"] = reference_years
            st.session_state[f"{prefix}_maximum_bottom_gap_percent"] = gap
        st.session_state["ranking_company_run"] = True
    del st.query_params["app_code"]
    for linked_param in ("app_budget", "app_count", "app_reference_years", "app_gap"):
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
components.html(
    """
    <script>
    (() => {
        const page = window.parent;
        if (!['127.0.0.1', 'localhost'].includes(page.location.hostname)) return;
        const controlId = 'local-view-switcher';
        if (page.document.getElementById(controlId)) return;
        const control = page.document.createElement('div');
        control.id = controlId;
        control.innerHTML = `
            <span>表示確認（初期：PC版）</span>
            <button type="button" data-width="1366" data-height="850" data-name="desktopPreview">PC版</button>
            <button type="button" data-width="390" data-height="850" data-name="mobilePreview">スマホ版</button>
        `;
        Object.assign(control.style, {
            position: 'fixed', right: '16px', bottom: '58px', zIndex: '1002',
            display: 'flex', alignItems: 'center', gap: '6px', padding: '7px 8px',
            border: '1px solid #CBD5E1', borderRadius: '12px',
            background: 'rgba(255,255,255,0.96)', boxShadow: '0 8px 24px rgba(15,23,42,0.14)',
            color: '#334155', fontFamily: '"Yu Gothic", sans-serif', fontSize: '12px',
            fontWeight: '700', backdropFilter: 'blur(8px)'
        });
        for (const button of control.querySelectorAll('button')) {
            Object.assign(button.style, {
                border: '0', borderRadius: '8px', padding: '7px 10px',
                background: button.dataset.name === 'desktopPreview' ? '#0F766E' : '#334155',
                color: '#FFFFFF', fontSize: '12px', fontWeight: '700', cursor: 'pointer'
            });
            button.addEventListener('click', () => {
                const preview = page.open(
                    page.location.href,
                    button.dataset.name,
                    `popup=yes,width=${button.dataset.width},height=${button.dataset.height},resizable=yes,scrollbars=yes`
                );
                if (preview) preview.focus();
            });
        }
        page.document.body.appendChild(control);
    })();
    </script>
    """,
    height=0,
)
st.markdown(
    """
    <style>
    .st-key-mobile_filters { display: none; }
    [data-testid="stSidebarNav"] { display: none; }
    .st-key-mobile_ranking_controls { display: none; }
    .st-key-mobile_results_table { display: none; }
    .st-key-mobile_search_history { display: none; }
    .st-key-mobile_full_period_graph { display: none; }
    .full-period-title .mobile-title-break { display: none; }
    .st-key-nanpin_indicator_card {
        margin: 36px 16px 0;
    }
    .st-key-nanpin_indicator_card [data-testid="stVerticalBlockBorderWrapper"] {
        background: #F8FAFC;
        border-color: #CBD5E1;
        border-radius: 10px;
    }
    .st-key-nanpin_indicator_card [data-testid="stNumberInput"] input {
        text-align: right;
        padding-right: 1.75rem;
    }
    .st-key-nanpin_indicator_card [data-testid="stNumberInputContainer"] {
        position: relative;
    }
    .st-key-nanpin_indicator_card [data-testid="stNumberInputContainer"]::after {
        content: "円";
        position: absolute;
        right: 4.35rem;
        top: 50%;
        transform: translateY(-50%);
        color: #0F172A;
        font-weight: 600;
        pointer-events: none;
    }
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
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(1) {
        width: 18%;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(2),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(2) {
        width: 32%;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(3),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(3) {
        width: 14%;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(4),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(4) {
        width: 15%;
    }
    .st-key-desktop_ranking_table .results-table-scroll th:nth-child(5),
    .st-key-desktop_ranking_table .results-table-scroll td:nth-child(5) {
        width: 20%;
    }
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
    .st-key-desktop_results_table .results-table-scroll td:first-child,
    .st-key-mobile_results_table .results-table-scroll td:first-child {
        color: #111111 !important;
        background: #DDE1E7 !important;
        font-weight: 700 !important;
    }
    .st-key-desktop_results_table .results-table-scroll,
    .st-key-mobile_results_table .results-table-scroll {
        width: fit-content;
        max-width: 100%;
    }
    .st-key-desktop_results_table .results-table-scroll table,
    .st-key-mobile_results_table .results-table-scroll table {
        width: auto;
        min-width: 0;
        table-layout: auto;
    }
    .st-key-desktop_results_table .results-table-scroll th,
    .st-key-desktop_results_table .results-table-scroll td,
    .st-key-mobile_results_table .results-table-scroll th,
    .st-key-mobile_results_table .results-table-scroll td {
        min-width: 10.5rem;
    }
    .st-key-desktop_results_table .results-table-scroll th:first-child,
    .st-key-mobile_results_table .results-table-scroll th:first-child {
        background: #9CA3AF !important;
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
    .nanpin-gap-label {
        min-height: 3rem;
        margin: 0.35rem 0 0.65rem;
        color: #111827;
        font-size: 0.875rem;
        line-height: 1.4;
    }
    .app-banner-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1rem;
        width: 70%;
        max-width: 602px;
        margin: 1.4rem 0 1.8rem;
    }
    .app-banner {
        display: flex;
        height: 66px;
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
    .nanpin-review-mobile { display: none; }
    .st-key-nanpin_allocation_chart_mobile { display: none; }
    .st-key-desktop_results_table [data-testid="stCaptionContainer"],
    .st-key-mobile_results_table [data-testid="stCaptionContainer"] {
        margin-top: 0.65rem;
        transform: translateY(1rem);
        margin-bottom: 1rem;
    }
    .nanpin-review-section { margin-bottom: 1rem; }
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
    .app-title {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        width: fit-content;
        margin: 0 0 1.4rem;
        text-align: center;
        font-family: "BIZ UDPGothic", "Yu Gothic UI", "Yu Gothic", sans-serif;
        font-size: clamp(2.25rem, 4vw, 3.25rem);
        font-weight: 900;
        line-height: 1.25;
        letter-spacing: 0.03em;
        color: #C65D0E;
        text-shadow:
            0 3px 0 #F7D28A,
            2px 5px 0 rgba(124, 58, 12, 0.15);
    }
    .app-title::before,
    .app-title::after {
        font-size: 0.72em;
        filter: drop-shadow(0 2px 1px rgba(75, 48, 22, 0.18));
    }
    .app-title::before { content: "🫓"; transform: rotate(-12deg); }
    .app-title::after { content: "🫓"; transform: rotate(12deg); }
    .app-subtitle {
        width: 100%;
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
        .nanpin-review-desktop { display: none; }
        .nanpin-review-mobile { display: block; }
        .st-key-nanpin_allocation_chart_desktop { display: none; }
        .st-key-nanpin_allocation_chart_mobile {
            display: block;
            width: 70%;
            margin: 0.6rem auto 0.9rem;
        }
        .st-key-desktop_initial_banners { display: none; }
        .st-key-nanpin_plan_content [data-testid="stHorizontalBlock"] {
            flex-direction: column-reverse !important;
        }
        .st-key-nanpin_plan_content [data-testid="stColumn"] {
            width: 100% !important;
            flex: 0 0 auto !important;
        }
        .app-banner-grid {
            grid-template-columns: 1fr;
            gap: 0.7rem;
            width: 70%;
            margin: 1rem auto 1.4rem;
        }
        .app-banner { height: 53px; }
        .stAppViewBlockContainer,
        .stMainBlockContainer,
        [data-testid="stAppViewBlockContainer"] {
            padding-top: 2.5rem !important;
        }
        .st-key-mobile_filters { display: block; }
        .st-key-mobile_ranking_controls { display: block; }
        .st-key-mobile_full_period_graph { display: block; }
        .st-key-desktop_full_period_graph { display: none; }
        .full-period-title {
            margin-bottom: 0.75rem;
            font-size: 16px !important;
            line-height: 1.45;
        }
        .full-period-title .mobile-title-break { display: block; }
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
            width: 100%;
            overflow-x: hidden;
        }
        .st-key-mobile_results_table .results-table-scroll table {
            width: 100%;
            min-width: 0;
            table-layout: fixed;
            font-size: clamp(0.54rem, 2.35vw, 0.68rem);
        }
        .st-key-mobile_results_table .results-table-scroll th,
        .st-key-mobile_results_table .results-table-scroll td {
            min-width: 0;
            padding: 0.38rem 0.18rem;
            white-space: normal;
            overflow-wrap: anywhere;
            line-height: 1.3;
        }
        .st-key-desktop_results_table { display: none; }
        .st-key-mobile_results_table { display: block; }
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
    '<div class="app-title" role="heading" aria-level="1">絶対安全ナンピン君</div>',
    unsafe_allow_html=True,
)

with st.container(key="mobile_filters"):
    st.header("検索条件")
    mobile_values = render_search_controls("mobile", show_end_date=False)
    if st.session_state.pop("mobile_history_run", False):
        mobile_values = (*mobile_values[:-1], True)
    if mobile_values[-1]:
        add_desktop_search_history(mobile_values)

st.markdown(
    '<div class="app-subtitle">'
    "購入する株のナンピン目安を提供します。"
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
                lowest_price_ranking, shallow_ranking = build_light_pickling_ranking(
                    ranking_start_date, ranking_end_date
                )
            st.markdown(
                '<div id="ranking-results-anchor" style="scroll-margin-top: 4rem;"></div>',
                unsafe_allow_html=True,
            )
            st.subheader("最安値ランキング")
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
            render_app_banners(
                ranking_values[0],
                "mobile" if mobile_ranking_requested else "desktop",
                ranking_values[4].year,
                carry_conditions=False,
            )
            scroll_to_result("ranking-results-anchor")
        except (RuntimeError, ValueError, KeyError) as error:
            st.error(f"ランキングを作成できませんでした: {error}")
    st.stop()

with st.container(key="mobile_search_history"):
    render_search_history("mobile")
    render_app_banners(
        mobile_values[0], "mobile", mobile_values[4].year, carry_conditions=False
    )
if not mobile_values[-1] and not desktop_values[-1]:
    with st.container(key="desktop_initial_banners"):
        render_app_banners(
            desktop_values[0], "desktop", desktop_values[4].year,
            carry_conditions=False,
        )
st.markdown(
    '<div class="app-footer">制作者：木星在住　'
    '<a href="https://x.com/mokuseidayo" target="_blank">Twitter</a></div>',
    unsafe_allow_html=True,
)

mobile_run_requested = bool(mobile_values[-1])
desktop_run_requested = bool(desktop_values[-1])
if mobile_run_requested:
    active_search_prefix = "mobile"
elif desktop_run_requested:
    active_search_prefix = "desktop"
else:
    active_search_prefix = st.session_state.get(
        "nanpin_active_search_prefix", "desktop"
    )
active_values = mobile_values if active_search_prefix == "mobile" else desktop_values
security_code, threshold, use_current_price, light_pickling_price, start_date, end_date, _ = active_values
averaging_down_count = int(
    st.session_state.get(f"{active_search_prefix}_averaging_down_count", 3)
)
investment_budget_man_yen = float(
    st.session_state.get(f"{active_search_prefix}_investment_budget_man_yen", 100)
)
maximum_bottom_gap_percent = int(
    st.session_state.get(f"{active_search_prefix}_maximum_bottom_gap_percent", 10)
)
search_signature = (
    active_search_prefix,
    str(security_code),
    str(start_date),
    str(end_date),
    int(averaging_down_count),
    float(investment_budget_man_yen),
    int(maximum_bottom_gap_percent),
    bool(use_current_price),
    bool(light_pickling_price),
)
if mobile_run_requested or desktop_run_requested:
    st.session_state["nanpin_active_search_prefix"] = active_search_prefix
    st.session_state["nanpin_result_signature"] = search_signature
    run = True
else:
    run = st.session_state.get("nanpin_result_signature") == search_signature
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
            light_pickling_days = None
            current_market_price = None
            if light_pickling_price:
                threshold, light_pickling_days = find_light_pickling_price(
                    prices, column, target_days=30
                )
                current_market_price = get_current_price(ticker)
            elif use_current_price:
                threshold = get_current_price(ticker)
            company_info = get_company_info(ticker)
            company_name = get_company_name(ticker, company_info)
        if column not in prices.columns:
            raise ValueError(f"{label}列がデータにありません。")

        st.markdown(
            '<div id="search-results-anchor" style="scroll-margin-top: 4rem;"></div>',
            unsafe_allow_html=True,
        )
        streaks = find_streaks(prices, column, threshold)
        calculated_period_low = float(prices[column].dropna().min())
        bottom_price_context = (
            f"{ticker}|{column}|{pd.Timestamp(start_date).date()}|"
            f"{pd.Timestamp(end_date).date()}|{float(threshold):.4f}"
        )
        if st.session_state.get("nanpin_bottom_price_context") != bottom_price_context:
            initial_bottom_price = max(1, int(round(calculated_period_low)))
            st.session_state["nanpin_bottom_price_context"] = bottom_price_context
            st.session_state["nanpin_bottom_price_committed"] = initial_bottom_price
            st.session_state["nanpin_bottom_price_draft"] = initial_bottom_price
        committed_bottom_price = float(
            st.session_state["nanpin_bottom_price_committed"]
        )
        if (
            st.session_state.get("nanpin_bottom_price_form_context")
            != bottom_price_context
        ):
            st.session_state["nanpin_bottom_price_form_context"] = (
                bottom_price_context
            )
            st.session_state["nanpin_bottom_price_draft"] = int(
                round(committed_bottom_price)
            )
        nanpin_plan = build_nanpin_plan(
            total_budget_yen=investment_budget_man_yen * 10_000,
            averaging_down_count=averaging_down_count,
            current_price=threshold,
            period_low=committed_bottom_price,
            max_gap_percent=maximum_bottom_gap_percent,
        )
        if light_pickling_price:
            st.info(
                f"浅漬け株価：{threshold:,.0f}円（最長{light_pickling_days}日）を基準にしています。"
            )
        elif use_current_price:
            st.info(f"現在の株価（直近取引日の終値）：{threshold:,.0f}円を基準にしています。")
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
        if streaks.empty:
            st.warning("該当する取引日はありませんでした。")
            recent_graph_slot = st.empty()
            full_graph_slot = st.empty()
        else:
            recent_graph_slot = st.empty()
            full_graph_slot = st.empty()
            display_streaks = streaks.copy()
            display_streaks["開始日"] = display_streaks["開始日"].map(format_date_ja)
            display_streaks["終了日"] = display_streaks["終了日"].map(format_date_ja)
            latest_prices = prices[column].dropna()
            if not latest_prices.empty and latest_prices.iloc[-1] <= threshold:
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
            nanpin_columns = ["初回投資"] + [
                f"第{step}ナンピン" for step in range(1, averaging_down_count + 1)
            ]
            cumulative_investment_amounts = []
            cumulative_profit_losses = []
            cumulative_investment = 0.0
            cumulative_shares = 0.0
            for step, (amount, investment_price) in enumerate(
                zip(
                    nanpin_plan["investment_amounts"],
                    nanpin_plan["investment_prices"],
                )
            ):
                cumulative_investment += float(amount)
                cumulative_shares += float(amount) / float(investment_price)
                cumulative_investment_amounts.append(
                    format_man_yen(cumulative_investment)
                )
                profit_loss = (
                    cumulative_shares * float(investment_price)
                    - cumulative_investment
                )
                profit_loss_amount = format_man_yen(abs(profit_loss))
                if profit_loss < 0 and profit_loss_amount != "0万円":
                    profit_loss_amount = f"-{profit_loss_amount}"
                elif profit_loss > 0 and profit_loss_amount != "0万円":
                    profit_loss_amount = f"+{profit_loss_amount}"
                cumulative_profit_losses.append(profit_loss_amount)
            nanpin_display = pd.DataFrame(
                [
                    [
                        "投資株価",
                        *[
                            format_yen(price)
                            for price in nanpin_plan["investment_prices"]
                        ],
                    ],
                    [
                        "投資額",
                        *[
                            format_man_yen(amount)
                            for amount in nanpin_plan["investment_amounts"]
                        ],
                    ],
                    ["合計投資額", *cumulative_investment_amounts],
                    [
                        "平均取得株価",
                        *[
                            format_nanpin_price(average_price, investment_price)
                            for average_price, investment_price in zip(
                                nanpin_plan["average_prices"],
                                nanpin_plan["investment_prices"],
                            )
                        ],
                    ],
                    ["損益", *cumulative_profit_losses],
                ],
                columns=["", *nanpin_columns],
            )
            nanpin_styles = pd.DataFrame(
                "", index=nanpin_display.index, columns=nanpin_display.columns
            )
            for nanpin_column in nanpin_columns:
                if "-" in str(nanpin_display.at[3, nanpin_column]):
                    nanpin_styles.at[3, nanpin_column] = (
                        "color: #DC2626; font-weight: 700;"
                    )
                if "-" in str(nanpin_display.at[4, nanpin_column]):
                    nanpin_styles.at[4, nanpin_column] = (
                        "color: #DC2626; font-weight: 700;"
                    )
            styled_nanpin = nanpin_display.style.apply(
                lambda _: nanpin_styles, axis=None
            ).set_table_styles(TABLE_HEADER_STYLES)
            mobile_nanpin_display = (
                nanpin_display.set_index("").T.reset_index().rename(
                    columns={"index": "投資段階"}
                )
            )
            mobile_nanpin_styles = pd.DataFrame(
                "", index=mobile_nanpin_display.index,
                columns=mobile_nanpin_display.columns
            )
            for row_index in mobile_nanpin_display.index:
                if "-" in str(mobile_nanpin_display.at[row_index, "平均取得株価"]):
                    mobile_nanpin_styles.at[row_index, "平均取得株価"] = (
                        "color: #DC2626; font-weight: 700;"
                    )
                if "-" in str(mobile_nanpin_display.at[row_index, "損益"]):
                    mobile_nanpin_styles.at[row_index, "損益"] = (
                        "color: #DC2626; font-weight: 700;"
                    )
            styled_mobile_nanpin = mobile_nanpin_display.style.apply(
                lambda _: mobile_nanpin_styles, axis=None
            ).set_table_styles(TABLE_HEADER_STYLES)
            table_height = 250
            with st.container(key="desktop_results_table"):
                render_results_table(
                    styled_nanpin, table_height, limit_vertical_height=False
                )
                st.caption(
                    "ナンピン株価は現在値から最終ナンピンの期間最安値まで"
                    f"均等に設定し、最終購入後の平均取得株価が期間最安値から"
                    f"{maximum_bottom_gap_percent}％以内に収まるよう投資額を配分しています。"
                )

            with st.container(key="mobile_results_table"):
                render_results_table(
                    styled_mobile_nanpin,
                    38 * (len(mobile_nanpin_display) + 1) + 4,
                    limit_vertical_height=False,
                )
                st.caption(
                    "ナンピン株価は現在値から最終ナンピンの期間最安値まで"
                    f"均等に設定し、最終購入後の平均取得株価が期間最安値から"
                    f"{maximum_bottom_gap_percent}％以内に収まるよう投資額を配分しています。"
                )
            csv = display_streaks.to_csv(index=False).encode("utf-8-sig")
            st.download_button("結果をCSVで保存", csv, "nissan_price_streaks.csv", "text/csv")

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
        final_average_price = float(nanpin_plan["average_prices"][-1])
        chart["最終平均以下"] = chart["株価"] <= final_average_price
        final_average_changes = chart["最終平均以下"].ne(
            chart["最終平均以下"].shift()
        ).cumsum()
        chart["最終平均連続区間"] = final_average_changes.where(
            chart["最終平均以下"]
        )
        nanpin_stage_colors = [
            "#E67E22",
            "#7C3AED",
            "#059669",
            "#DB2777",
            "#0891B2",
            "#CA8A04",
            "#4F46E5",
            "#C2410C",
            "#0F766E",
            "#9333EA",
            "#BE123C",
        ]
        investment_prices = [
            float(value) for value in nanpin_plan["investment_prices"]
        ]
        average_prices = [
            float(value) for value in nanpin_plan["average_prices"]
        ]
        initial_average_price = average_prices[0]
        chart["初回平均超"] = chart["株価"] > initial_average_price
        initial_average_changes = chart["初回平均超"].ne(
            chart["初回平均超"].shift()
        ).cumsum()
        chart["初回平均超連続区間"] = initial_average_changes.where(
            chart["初回平均超"]
        )
        price_segment_rows = []
        for segment_index in range(len(chart) - 1):
            start_row = chart.iloc[segment_index]
            end_row = chart.iloc[segment_index + 1]
            start_date_value = pd.Timestamp(start_row["日付"])
            end_date_value = pd.Timestamp(end_row["日付"])
            start_price = float(start_row["株価"])
            end_price = float(end_row["株価"])

            def append_price_segment(
                segment_start_date,
                segment_end_date,
                segment_start_price,
                segment_end_price,
                color,
            ):
                price_segment_rows.append(
                    {
                        "開始日": segment_start_date,
                        "終了日": segment_end_date,
                        "開始株価": segment_start_price,
                        "終了株価": segment_end_price,
                        "株価線色": color,
                    }
                )

            starts_above = start_price > initial_average_price
            ends_above = end_price > initial_average_price
            if starts_above == ends_above or start_price == end_price:
                append_price_segment(
                    start_date_value,
                    end_date_value,
                    start_price,
                    end_price,
                    "#E67E22" if starts_above else "#2563EB",
                )
                continue

            crossing_ratio = (
                initial_average_price - start_price
            ) / (end_price - start_price)
            crossing_date = start_date_value + (
                end_date_value - start_date_value
            ) * crossing_ratio
            append_price_segment(
                start_date_value,
                crossing_date,
                start_price,
                initial_average_price,
                "#E67E22" if starts_above else "#2563EB",
            )
            append_price_segment(
                crossing_date,
                end_date_value,
                initial_average_price,
                end_price,
                "#E67E22" if ends_above else "#2563EB",
            )
        price_segments = pd.DataFrame(price_segment_rows)
        above_price_points = []
        for orange_segment_id, (_, segment_row) in enumerate(
            price_segments[price_segments["株価線色"] == "#E67E22"].iterrows()
        ):
            above_price_points.extend(
                [
                    {
                        "日付": segment_row["開始日"],
                        "株価": segment_row["開始株価"],
                        "オレンジ区間": orange_segment_id,
                    },
                    {
                        "日付": segment_row["終了日"],
                        "株価": segment_row["終了株価"],
                        "オレンジ区間": orange_segment_id,
                    },
                ]
            )
        above_price_points = pd.DataFrame(above_price_points)
        active_segment = 0
        active_stage_labels = []
        active_stage_colors = []
        active_segment_ids = []
        previous_stage = None
        for chart_price in chart["株価"].astype(float):
            active_stage = len(average_prices) - 1
            for stage_index, average_price in enumerate(average_prices):
                if chart_price >= average_price:
                    active_stage = stage_index
                    break
            if active_stage != previous_stage:
                active_segment += 1
            active_stage_labels.append(
                "初回投資" if active_stage == 0 else f"第{active_stage}ナンピン"
            )
            active_stage_colors.append(nanpin_stage_colors[active_stage])
            active_segment_ids.append(active_segment)
            previous_stage = active_stage
        chart["ナンピン有効段階"] = active_stage_labels
        chart["ナンピン線色"] = active_stage_colors
        chart["ナンピン連続区間"] = active_segment_ids
        chart_segments = pd.DataFrame(
            {
                "開始日": chart["日付"].iloc[:-1].to_numpy(),
                "終了日": chart["日付"].iloc[1:].to_numpy(),
                "開始株価": chart["株価"].iloc[:-1].to_numpy(),
                "終了株価": chart["株価"].iloc[1:].to_numpy(),
                "線色": chart["ナンピン線色"].iloc[1:].to_numpy(),
            }
        )

        base = alt.Chart(chart).encode(
            x=alt.X(
                "日付:T",
                title=None,
                axis=alt.Axis(
                    format="%Y年",
                    tickCount="year",
                    labelAngle=0,
                    domain=True,
                    domainColor="#94A3B8",
                    domainWidth=1,
                ),
                scale=alt.Scale(
                    domain=[pd.Timestamp(start_date), pd.Timestamp(end_date)]
                ),
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
        normal_line = base.mark_line(color="#2563EB", strokeWidth=2)
        above_initial_average_line = alt.Chart(above_price_points).mark_line(
            color="#E67E22", strokeWidth=2, strokeCap="butt"
        ).encode(
            x=alt.X(
                "日付:T",
                title=None,
                axis=alt.Axis(format="%Y年", tickCount="year", labelAngle=0),
                scale=alt.Scale(
                    domain=[pd.Timestamp(start_date), pd.Timestamp(end_date)]
                ),
            ),
            y=alt.Y(
                "株価:Q",
                title=f"{label}（円）",
                scale=alt.Scale(zero=False),
            ),
            detail="オレンジ区間:N",
        )
        final_average_below = base.transform_filter(
            alt.datum["最終平均以下"] == True
        )
        final_average_below_line = final_average_below.mark_line(
            color="#DC2626", strokeWidth=3
        ).encode(
            detail="最終平均連続区間:N"
        )
        final_average_below_points = final_average_below.mark_circle(
            color="#DC2626", size=45
        )
        nanpin_recovery_line = base.transform_filter(
            alt.datum["ナンピン有効段階"] != None
        ).mark_line(strokeWidth=3).encode(
            color=alt.Color("ナンピン線色:N", scale=None, legend=None),
            detail="ナンピン連続区間:N",
        )
        nanpin_average_band_line = alt.Chart(chart_segments).mark_rule(
            strokeWidth=3
        ).encode(
            x=alt.X(
                "開始日:T",
                axis=None,
                scale=alt.Scale(
                    domain=[pd.Timestamp(start_date), pd.Timestamp(end_date)]
                ),
            ),
            x2="終了日:T",
            y=alt.Y("開始株価:Q", axis=None, scale=alt.Scale(zero=False)),
            y2="終了株価:Q",
            color=alt.Color("線色:N", scale=None, legend=None),
        )
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
        nanpin_line_data = pd.DataFrame(
            {
                "投資段階": ["初回投資"]
                + [
                    f"第{step}ナンピン" for step in range(1, averaging_down_count + 1)
                ],
                "ナンピン株価": nanpin_plan["investment_prices"],
                "線色": nanpin_stage_colors[: averaging_down_count + 1],
                "表示": [
                    f"{stage} {format_man_yen(amount)}"
                    for stage, amount in zip(
                        ["初回投資"]
                        + [
                            f"第{step}ナンピン"
                            for step in range(1, averaging_down_count + 1)
                        ],
                        nanpin_plan["investment_amounts"],
                    )
                ],
                "ラベル位置": [
                    pd.Timestamp(start_date)
                    + (pd.Timestamp(end_date) - pd.Timestamp(start_date)) / 2
                ]
                * (averaging_down_count + 1),
            }
        )
        nanpin_price_lines = alt.Chart(nanpin_line_data).mark_rule(
            strokeWidth=2, opacity=0.95
        ).encode(
            y="ナンピン株価:Q",
            color=alt.Color("線色:N", scale=None, legend=None),
            tooltip=[
                alt.Tooltip("投資段階:N", title="投資段階"),
                alt.Tooltip("ナンピン株価:Q", title="投資株価", format=",.0f"),
            ],
        )
        nanpin_price_label_backgrounds = alt.Chart(nanpin_line_data).mark_text(
            align="center",
            baseline="bottom",
            dy=-3,
            color="#FFFFFF",
            stroke="#FFFFFF",
            strokeWidth=6,
            opacity=0.96,
            fontSize=16,
            fontWeight="bold",
        ).encode(
            x="ラベル位置:T",
            y="ナンピン株価:Q",
            text="表示:N",
        )
        nanpin_price_labels = alt.Chart(nanpin_line_data).mark_text(
            align="center",
            baseline="bottom",
            dy=-3,
            fontSize=16,
            fontWeight="bold",
        ).encode(
            x="ラベル位置:T",
            y="ナンピン株価:Q",
            text="表示:N",
            color=alt.Color("線色:N", scale=None, legend=None),
        )
        recent_end = chart["日付"].max()
        recent_start = recent_end - pd.DateOffset(years=1)
        recent_chart = chart[chart["日付"] >= recent_start].copy()
        recent_above_price_points = above_price_points[
            above_price_points["日付"] >= recent_start
        ].copy()
        recent_chart_segments = chart_segments[
            chart_segments["終了日"] >= recent_start
        ].copy()
        recent_nanpin_line_data = nanpin_line_data.copy()
        recent_nanpin_line_data["ラベル位置"] = (
            recent_start + (recent_end - recent_start) / 2
        )
        recent_nanpin_price_label_backgrounds = alt.Chart(
            recent_nanpin_line_data
        ).mark_text(
            align="center",
            baseline="bottom",
            dy=-3,
            color="#FFFFFF",
            stroke="#FFFFFF",
            strokeWidth=6,
            opacity=0.96,
            fontSize=16,
            fontWeight="bold",
        ).encode(
            x="ラベル位置:T",
            y="ナンピン株価:Q",
            text="表示:N",
        )
        recent_nanpin_price_labels = alt.Chart(recent_nanpin_line_data).mark_text(
            align="center",
            baseline="bottom",
            dy=-3,
            fontSize=16,
            fontWeight="bold",
        ).encode(
            x="ラベル位置:T",
            y="ナンピン株価:Q",
            text="表示:N",
            color=alt.Color("線色:N", scale=None, legend=None),
        )
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
        recent_above_initial_average_line = alt.Chart(
            recent_above_price_points
        ).mark_line(
            color="#E67E22", strokeWidth=2, strokeCap="butt", clip=True
        ).encode(
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
            detail="オレンジ区間:N",
        )
        recent_nanpin_recovery_line = recent_base.transform_filter(
            alt.datum["ナンピン有効段階"] != None
        ).mark_line(strokeWidth=3).encode(
            color=alt.Color("ナンピン線色:N", scale=None, legend=None),
            detail="ナンピン連続区間:N",
        )
        recent_nanpin_average_band_line = alt.Chart(
            recent_chart_segments
        ).mark_rule(strokeWidth=3, clip=True).encode(
            x=alt.X(
                "開始日:T",
                axis=None,
                scale=alt.Scale(domain=[recent_start, recent_end]),
            ),
            x2="終了日:T",
            y=alt.Y("開始株価:Q", axis=None, scale=alt.Scale(zero=False)),
            y2="終了株価:Q",
            color=alt.Color("線色:N", scale=None, legend=None),
        )
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
            recent_evaluation_start = pd.Timestamp(recent_pickling["日付"].min())
            recent_evaluation_chart = recent_chart[
                recent_chart["日付"] >= recent_evaluation_start
            ]
        else:
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
        extrema_labels = alt.Chart(extrema_annotations).mark_text(
            dy=-14, fontSize=12, fontWeight="bold", color="#16A34A"
        ).encode(
            x="日付:T",
            y="株価:Q",
            text="注記:N",
        )
        full_period_title = (
            '<div class="full-period-title" style="font-size:20px;font-weight:700;">'
            f'期間：<span class="mobile-title-break"></span>'
            f"{format_month_ja(start_date)}～{format_month_ja(end_date)}"
            "</div>"
        )
        full_period_chart = (
            year_lines
            + normal_line
            + above_initial_average_line
            + nanpin_price_lines
            + nanpin_price_label_backgrounds
            + nanpin_price_labels
        ).properties(height=640)
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
        mobile_above_initial_average_line = alt.Chart(above_price_points).mark_line(
            color="#E67E22", strokeWidth=2, strokeCap="butt"
        ).encode(
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
            ),
            y=alt.Y(
                "株価:Q",
                title=f"{label}（円）",
                scale=alt.Scale(zero=False),
            ),
            detail="オレンジ区間:N",
        )
        mobile_full_period_chart = (
            year_lines
            + mobile_normal_line
            + mobile_above_initial_average_line
            + nanpin_price_lines
            + nanpin_price_label_backgrounds
            + nanpin_price_labels
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
                "<div>現在高値の可能性があるため評価不可です。</div>"
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
                f"<div>直近1年の塩漬け開始後（{recent_statistics_period}）の"
                f"<br>最安値は"
                f'<strong style="color:#DC2626;">'
                f"{recent_low_percent:+d}％（{recent_low:,.0f}円）</strong>で"
                f'<strong style="color:#DC2626;">{low_assessment}</strong>、<br>'
                f"最高値は"
                f'<strong style="color:#2563EB;">'
                f"{recent_high_percent:+d}％（{recent_high:,.0f}円）</strong>で"
                f'<strong style="color:#2563EB;">{high_assessment}</strong>です。</div>'
                f'<div><strong style="color:{outlook_color};">'
                f"{outlook_summary}</strong></div>"
            )
        purchase_context = (
            f"現在の株価{threshold:,.0f}円で購入した場合、"
            if use_current_price
            else f"{threshold:,.0f}円で購入した場合、"
        )
        nanpin_review_lines = []
        nanpin_mobile_review_lines = []
        for step, (investment_price, investment_amount, average_price) in enumerate(
            zip(
                nanpin_plan["investment_prices"],
                nanpin_plan["investment_amounts"],
                nanpin_plan["average_prices"],
            )
        ):
            stage_label = "初回投資" if step == 0 else f"第{step}ナンピン"
            if step == 0:
                nanpin_review_lines.append(
                    '<div style="margin-bottom:12px;">'
                    f"{escape(company_name)}の現在株価"
                    f"{format_yen(investment_price)}に<br>初回は"
                    f'<span style="color:#2563EB;">'
                    f"{format_man_yen(investment_amount)}</span>投資し…</div>"
                )
                nanpin_mobile_review_lines.append(
                    '<div class="nanpin-review-section">'
                    f"{escape(company_name)}の現在株価"
                    f"{format_yen(investment_price)}に<br>初回は"
                    f'<span style="color:#2563EB;">'
                    f"{format_man_yen(investment_amount)}</span>投資し…</div>"
                )
                continue
            average_gap = calculate_nanpin_gap_percent(
                average_price, investment_price
            )
            average_gap_text = f"{average_gap:+d}" if average_gap else "0"
            nanpin_review_lines.append(
                f"<div>{stage_label}は株価{format_yen(investment_price)}に"
                f'<span style="color:#2563EB;">'
                f"{format_man_yen(investment_amount)}</span> "
                f'<strong style="color:#DC2626;">平均取得{average_gap_text}％</strong>'
                "</div>"
            )
            nanpin_mobile_review_lines.append(
                f'<div class="nanpin-review-section">{stage_label}は株価'
                f"{format_yen(investment_price)}に<br>"
                f'<span style="color:#2563EB;">'
                f"{format_man_yen(investment_amount)}</span> "
                f'<strong style="color:#DC2626;">平均取得'
                f"{average_gap_text}％</strong></div>"
            )
        final_investment_price = float(nanpin_plan["investment_prices"][-1])
        final_average_gap = calculate_nanpin_gap_percent(
            float(nanpin_plan["average_prices"][-1]), final_investment_price
        )
        final_average_gap_text = (
            f"{final_average_gap:+d}" if final_average_gap else "0"
        )
        total_nanpin_investment = sum(nanpin_plan["investment_amounts"])
        allocation_stage_labels = [
            "初回投資" if step == 0 else f"第{step}ナンピン"
            for step in range(len(nanpin_plan["investment_amounts"]))
        ]
        allocation_data = pd.DataFrame(
            {
                "投資段階": allocation_stage_labels,
                "_順番": list(range(len(allocation_stage_labels))),
                "円内表示": [
                    "初回" if step == 0 else f"第{step}"
                    for step in range(len(allocation_stage_labels))
                ],
                "投資額": nanpin_plan["investment_amounts"],
                "投資額表示": [
                    format_man_yen(amount)
                    for amount in nanpin_plan["investment_amounts"]
                ],
                "割合": [
                    f"{amount / total_nanpin_investment * 100:.0f}％"
                    for amount in nanpin_plan["investment_amounts"]
                ],
            }
        ).sort_values(["投資額", "_順番"], ascending=[True, True])
        allocation_data = allocation_data.reset_index(drop=True)
        allocation_data["_開始角"] = (
            allocation_data["投資額"].cumsum().shift(fill_value=0)
            / total_nanpin_investment
            * 2
            * pi
        )
        allocation_data["_終了角"] = (
            allocation_data["投資額"].cumsum()
            / total_nanpin_investment
            * 2
            * pi
        )
        allocation_data["_中央角"] = (
            allocation_data["_開始角"] + allocation_data["_終了角"]
        ) / 2
        allocation_color = alt.Color(
            "投資段階:N",
            scale=alt.Scale(
                domain=allocation_stage_labels,
                range=nanpin_stage_colors[: len(allocation_stage_labels)],
            ),
            legend=None,
        )
        allocation_tooltips = [
            alt.Tooltip("投資段階:N", title="投資段階"),
            alt.Tooltip("投資額表示:N", title="投資額"),
            alt.Tooltip("割合:N", title="割合"),
        ]
        allocation_arcs = alt.Chart(allocation_data).mark_arc(
            outerRadius=90, stroke="#FFFFFF", strokeWidth=2
        ).encode(
            theta=alt.Theta("_開始角:Q", scale=None),
            theta2=alt.Theta2("_終了角:Q"),
            color=allocation_color,
            tooltip=allocation_tooltips,
        )
        allocation_labels = alt.Chart(allocation_data).mark_text(
            radius=60,
            color="#FFFFFF",
            fontSize=13,
            fontWeight="bold",
        ).encode(
            theta=alt.Theta("_中央角:Q", scale=None),
            text="円内表示:N",
            color=alt.value("#FFFFFF"),
            tooltip=allocation_tooltips,
        )
        allocation_chart = (allocation_arcs + allocation_labels).properties(
            height=260
        )
        mobile_allocation_chart = (allocation_arcs + allocation_labels).properties(
            height=220
        )
        nanpin_review_html = (
            '<div class="nanpin-review-plan" style="margin-top:16px;font-weight:700;font-size:16px;line-height:1.8;">'
            + '<div class="nanpin-review-desktop">'
            + "".join(nanpin_review_lines)
            + '<div style="margin-top:12px;">このように投資をすれば<br>'
            + '<span style="color:#2563EB;">株価'
            + f"{format_yen(final_investment_price)}まで</span>落ちても合計"
            + '<span style="color:#2563EB;">'
            + f"{format_man_yen(total_nanpin_investment)}</span>を投資する事で<br>"
            + '<strong style="color:#DC2626;">平均取得株価'
            + f"{format_yen(final_average_price)} ({final_average_gap_text}％)</strong>"
            + "に抑えることが可能です。"
            + "</div></div>"
            + '<div class="nanpin-review-mobile">'
            + "".join(nanpin_mobile_review_lines)
            + '<div class="nanpin-review-section">このように投資をすれば'
            + '<span style="color:#2563EB;">株価'
            + f"{format_yen(final_investment_price)}まで</span>落ちても合計"
            + '<span style="color:#2563EB;">'
            + f"{format_man_yen(total_nanpin_investment)}</span>を投資する事で"
            + '<strong style="color:#DC2626;">平均取得株価'
            + f"{format_yen(final_average_price)} ({final_average_gap_text}％)</strong>に"
            + "抑えることが可能です。</div></div></div>"
        )
        review_price_context = (
            f"現在{format_yen(threshold)}　"
            f"底値{format_yen(float(nanpin_plan['period_low']))}とした場合"
        )
        review_header_html = (
            '<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">'
            f'<span class="review-card-grade" style="display:inline-block;padding:3px 11px;border-radius:999px;'
            f'background:{grade_color};color:#FFFFFF;font-size:18px;font-weight:700;white-space:nowrap;">'
            f"{review_price_context}</span></div>"
        )
        review_note_html = (
            '<div style="font-size:14px;color:#64748B;margin-top:8px;">'
            "※過去の株価に基づく傾向であり、将来の利益を保証するものではありません。"
            "</div>"
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
                        + recent_above_initial_average_line
                        + nanpin_price_lines
                        + recent_nanpin_price_label_backgrounds
                        + recent_nanpin_price_labels
                    ).properties(height=320),
                    use_container_width=True,
                )
                with st.container(key="mobile_full_period_graph"):
                    st.markdown(full_period_title, unsafe_allow_html=True)
                    st.altair_chart(mobile_full_period_chart, use_container_width=True)
            with review_column:
                with st.container(key="nanpin_indicator_card", border=True):
                    st.markdown(review_header_html, unsafe_allow_html=True)
                    with st.container(key="nanpin_plan_content"):
                        review_text_column, allocation_column = st.columns(
                            [2.2, 1], vertical_alignment="top"
                        )
                        with review_text_column:
                            st.markdown(nanpin_review_html, unsafe_allow_html=True)
                        with allocation_column:
                            with st.container(key="nanpin_allocation_chart_desktop"):
                                st.markdown(
                                    '<div style="font-size:15px;font-weight:700;'
                                    'text-align:center;margin-top:10px;">'
                                    "投資資産の分布</div>",
                                    unsafe_allow_html=True,
                                )
                                st.altair_chart(
                                    allocation_chart, use_container_width=True
                                )
                            with st.container(key="nanpin_allocation_chart_mobile"):
                                st.altair_chart(
                                    mobile_allocation_chart, use_container_width=True
                                )
                    st.markdown(review_note_html, unsafe_allow_html=True)
                    render_bottom_price_form(threshold)
        render_app_banners(security_code, active_search_prefix, start_date.year)
        render_company_info(company_name, ticker, company_info)
        scroll_to_result("search-results-anchor")
    except Exception as exc:
        st.error(f"処理できませんでした: {exc}")
        st.caption("証券コードとインターネット接続をご確認のうえ、もう一度お試しください。")

