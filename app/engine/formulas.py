"""
Core monthly Support/Resistance formula engine.

CANONICAL FORMULAS (do not change):
    STRADDLE = ATM_CE + ATM_PE
    MIDPOINT = (ATM_CE + ATM_PE) / 2
    R1 = SPOT_LEVEL + ATM_CE
    R2 = SPOT_LEVEL + ATM_CE + ATM_PE
    S1 = SPOT_LEVEL - ATM_PE      <- S1 uses ATM PE, never ATM CE
    S2 = SPOT_LEVEL - ATM_CE - ATM_PE

Zones are +/- zone_pct around each level.
"""
from dataclasses import dataclass


class InvalidMarketDataError(ValueError):
    """Raised when inputs required for a monthly S/R calculation are missing or invalid."""


@dataclass(frozen=True)
class ZoneBand:
    lower: float
    upper: float


@dataclass(frozen=True)
class MonthlyLevels:
    spot_level: float
    atm_strike: float
    atm_ce: float
    atm_pe: float
    straddle: float
    midpoint: float
    r1: float
    r2: float
    s1: float
    s2: float
    zone_pct: float
    s2_zone: ZoneBand
    s1_zone: ZoneBand
    r1_zone: ZoneBand
    r2_zone: ZoneBand


def _validate_inputs(spot_level: float, atm_strike: float, atm_ce: float, atm_pe: float) -> None:
    for name, value in (
        ("spot_level", spot_level),
        ("atm_strike", atm_strike),
        ("atm_ce", atm_ce),
        ("atm_pe", atm_pe),
    ):
        if value is None:
            raise InvalidMarketDataError(f"{name} is missing (None)")
        if value <= 0:
            raise InvalidMarketDataError(f"{name} must be > 0, got {value}")


def _zone(level: float, zone_pct: float) -> ZoneBand:
    lower = level * (1 - zone_pct)
    upper = level * (1 + zone_pct)
    if lower > upper:
        lower, upper = upper, lower
    return ZoneBand(lower=round(lower, 4), upper=round(upper, 4))


def compute_monthly_levels(
    spot_level: float,
    atm_strike: float,
    atm_ce: float,
    atm_pe: float,
    zone_pct: float = 0.05,
) -> MonthlyLevels:
    """
    Compute the fixed monthly S/R structure from the previous-expiry EOD spot
    and the next-month ATM CE/PE premiums.

    zone_pct is expressed as a fraction (0.05 == 5%).
    """
    _validate_inputs(spot_level, atm_strike, atm_ce, atm_pe)
    if zone_pct <= 0:
        raise InvalidMarketDataError(f"zone_pct must be > 0, got {zone_pct}")

    straddle = atm_ce + atm_pe
    midpoint = straddle / 2

    r1 = spot_level + atm_ce
    r2 = spot_level + atm_ce + atm_pe
    s1 = spot_level - atm_pe  # RULE: S1 MUST use ATM PE, never ATM CE
    s2 = spot_level - atm_ce - atm_pe

    if not (s2 < s1 < spot_level < r1 < r2):
        raise InvalidMarketDataError(
            f"Computed levels violate ordering S2<S1<SPOT<R1<R2: "
            f"S2={s2} S1={s1} SPOT={spot_level} R1={r1} R2={r2}"
        )

    return MonthlyLevels(
        spot_level=spot_level,
        atm_strike=atm_strike,
        atm_ce=atm_ce,
        atm_pe=atm_pe,
        straddle=straddle,
        midpoint=midpoint,
        r1=r1,
        r2=r2,
        s1=s1,
        s2=s2,
        zone_pct=zone_pct,
        s2_zone=_zone(s2, zone_pct),
        s1_zone=_zone(s1, zone_pct),
        r1_zone=_zone(r1, zone_pct),
        r2_zone=_zone(r2, zone_pct),
    )


def nearest_atm_strike(spot_price: float, available_strikes: list[float]) -> float:
    """Select the strike closest to spot_price. Ties broken toward the lower strike."""
    if not available_strikes:
        raise InvalidMarketDataError("No available strikes to select ATM from")
    return min(available_strikes, key=lambda k: (abs(k - spot_price), k))


@dataclass(frozen=True)
class DistanceResult:
    abs_distance: float
    signed_distance: float
    distance_pct: float
    abs_distance_pct: float


def compute_distance(current_spot: float, level: float) -> DistanceResult:
    if level == 0:
        raise InvalidMarketDataError("level cannot be zero when computing distance")
    signed = current_spot - level
    pct = (signed / level) * 100
    return DistanceResult(
        abs_distance=round(abs(signed), 4),
        signed_distance=round(signed, 4),
        distance_pct=round(pct, 4),
        abs_distance_pct=round(abs(pct), 4),
    )


ZONE_STATUS_FAR = "FAR"
ZONE_STATUS_APPROACHING = "APPROACHING"
ZONE_STATUS_INSIDE_ZONE = "INSIDE_ZONE"
ZONE_STATUS_VERY_CLOSE = "VERY_CLOSE"
ZONE_STATUS_TOUCH = "TOUCH"


def classify_zone_status(
    current_spot: float,
    level: float,
    zone: ZoneBand,
    approach_threshold_pct: float = 0.10,
    very_close_threshold_pct: float = 0.01,
    touch_threshold_pct: float = 0.001,
) -> str:
    """
    Classify current price relative to a single level's zone.
    Thresholds are fractions (0.01 == 1%).
    Direction-aware statuses (BOUNCE/REJECTED/BREAKOUT/BREAKDOWN) require
    historical price context and are computed separately in the scanner module.
    """
    dist = compute_distance(current_spot, level)
    abs_pct = dist.abs_distance_pct / 100

    if abs_pct <= touch_threshold_pct:
        return ZONE_STATUS_TOUCH
    if zone.lower <= current_spot <= zone.upper:
        if abs_pct <= very_close_threshold_pct:
            return ZONE_STATUS_VERY_CLOSE
        return ZONE_STATUS_INSIDE_ZONE
    if abs_pct <= approach_threshold_pct:
        return ZONE_STATUS_APPROACHING
    return ZONE_STATUS_FAR
