import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from app.backtest import bhavcopy


@pytest.fixture()
def sample_df() -> pd.DataFrame:
    rows = [
        # symbol, expiry, strike, type, close, last, underlying, settle, oi, volume, txns
        ("RELIANCE", "2026-08-25", 1290.0, "CE", 30.0, 30.0, 1288.0, 30.0, 1000, 500, 100),
        ("RELIANCE", "2026-08-25", 1290.0, "PE", 28.0, 28.0, 1288.0, 28.0, 900, 400, 90),
        ("RELIANCE", "2026-09-29", 1290.0, "CE", 45.0, 45.0, 1288.0, 45.0, 500, 200, 50),
        ("RELIANCE", "2026-09-29", 1290.0, "PE", 40.0, 40.0, 1288.0, 40.0, 450, 0, 0),  # untraded
        ("RELIANCE", "2026-09-29", 1310.0, "CE", 35.0, 35.0, 1288.0, 35.0, 300, 100, 20),
        ("TCS", "2026-09-29", 3000.0, "CE", 60.0, 60.0, 2995.0, 60.0, 200, 50, 10),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "ClsPric", "LastPric",
            "UndrlygPric", "SttlmPric", "OpnIntrst", "TtlTradgVol", "TtlNbOfTxsExctd",
        ],
    )


def test_get_underlying_price(sample_df):
    assert bhavcopy.get_underlying_price(sample_df, "RELIANCE") == 1288.0


def test_get_underlying_price_missing_symbol(sample_df):
    assert bhavcopy.get_underlying_price(sample_df, "NOPE") is None


def test_get_available_expiries(sample_df):
    expiries = bhavcopy.get_available_expiries(sample_df, "RELIANCE", "CE")
    assert expiries == ["2026-08-25", "2026-09-29"]


def test_get_available_strikes(sample_df):
    strikes = bhavcopy.get_available_strikes(sample_df, "RELIANCE", "2026-09-29", "CE")
    assert strikes == [1290.0, 1310.0]


def test_get_option_row(sample_df):
    row = bhavcopy.get_option_row(sample_df, "RELIANCE", "2026-09-29", 1290.0, "CE")
    assert row is not None
    assert row["ClsPric"] == 45.0
    assert row["TtlTradgVol"] == 200


def test_get_option_row_untraded_still_returned(sample_df):
    """bhavcopy.get_option_row itself doesn't filter on volume -- that's the
    caller's (historical_levels) job, so an untraded row must still be
    retrievable for inspection."""
    row = bhavcopy.get_option_row(sample_df, "RELIANCE", "2026-09-29", 1290.0, "PE")
    assert row is not None
    assert row["TtlTradgVol"] == 0


def test_get_option_row_missing_returns_none(sample_df):
    row = bhavcopy.get_option_row(sample_df, "RELIANCE", "2026-09-29", 9999.0, "CE")
    assert row is None


def test_symbols_are_isolated(sample_df):
    strikes = bhavcopy.get_available_strikes(sample_df, "TCS", "2026-09-29", "CE")
    assert strikes == [3000.0]
