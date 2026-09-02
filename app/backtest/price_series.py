"""
Daily equity price series for a monthly cycle, used by the level-performance
statistics and trade simulator. Sourced from DhanHQ's /charts/historical
(proven reliable for equity EOD data throughout this project) -- unlike the
option-premium problem, there's no reason to route this through bhavcopy too.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

from app.data.dhan_client import DhanApiError, DhanClient
from app.data.dhan_constants import EXCHANGE_SEGMENT_NSE_EQ, INSTRUMENT_EQUITY
from app.data.universe import FnoStock


class PriceSeriesError(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyBar:
    trade_date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float


def get_cycle_price_series(
    client: DhanClient, stock: FnoStock, reference_expiry: str, pricing_expiry: str
) -> list[DailyBar]:
    """
    Daily bars strictly AFTER reference_expiry through pricing_expiry
    (inclusive) -- i.e. the trading days the monthly levels were actually
    "live" for. reference_expiry's own bar is excluded since that day
    produced the levels, not react to them.
    """
    from_date = date.fromisoformat(reference_expiry) + timedelta(days=1)
    to_date = date.fromisoformat(pricing_expiry) + timedelta(days=1)  # /charts/historical toDate is exclusive
    try:
        hist = client.get_historical_daily(
            security_id=stock.equity_security_id,
            exchange_segment=EXCHANGE_SEGMENT_NSE_EQ,
            instrument=INSTRUMENT_EQUITY,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
        )
    except DhanApiError as e:
        raise PriceSeriesError(f"{stock.symbol}: failed to fetch price series: {e}") from e

    closes = hist.get("close") or []
    if not closes:
        raise PriceSeriesError(f"{stock.symbol}: no price data for {from_date}..{to_date}")

    bars = []
    for i, ts in enumerate(hist["timestamp"]):
        bars.append(
            DailyBar(
                trade_date=datetime.fromtimestamp(ts, IST).date().isoformat(),
                open=hist["open"][i],
                high=hist["high"][i],
                low=hist["low"][i],
                close=hist["close"][i],
                volume=hist["volume"][i],
            )
        )
    return bars
