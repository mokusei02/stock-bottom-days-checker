"""Daily full-history snapshots. Never overwrite valid data with failed downloads.

Only market data is written to the separate data checkout, never user searches.
Full histories are refreshed so stock splits cannot corrupt previously saved prices.
"""
from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import zipfile

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from market_store import parse_prices

JST = timezone(timedelta(hours=9))


def ranking_codes():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "NIKKEI225_CODES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("Nikkei universe missing")


def fetch(ticker, end):
    try:
        prices = yf.Ticker(ticker).history(start="2000-01-01", end=end, auto_adjust=False, actions=False, raise_errors=True, timeout=20)
        prices.index = prices.index.tz_localize(None).normalize()
        prices = prices[["Open", "High", "Low", "Close"]].dropna()
        # Providers occasionally return zero-valued historical OHLC rows. Exclude
        # those missing-price rows instead of treating zero as a real stock low.
        prices = prices.loc[(prices > 0).all(axis=1)]
        prices.index.name = "Date"
        content = prices.to_csv(date_format="%Y-%m-%d").encode("utf-8")
        validated = parse_prices(content)
        return ticker, content, validated.index[-1].date().isoformat(), None
    except YFRateLimitError:
        return ticker, None, None, "rate_limit"
    except Exception as error:
        return ticker, None, None, type(error).__name__


def update(output: Path, only_nikkei=False, workers=2):
    now = datetime.now(JST)
    day = now.date()
    if now.time() < time(16):
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    end = (day + timedelta(days=1)).isoformat()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema": 1, "prices": {}}
    manifest = json.loads(json.dumps(old))
    nikkei = [f"{code}.T" for code in ranking_codes()]
    all_codes = pd.read_csv(ROOT / "companies.csv", dtype=str)["code"]
    universe = nikkei if only_nikkei else list(dict.fromkeys(nikkei + [f"{c}.T" for c in all_codes]))
    yf.set_tz_cache_location(str(ROOT / ".yfinance-cache"))
    # Initialize the SQLite/cookie caches in one thread before any worker starts.
    first = fetch(universe[0], end)
    if first[3] == "rate_limit":
        raise RuntimeError("Provider rate limit: previous snapshot left unchanged")
    pending = {}
    failed = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda ticker: fetch(ticker, end), universe[1:])
        import itertools
        for index, (ticker, content, latest, error) in enumerate(itertools.chain([first], results), 1):
            if error:
                failed.append(ticker)
                print(f"Unavailable: {ticker} ({error})", flush=True)
                if error == "rate_limit":
                    # No partial publication when the provider has limited access.
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise RuntimeError("Provider rate limit: previous snapshot left unchanged")
            else:
                pending[ticker] = content
                manifest["prices"][ticker] = {"path": f"prices/{ticker}.csv", "latest_date": latest, "fetched_at": now.isoformat(timespec="seconds")}
            if index % 100 == 0:
                print(f"Fetched {index}/{len(universe)}", flush=True)
    if not pending:
        raise RuntimeError("No valid prices; previous snapshot left unchanged")
    (output / "prices").mkdir(exist_ok=True)
    for ticker, content in pending.items():
        (output / "prices" / f"{ticker}.csv").write_bytes(content)
    # Rankings are refreshed only from a complete, same-run Nikkei universe.
    if all(ticker in pending for ticker in nikkei):
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for ticker in nikkei:
                archive.writestr(f"{ticker}.csv", pending[ticker])
        (output / "nikkei225.zip").write_bytes(bundle.getvalue())
        manifest["ranking"] = {"path": "nikkei225.zip", "tickers": nikkei, "as_of": max(manifest["prices"][t]["latest_date"] for t in nikkei), "fetched_at": now.isoformat(timespec="seconds")}
    manifest.update(generated_at=now.isoformat(timespec="seconds"), target_date=day.isoformat(), failed_tickers=failed)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(pending)} symbols; retained previous data for {len(failed)} failures", flush=True)
    if not manifest.get("ranking"):
        raise RuntimeError("Initial Nikkei snapshot incomplete; do not publish")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only-nikkei", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    update(args.output, args.only_nikkei, args.workers)
