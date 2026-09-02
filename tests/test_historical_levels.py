import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from app.backtest import bhavcopy, historical_levels
from app.backtest.expiry_calendar import MonthlyExpiry
from app.backtest.historical_levels import HistoricalDataError, reconstruct_monthly_cycle


def _fake_df(ce_close, pe_close, ce_vol, pe_vol, spot=1250.0, strike=1250.0):
    rows = [
        ("RELIANCE", "2025-12-30", strike, "CE", ce_close, spot, ce_close, ce_vol, 100),
        ("RELIANCE", "2025-12-30", strike, "PE", pe_close, spot, pe_close, pe_vol, 100),
    ]
    return pd.DataFrame(
        rows,
        columns=["TckrSymb", "XpryDt", "StrkPric", "OptnTp", "ClsPric", "UndrlygPric", "SttlmPric", "TtlTradgVol", "TtlNbOfTxsExctd"],
    )


_EXPIRY_BY_MONTH = {
    (2025, 11): "2025-11-25",
    (2025, 12): "2025-12-30",
}


@pytest.fixture()
def patch_expiries(monkeypatch):
    def _fake_resolve(symbol, year, month):
        return MonthlyExpiry(
            calculation_month=f"{year:04d}-{month:02d}",
            expiry_date=_EXPIRY_BY_MONTH[(year, month)],
        )

    monkeypatch.setattr(historical_levels, "resolve_monthly_expiry", _fake_resolve)


def test_rejects_zero_volume_by_default(monkeypatch, patch_expiries):
    df = _fake_df(ce_close=80.0, pe_close=70.0, ce_vol=0, pe_vol=500)
    monkeypatch.setattr(bhavcopy, "get_bhavcopy", lambda d: df)
    with pytest.raises(HistoricalDataError, match="zero traded volume"):
        reconstruct_monthly_cycle("RELIANCE", 2025, 11)


def test_accepts_zero_volume_when_disabled(monkeypatch, patch_expiries):
    df = _fake_df(ce_close=80.0, pe_close=70.0, ce_vol=0, pe_vol=500)
    monkeypatch.setattr(bhavcopy, "get_bhavcopy", lambda d: df)
    cycle = reconstruct_monthly_cycle("RELIANCE", 2025, 11, require_traded_volume=False)
    assert cycle.levels.atm_ce == 80.0


def test_rejects_implausible_straddle(monkeypatch, patch_expiries):
    # straddle = 0.05 + 8.8 = 8.85, spot=1250 -> 0.7%, below the 1% floor
    df = _fake_df(ce_close=0.05, pe_close=8.8, ce_vol=500, pe_vol=500)
    monkeypatch.setattr(bhavcopy, "get_bhavcopy", lambda d: df)
    with pytest.raises(HistoricalDataError, match="plausible band"):
        reconstruct_monthly_cycle("RELIANCE", 2025, 11)


def test_accepts_plausible_straddle(monkeypatch, patch_expiries):
    df = _fake_df(ce_close=40.0, pe_close=35.0, ce_vol=500, pe_vol=500)
    monkeypatch.setattr(bhavcopy, "get_bhavcopy", lambda d: df)
    cycle = reconstruct_monthly_cycle("RELIANCE", 2025, 11)
    assert cycle.levels.straddle == pytest.approx(75.0)
    assert cycle.levels.s2 < cycle.levels.s1 < cycle.levels.spot_level < cycle.levels.r1 < cycle.levels.r2


def test_missing_underlying_price_raises(monkeypatch, patch_expiries):
    df = _fake_df(ce_close=40.0, pe_close=35.0, ce_vol=500, pe_vol=500)
    df["TckrSymb"] = "OTHERSTOCK"  # RELIANCE not present at all
    monkeypatch.setattr(bhavcopy, "get_bhavcopy", lambda d: df)
    with pytest.raises(HistoricalDataError, match="no underlying price"):
        reconstruct_monthly_cycle("RELIANCE", 2025, 11)


def test_bhavcopy_unavailable_propagates_as_historical_data_error(monkeypatch, patch_expiries):
    def _raise(d):
        raise bhavcopy.BhavcopyUnavailableError("no file")

    monkeypatch.setattr(bhavcopy, "get_bhavcopy", _raise)
    with pytest.raises(HistoricalDataError):
        reconstruct_monthly_cycle("RELIANCE", 2025, 11)
