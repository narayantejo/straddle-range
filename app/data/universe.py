"""
NSE F&O stock universe: derived from the DhanHQ instrument master CSV.

We do NOT hard-code a stock list. Every refresh re-derives the universe from
the live instrument master, so newly added F&O stocks appear automatically
and discontinued ones drop off.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app import config
from app.data import dhan_constants as C
from app.data.dhan_client import DhanClient

CACHE_DIR = config.ROOT_DIR / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
INSTRUMENT_MASTER_CACHE = CACHE_DIR / "instrument_master.csv"


@dataclass(frozen=True)
class FnoStock:
    symbol: str  # UNDERLYING_SYMBOL, e.g. "RELIANCE"
    company_name: str
    equity_security_id: int  # NSE_EQ security id, used as UnderlyingScrip
    lot_size: int
    near_future_security_id: int | None = None  # nearest-expiry FUTSTK contract, for OI/volume
    near_future_expiry: str | None = None


def refresh_instrument_master(client: DhanClient | None = None) -> Path:
    """Download the latest instrument master CSV to the local cache."""
    client = client or DhanClient()
    client.download_instrument_master_csv(str(INSTRUMENT_MASTER_CACHE))
    return INSTRUMENT_MASTER_CACHE


def _load_master() -> pd.DataFrame:
    if not INSTRUMENT_MASTER_CACHE.exists():
        refresh_instrument_master()
    return pd.read_csv(INSTRUMENT_MASTER_CACHE, low_memory=False)


def get_fno_universe(refresh: bool = False) -> list[FnoStock]:
    """
    Return the complete current NSE F&O stock universe (equity derivatives only --
    excludes index derivatives such as NIFTY/BANKNIFTY, and excludes exchange
    test scrips).
    """
    if refresh:
        refresh_instrument_master()
    df = _load_master()

    fno_derivatives = df[
        (df[C.COL_EXCH_ID] == "NSE")
        & (df[C.COL_SEGMENT] == C.SEGMENT_DERIVATIVES)
        & (df[C.COL_INSTRUMENT].isin([C.INSTRUMENT_FUTSTK, C.INSTRUMENT_OPTSTK]))
        & (~df[C.COL_UNDERLYING_SYMBOL].astype(str).str.contains(C.TEST_SYMBOL_MARKER, na=False))
    ]

    underlying_ids = (
        fno_derivatives[[C.COL_UNDERLYING_SYMBOL, C.COL_UNDERLYING_SECURITY_ID]]
        .dropna()
        .drop_duplicates()
    )

    equities = df[(df[C.COL_EXCH_ID] == "NSE") & (df[C.COL_SEGMENT] == C.SEGMENT_EQUITY)]
    equities_by_id = equities.set_index(C.COL_SECURITY_ID)

    futures = fno_derivatives[fno_derivatives[C.COL_INSTRUMENT] == C.INSTRUMENT_FUTSTK].copy()
    futures_sorted = futures.sort_values(C.COL_EXPIRY_DATE)
    near_future_by_symbol = futures_sorted.drop_duplicates(
        subset=[C.COL_UNDERLYING_SYMBOL], keep="first"
    ).set_index(C.COL_UNDERLYING_SYMBOL)

    lot_sizes = futures.groupby(C.COL_UNDERLYING_SYMBOL)[C.COL_LOT_SIZE].first()

    stocks: list[FnoStock] = []
    for _, row in underlying_ids.iterrows():
        symbol = row[C.COL_UNDERLYING_SYMBOL]
        eq_security_id = int(row[C.COL_UNDERLYING_SECURITY_ID])
        if eq_security_id not in equities_by_id.index:
            continue  # cannot resolve underlying equity contract; skip rather than guess
        eq_row = equities_by_id.loc[eq_security_id]
        if isinstance(eq_row, pd.DataFrame):
            eq_row = eq_row.iloc[0]
        company_name = str(eq_row[C.COL_SYMBOL_NAME])
        lot_size = int(lot_sizes.get(symbol, 0))

        near_future_security_id = None
        near_future_expiry = None
        if symbol in near_future_by_symbol.index:
            fut_row = near_future_by_symbol.loc[symbol]
            near_future_security_id = int(fut_row[C.COL_SECURITY_ID])
            near_future_expiry = str(fut_row[C.COL_EXPIRY_DATE])[:10]

        stocks.append(
            FnoStock(
                symbol=symbol,
                company_name=company_name,
                equity_security_id=eq_security_id,
                lot_size=lot_size,
                near_future_security_id=near_future_security_id,
                near_future_expiry=near_future_expiry,
            )
        )

    stocks.sort(key=lambda s: s.symbol)
    return stocks
