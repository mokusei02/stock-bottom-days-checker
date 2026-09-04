from __future__ import annotations

import base64
import json
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf


LABELS = {"Close": "終値", "Low": "安値", "Open": "始値", "High": "高値"}
START_YEAR_OPTIONS = list(range(2000, 2030, 5))
SEARCH_HISTORY_FILE = Path(__file__).with_name(".search_history.json")
SEARCH_HISTORY_COOKIE = "stock_search_history"
TABLE_HEADER_STYLES = [
    {
        "selector": "th",
        "props": [("color", "#111111"), ("font-weight", "700")],
    }
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


def find_streaks(df: pd.DataFrame, column: str, threshold: float) -> pd.DataFrame:
    prices = df[column].dropna()
    below = prices <= threshold
    group = below.ne(below.shift()).cumsum()
    next_high_column = f"次の{threshold:,.0f}円までの最高値（円）"
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


@st.cache_data
def load_company_options() -> list[str]:
    companies = pd.read_csv(
        Path(__file__).with_name("companies.csv"), dtype={"code": str}
    )
    return [f"{row.code}｜{row.name}" for row in companies.itertuples(index=False)]


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
        "XX円（この価格以下）",
        min_value=0,
        value=320,
        step=1,
        key=f"{key_prefix}_threshold",
    )
    if not current_price_after_dates:
        use_current_price = st.checkbox(
            "現在の株価",
            value=False,
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
            value=False,
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
    return (
        security_code,
        threshold,
        use_current_price,
        light_pickling_price,
        start_date,
        end_date,
        run,
    )


st.set_page_config(page_title="塩漬け日数チェッカー", page_icon="📉", layout="wide")

# Older versions stored search history in the URL. Remove that legacy parameter
# now that history is persisted locally, so the address always stays clean.
if "history" in st.query_params:
    del st.query_params["history"]
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
    .st-key-mobile_results_table { display: none; }
    .st-key-mobile_search_history { display: none; }
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
        background: #dedede;
    }
    .st-key-nukazuke_summary [data-testid="stMetricValue"] {
        justify-content: center;
        text-align: center;
    }
    .st-key-desktop_results_table [role="columnheader"],
    .st-key-mobile_results_table [role="columnheader"] {
        color: #111111 !important;
        font-weight: 700 !important;
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
        .st-key-mobile_filters { display: block; }
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
with st.container(key="mobile_search_history"):
    render_search_history("mobile")
st.markdown(
    '<div class="app-footer">制作者：木星在住　'
    '<a href="https://x.com/mokuseidayo" target="_blank">Twitter</a></div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("検索条件")
    desktop_values = render_search_controls("desktop", show_end_date=False)
    if st.session_state.pop("desktop_history_run", False):
        desktop_values = (*desktop_values[:-1], True)
    if desktop_values[-1]:
        add_desktop_search_history(desktop_values)
    render_search_history("desktop")

if mobile_values[-1]:
    security_code, threshold, use_current_price, light_pickling_price, start_date, end_date, run = mobile_values
else:
    security_code, threshold, use_current_price, light_pickling_price, start_date, end_date, run = desktop_values
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

        streaks = find_streaks(prices, column, threshold)
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
        else:
            st.subheader(
                f"{format_month_ja(start_date)}から{format_month_ja(end_date)}まで"
                f"{company_name}が{threshold:,.0f}円以下の塩漬け期間"
            )
        if streaks.empty:
            st.warning("該当する取引日はありませんでした。")
        else:
            render_nukazuke_summary(streaks)
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
            table_height = 38 * (len(streaks) + 1) + 4
            with st.container(key="desktop_results_table"):
                desktop_column_names = {
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

        chart = prices[[column]].dropna().reset_index()
        chart.columns = ["日付", "株価"]
        chart["基準以下"] = chart["株価"] <= threshold
        changes = chart["基準以下"].ne(chart["基準以下"].shift()).cumsum()
        chart["連続区間"] = changes.where(chart["基準以下"])

        base = alt.Chart(chart).encode(
            x=alt.X(
                "日付:T",
                title="年",
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
        threshold_line = alt.Chart(pd.DataFrame({"基準価格": [threshold]})).mark_rule(
            color="#DC2626", strokeDash=[6, 4], opacity=0.65
        ).encode(y="基準価格:Q")
        st.altair_chart(
            (normal_line + below_line + below_points + threshold_line).properties(height=420),
            use_container_width=True,
        )
        render_company_info(company_name, ticker, company_info)
    except Exception as exc:
        st.error(f"処理できませんでした: {exc}")
        st.caption("証券コードとインターネット接続をご確認のうえ、もう一度お試しください。")

