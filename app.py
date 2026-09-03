from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf


LABELS = {"Close": "終値", "Low": "安値", "Open": "始値", "High": "高値"}


def format_date_ja(value) -> str:
    return pd.Timestamp(value).strftime("%Y年%m月%d日")


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
        return pd.DataFrame(columns=["開始日", "終了日", "下回った日数", "期間中最安値（円）", next_high_column])

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


def render_search_controls(
    key_prefix: str,
    show_end_date: bool = True,
    start_date_label: str = "開始日",
    start_date_value: date = date(2010, 1, 1),
    current_price_after_dates: bool = False,
):
    company_options = load_company_options()
    default_index = next(
        (index for index, option in enumerate(company_options) if option.startswith("7201｜")),
        0,
    )
    selected_company = st.selectbox(
        "企業名・証券コード",
        options=company_options,
        index=default_index,
        key=f"{key_prefix}_company",
        accept_new_options=True,
        help="企業名または証券コードを入力して、候補から選択してください。",
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
            "現在の株価", value=False, key=f"{key_prefix}_use_current_price"
        )
    end_date = (
        st.date_input("終了日", value=date.today(), key=f"{key_prefix}_end")
        if show_end_date
        else date.today()
    )
    latest_start_date = (pd.Timestamp(end_date) - pd.DateOffset(months=1)).date()
    start_date = st.date_input(
        start_date_label,
        value=start_date_value,
        max_value=latest_start_date,
        key=f"{key_prefix}_start",
        help="検索期間が1か月以上になる日付を指定してください。",
    )
    if current_price_after_dates:
        use_current_price = st.checkbox(
            "現在の株価", value=False, key=f"{key_prefix}_use_current_price"
        )
    run = st.button(
        "集計する", type="primary", use_container_width=True, key=f"{key_prefix}_run"
    )
    return security_code, threshold, use_current_price, start_date, end_date, run


st.set_page_config(page_title="底値日数チェッカー", page_icon="📉", layout="wide")
components.html(
    """
    <script>
    for (const page of [window.parent.document, window.top.document]) {
        page.documentElement.lang = "ja";
        page.body?.setAttribute("lang", "ja");
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
        h1 {
            font-size: clamp(1.7rem, 8vw, 2.25rem) !important;
            white-space: nowrap;
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
        .st-key-desktop_results_table { display: none; }
        .st-key-mobile_results_table { display: block; }
        section[data-testid="stSidebar"] { display: none; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("底値日数チェッカー")

with st.container(key="mobile_filters"):
    st.header("検索条件")
    mobile_values = render_search_controls(
        "mobile",
        show_end_date=False,
        start_date_label="検索開始日",
        start_date_value=date(2010, 1, 1),
        current_price_after_dates=True,
    )

st.caption("入力した国内証券コードの株価が、指定価格以下だった連続期間を探します。")
st.markdown(
    '<div class="app-footer">制作者：木星在住　'
    '<a href="https://x.com/mokuseidayo" target="_blank">Twitter</a></div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("検索条件")
    desktop_values = render_search_controls("desktop")

if mobile_values[-1]:
    security_code, threshold, use_current_price, start_date, end_date, run = mobile_values
else:
    security_code, threshold, use_current_price, start_date, end_date, run = desktop_values
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
            if use_current_price:
                threshold = get_current_price(ticker)
            prices = download_prices(ticker, start_date, end_date)
            company_info = get_company_info(ticker)
            company_name = get_company_name(ticker, company_info)
        if column not in prices.columns:
            raise ValueError(f"{label}列がデータにありません。")

        streaks = find_streaks(prices, column, threshold)
        if use_current_price:
            st.info(f"現在の株価（直近取引日の終値）：{threshold:,.0f}円を基準にしています。")
        st.subheader(
            f"{format_date_ja(start_date)}から{format_date_ja(end_date)}まで"
            f"{company_name}が{threshold:,.0f}円以下だった期間"
        )
        if streaks.empty:
            st.warning("該当する取引日はありませんでした。")
        else:
            st.metric("下回った回数", f"{len(streaks)}回")
            display_streaks = streaks.copy()
            display_streaks["開始日"] = display_streaks["開始日"].map(format_date_ja)
            display_streaks["終了日"] = display_streaks["終了日"].map(format_date_ja)
            display_streaks["下回った日数"] = display_streaks["下回った日数"].map(
                lambda value: f"{int(value)}日"
            )
            display_streaks["期間中最安値（円）"] = display_streaks[
                "期間中最安値（円）"
            ].map(
                lambda value: f"{Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)}円"
            )
            next_high_column = f"次の{threshold:,.0f}円までの最高値（円）"
            display_streaks[next_high_column] = display_streaks[next_high_column].map(
                lambda value: "—"
                if pd.isna(value)
                else f"{Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)}円"
            )
            cell_styles = pd.DataFrame(
                "", index=display_streaks.index, columns=display_streaks.columns
            )
            cell_styles.loc[
                streaks["下回った日数"].gt(30), "下回った日数"
            ] = "color: #DC2626; font-weight: 700;"
            cell_styles.loc[
                streaks["下回った日数"].le(7), "下回った日数"
            ] = "color: #2563EB; font-weight: 700;"
            cell_styles.loc[
                streaks["期間中最安値（円）"].lt(threshold * 0.9),
                "期間中最安値（円）",
            ] = "color: #DC2626; font-weight: 700;"
            cell_styles.loc[
                streaks[next_high_column].gt(threshold * 1.1), next_high_column
            ] = "color: #2563EB; font-weight: 700;"
            table_height = 38 * (len(streaks) + 1) + 4
            with st.container(key="desktop_results_table"):
                styled_streaks = display_streaks.style.apply(
                    lambda _: cell_styles, axis=None
                )
                st.dataframe(
                    styled_streaks,
                    hide_index=True,
                    width=850,
                    height=table_height,
                    column_config={
                        "開始日": st.column_config.TextColumn(width="small"),
                        "終了日": st.column_config.TextColumn(width="small"),
                        "下回った日数": st.column_config.TextColumn(width="small"),
                        "期間中最安値（円）": st.column_config.TextColumn(width="small"),
                        next_high_column: st.column_config.TextColumn(width="medium"),
                    },
                    key="desktop_streaks",
                )

            with st.container(key="mobile_results_table"):
                mobile_column_names = {
                    "下回った日数": "連続下落",
                    "期間中最安値（円）": "最安値",
                }
                mobile_display = display_streaks.drop(columns=["終了日"]).rename(
                    columns=mobile_column_names
                )
                mobile_styles = cell_styles.drop(columns=["終了日"]).rename(
                    columns=mobile_column_names
                )
                styled_mobile = mobile_display.style.apply(
                    lambda _: mobile_styles, axis=None
                )
                st.dataframe(
                    styled_mobile,
                    hide_index=True,
                    width=680,
                    height=table_height,
                    column_config={
                        "開始日": st.column_config.TextColumn(width=145),
                        "連続下落": st.column_config.TextColumn(width="small"),
                        "最安値": st.column_config.TextColumn(width="small"),
                        next_high_column: st.column_config.TextColumn(width="medium"),
                    },
                    key="mobile_streaks",
                )
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

