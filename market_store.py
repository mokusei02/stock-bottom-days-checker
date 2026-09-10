"""Read immutable daily market snapshots; the web server never downloads quotes."""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

REPOSITORY = "mokusei02/stock-bottom-days-checker"
BRANCH = "market-data"
_last_snapshot = None
_local_snapshot_setting = os.getenv("MARKET_STORE_LOCAL_DIR")
LOCAL_SNAPSHOT_DIR = Path(_local_snapshot_setting) if _local_snapshot_setting else None


def read_url(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "stock-days-snapshot/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def raw_url(revision: str, path: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid data revision")
    if not re.fullmatch(r"(?:prices/[0-9A-Z]+\.T\.csv|nikkei225\.zip|manifest\.json)", path):
        raise ValueError("Invalid data path")
    return f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/{path}"


def get_snapshot() -> tuple[str, dict]:
    global _last_snapshot
    try:
        pointer = json.loads(read_url(f"https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}/latest.json"))
        revision = pointer["revision"]
        manifest = json.loads(read_url(raw_url(revision, "manifest.json")))
        if manifest.get("schema") != 1 or not manifest.get("prices"):
            raise ValueError("Empty market snapshot")
        _last_snapshot = (revision, manifest)
    except Exception as error:
        try:
            if LOCAL_SNAPSHOT_DIR is None:
                raise FileNotFoundError("Local snapshot is disabled")
            pointer = json.loads((LOCAL_SNAPSHOT_DIR / "latest.json").read_text(encoding="utf-8"))
            revision = pointer["revision"]
            manifest = json.loads((LOCAL_SNAPSHOT_DIR / "manifest.json").read_text(encoding="utf-8"))
            _last_snapshot = (revision, manifest)
        except (OSError, ValueError, KeyError, TypeError):
            if _last_snapshot is None:
                raise RuntimeError("保存株価データを読み込めませんでした。時間をおいてお試しください。") from error
    return _last_snapshot


def parse_prices(content: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content), parse_dates=["Date"], index_col="Date")
    required = ["Open", "High", "Low", "Close"]
    if frame.empty or not set(required).issubset(frame):
        raise ValueError("Empty or invalid price data")
    frame = frame[required].apply(pd.to_numeric, errors="coerce").dropna()
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    if frame.empty or (frame <= 0).any().any():
        raise ValueError("Invalid OHLC data")
    return frame


def read_prices(revision: str, ticker: str, manifest: dict) -> pd.DataFrame:
    entry = manifest["prices"].get(ticker)
    if entry is None:
        raise RuntimeError("この銘柄の保存データはまだ取得できていません。次回の更新をお待ちください。")
    try:
        return parse_prices(read_url(raw_url(revision, entry["path"])))
    except (OSError, ValueError) as error:
        try:
            if LOCAL_SNAPSHOT_DIR is None:
                raise FileNotFoundError("Local snapshot is disabled")
            return parse_prices((LOCAL_SNAPSHOT_DIR / entry["path"]).read_bytes())
        except (OSError, ValueError, KeyError) as local_error:
            raise RuntimeError("保存株価データの読み込みに失敗しました。時間をおいてお試しください。") from local_error


def read_nikkei(revision: str, manifest: dict) -> pd.DataFrame:
    entry = manifest.get("ranking")
    if not entry:
        raise RuntimeError("ランキング用データの初回更新がまだ完了していません。")
    try:
        with zipfile.ZipFile(io.BytesIO(read_url(raw_url(revision, entry["path"])))) as archive:
            frames = {name.removesuffix(".csv"): parse_prices(archive.read(name)) for name in archive.namelist()}
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        try:
            if LOCAL_SNAPSHOT_DIR is None:
                raise FileNotFoundError("Local snapshot is disabled")
            with zipfile.ZipFile(LOCAL_SNAPSHOT_DIR / entry["path"]) as archive:
                frames = {name.removesuffix(".csv"): parse_prices(archive.read(name)) for name in archive.namelist()}
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as local_error:
            raise RuntimeError("保存ランキングデータの読み込みに失敗しました。時間をおいてお試しください。") from local_error
    if set(frames) != set(entry["tickers"]):
        raise RuntimeError("ランキング用データが不完全です。")
    return pd.concat(frames, axis=1)
