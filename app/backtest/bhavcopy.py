"""
NSE F&O Bhav Copy: the exchange's own official daily settlement file.

One CSV per trading day covers every stock, every strike, every expiry --
OHLC, last-traded/close price, settlement price, open interest, and volume
for every listed derivative contract, plus the underlying's own reference
price (UndrlygPric). This is the authoritative source for historical option
premiums used by the backtesting engine, chosen after finding DhanHQ's
/charts/rollingoption endpoint too slow (~30s/query) and unreliable
(frequent 504s and empty responses) for building a historical dataset from.

URL format confirmed live on 2026-09-02:
    https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
Non-trading days (weekends, holidays) return 404 -- this IS the trading-day
verification, no separate check needed.

Requires a browser-like User-Agent; NSE's archive host rejects requests
without one.
"""
from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

from app import config

CACHE_DIR = config.ROOT_DIR / "data" / "cache" / "bhavcopy"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

BHAVCOPY_URL_TEMPLATE = (
    "https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date}_F_0000.csv.zip"
)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Columns we actually use, kept narrow to keep the cached parquet small.
_USE_COLS = [
    "TradDt", "TckrSymb", "XpryDt", "StrkPric", "OptnTp",
    "ClsPric", "LastPric", "UndrlygPric", "SttlmPric",
    "OpnIntrst", "TtlTradgVol", "TtlNbOfTxsExctd",
]


class BhavcopyUnavailableError(RuntimeError):
    """Raised when a trading day's bhavcopy can't be fetched -- may mean the
    exchange was closed that day (holiday/weekend), or a real download
    failure. Callers must not guess/substitute; treat as a hard stop for
    that date."""


def _cache_path(date_str: str) -> Path:
    return CACHE_DIR / f"{date_str}.parquet"


def get_bhavcopy(date_str: str) -> pd.DataFrame:
    """
    Returns the parsed bhavcopy for date_str (YYYY-MM-DD) as a DataFrame,
    downloading and caching it (as parquet) on first use. Raises
    BhavcopyUnavailableError if the exchange has no data for that date
    (holiday, weekend, or a genuine fetch failure).
    """
    compact_date = date_str.replace("-", "")
    cache_file = _cache_path(date_str)
    if cache_file.exists():
        return pd.read_parquet(cache_file)

    url = BHAVCOPY_URL_TEMPLATE.format(date=compact_date)
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    except requests.exceptions.RequestException as e:
        raise BhavcopyUnavailableError(f"Bhavcopy fetch failed for {date_str}: {e}") from e

    if resp.status_code == 404:
        raise BhavcopyUnavailableError(
            f"No bhavcopy for {date_str} -- likely a non-trading day (holiday/weekend)."
        )
    if resp.status_code != 200:
        raise BhavcopyUnavailableError(f"Bhavcopy fetch failed [{resp.status_code}] for {date_str}")

    try:
        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, usecols=_USE_COLS, low_memory=False)
    except (zipfile.BadZipFile, ValueError) as e:
        raise BhavcopyUnavailableError(f"Bhavcopy for {date_str} is not a valid zip/csv: {e}") from e

    df.to_parquet(cache_file, index=False)
    return df


def get_underlying_price(df: pd.DataFrame, symbol: str) -> float | None:
    rows = df[df["TckrSymb"] == symbol]
    if rows.empty:
        return None
    return float(rows.iloc[0]["UndrlygPric"])


def get_available_expiries(df: pd.DataFrame, symbol: str, option_type: str = "CE") -> list[str]:
    rows = df[(df["TckrSymb"] == symbol) & (df["OptnTp"] == option_type)]
    return sorted(rows["XpryDt"].unique())


def get_option_row(
    df: pd.DataFrame, symbol: str, expiry_date: str, strike: float, option_type: str
) -> dict | None:
    rows = df[
        (df["TckrSymb"] == symbol)
        & (df["XpryDt"] == expiry_date)
        & (df["StrkPric"] == strike)
        & (df["OptnTp"] == option_type)
    ]
    if rows.empty:
        return None
    return rows.iloc[0].to_dict()


def get_available_strikes(
    df: pd.DataFrame, symbol: str, expiry_date: str, option_type: str
) -> list[float]:
    rows = df[
        (df["TckrSymb"] == symbol) & (df["XpryDt"] == expiry_date) & (df["OptnTp"] == option_type)
    ]
    return sorted(rows["StrkPric"].unique().tolist())
