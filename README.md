# NSE F&O Straddle-Based Monthly Support & Resistance Scanner

A support/resistance scanner for the NSE Futures & Options stock universe.
Monthly S1/S2/R1/R2 levels are derived from the previous monthly expiry's EOD
spot price and the next-month ATM CE/PE straddle premiums (via the DhanHQ v2
API), then held fixed for the whole cycle while a daily scanner tracks
proximity, zone status, reactions (bounce/rejection/breakout/breakdown), and
signal strength against those levels — with configurable alerts.

**Status:** `main` is the stable baseline, tagged `v1.0-stable`. See
[Versioning](#versioning--branching) below before making changes.

---

## Feature overview

### 1. F&O universe
- Full NSE equity F&O stock list (currently ~210 stocks), derived live from
  DhanHQ's instrument master CSV — **no hard-coded stock list**. Refreshing
  the universe automatically picks up newly added F&O stocks and drops
  discontinued ones.
- Resolves each stock's equity security ID, lot size, and nearest-expiry
  futures contract (for OI tracking) directly from the instrument master.

### 2. Monthly S/R calculation engine (`app/engine/formulas.py`)
Implements the exact spec formulas, unit-tested (including a mandatory test
that fails if S1 is ever computed with ATM CE instead of ATM PE):

```
STRADDLE = ATM_CE + ATM_PE
MIDPOINT = (ATM_CE + ATM_PE) / 2
R1 = SPOT_LEVEL + ATM_CE
R2 = SPOT_LEVEL + ATM_CE + ATM_PE
S1 = SPOT_LEVEL - ATM_PE      <- uses ATM PE, never ATM CE
S2 = SPOT_LEVEL - ATM_CE - ATM_PE
```

- Configurable `±zone%` band (default 5%) around every level.
- Validates `S2 < S1 < SPOT < R1 < R2` on every calculation; rejects missing,
  zero, or negative inputs rather than silently substituting values.
- Levels are calculated **once per monthly cycle** and stored immutably —
  never recalculated mid-cycle, never overwritten (`app/db/schema.sql`:
  `UNIQUE(symbol, calculation_month)`).

### 3. Expiry resolution (`app/engine/expiry.py`)
- Live path: on the actual reference-expiry trading day, reads the exchange's
  own expiry list directly — no calendar guessing.
- Bootstrap path: mid-cycle, the already-passed reference expiry is inferred
  from NSE's documented rule (last Tuesday of the month, SEBI circular
  effective 2025-09-01) and then **verified against real historical trading
  data**, walking backward through holidays until an actual trading day with
  data is found. This is the only place the app infers a date rather than
  reading it from the exchange.

### 4. Daily scanner (`app/scanner/daily_scanner.py`)
Per stock, per scan:
- Live spot (batched `/marketfeed/quote`, up to 1000 instruments/request)
- Distance to each of S2/S1/R1/R2 — absolute, signed, and %
- Zone status per level: `FAR → APPROACHING → VERY_CLOSE → INSIDE_ZONE → TOUCH`
- Nearest support, nearest resistance, and the single absolute-nearest level
- Direction (`UP`/`DOWN`/`SIDEWAYS`), from the stock's own accumulated scan
  history — no extra per-stock API calls needed, so it scales to the full
  universe in ~2 batched requests regardless of stock count
- Futures OI and volume (batched `/marketfeed/quote` on the near-month
  futures contract), with day-over-day % change computed from prior scans

### 5. Breakout/breakdown confirmation (`app/engine/confirmation.py`)
A single tick beyond a level is **never** treated as a confirmed break.
Independently togglable checks (sidebar):
- Candle close beyond the level
- Minimum % penetration
- N consecutive closes beyond the level
- Volume confirmation (today's volume vs. trailing average)
- Futures OI confirmation (rising OI in the direction of the move)
- Momentum (pluggable hook for an external signal)

All enabled checks must pass for a break to count as confirmed.

### 6. Reaction classification (`app/engine/reaction.py`)
Layers actual market behavior on top of the static zone status:
`BOUNCE` (support + reversal up), `REJECTED` (resistance + reversal down),
`BREAKOUT` (confirmed break above resistance), `BREAKDOWN` (confirmed break
below support) — explicitly kept separate from the calculated level itself,
per the spec's distinction between a *calculated* level and a *confirmed
reaction*.

### 7. Signal scoring (`app/engine/signal_scoring.py`)
0–100 score blending proximity, zone entry, direction, price action/reaction,
volume, and futures OI (option-activity slot is pluggable for a future
phase). Missing factors are excluded from the weighted average rather than
penalizing the score. Produces a human-readable signal type (e.g. `SUPPORT
BOUNCE`, `STRONG BREAKOUT`, `RESISTANCE TEST`, `NO SETUP`).

### 8. Option-buying mode
`CE WATCH` / `PE WATCH` flags for stocks genuinely engaged with a support or
resistance zone (not just loosely "approaching" — that band is too wide to
be useful as a filter). Explicitly labeled in the UI as a scanner signal, not
a trading recommendation; proximity alone never creates a buy signal.

### 9. Alerts (`app/alerts/`)
- Configurable rules: per symbol (or all stocks), per level (S1/S2/R1/R2/
  ANY), per condition (`WITHIN_PCT`, `INSIDE_ZONE`, `TOUCH`, `BOUNCE`,
  `REJECTED`, `BREAKOUT`, `BREAKDOWN`)
- Deduplicated per rule+symbol+level+condition+day, so re-running the scanner
  mid-day doesn't spam repeats
- Channels: dashboard (always on, zero setup), email and Telegram (both
  **disabled until you add credentials to `.env`** — see `.env.example`)

### 10. Dashboard (`streamlit_app.py`)
Tabs: All F&O Stocks · Support Watch · Resistance Watch · Breakout Watch ·
Breakdown Watch · Option Buying Mode · Alerts (recent alerts + rule
management) · Chart (candlestick with S/R lines) · Calculation Audit (full
derivation trail: reference expiry, spot, pricing expiry, ATM strike, CE, PE,
straddle, midpoint, every level and its zone — exactly how the spec's audit
screen is described).

### 11. Historical database (`app/db/schema.sql`)
- `monthly_levels`: append-only, immutable, one row per stock per cycle —
  the full historical record of every calculation ever made.
- `daily_scans`: append-only snapshot per stock per scan (spot, distances,
  zone statuses, reactions, direction, volume/OI, signal score/type,
  CE/PE watch flags) — this is what the (not-yet-built) backtesting engine
  and statistical analysis phase will consume.
- `alert_rules` / `alert_log`: rule configuration and a full fired-alert
  history.

### 12. Tests
71 unit tests (`pytest tests/`), covering the formula engine (including the
mandatory S1-uses-ATM-PE check), direction classification, confirmation
logic, reaction classification, signal scoring, and the alert engine's
condition matching and dedup behavior. All pure-logic modules are tested
without hitting the live API; the DhanHQ integration itself has been
verified end-to-end against the live account.

---

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your DhanHQ `DHAN_CLIENT_ID` and
`DHAN_ACCESS_TOKEN`. Email/Telegram alert credentials in the same file are
optional — leave them blank to keep those channels off.

## Run

```bash
python -m streamlit run streamlit_app.py
```

(or `run_windows.bat` on Windows). Then in the sidebar, in order:
1. **Refresh F&O universe**
2. **Run monthly rollover** (batchable — option-chain calls are rate-limited
   to 1/3s, so a full-universe rollover takes ~15-20 minutes)
3. **Run daily scan** (fast — batched quote calls regardless of universe size)
4. **Load default alert rules** (one-time, optional)

## Tests

```bash
python -m pytest tests/ -v
```

---

## Architecture

```
app/data/       DhanHQ client, instrument-master-derived F&O universe
app/engine/     formulas.py, expiry.py, monthly_engine.py, direction.py,
                confirmation.py, reaction.py, signal_scoring.py
app/scanner/    daily_scanner.py
app/alerts/     rules.py, engine.py, notifiers.py
app/db/         SQLite schema + access
app/pipeline.py High-level orchestration shared by the CLI scripts and the dashboard
scripts/        run_full_rollover.py (headless full-universe rollover)
streamlit_app.py  Dashboard
```

---

## Versioning / branching

- **`main`** — the stable, verified baseline. Currently tagged
  `v1.0-stable`. Nothing lands here except a deliberate merge from `develop`
  once a round of changes has been reviewed and confirmed.
- **`develop`** — where new work happens. Feel free to iterate here freely;
  `main` is never at risk.
- To go back to any past stable point: `git checkout v1.0-stable` (or
  whichever tag). Tags are never deleted or moved.

## Known DhanHQ-side reliability notes

Two upstream issues were observed and worked around during development —
neither is a bug in this codebase:
- `/v2/charts/historical` intermittently returns `DH-907 Data_Error` for
  requests that succeed moments later with identical parameters (matches
  reports on DhanHQ's community forum). Affects the Chart tab and new
  monthly rollovers' EOD-spot fetch; the daily scanner, signals, and alerts
  don't use this endpoint and are unaffected. Error messages surfacing
  `DH-905`/`DH-907` include a note pointing here.
- `/v2/optionchain` occasionally returns a transient `500 Internal Server
  Error` under sustained load (e.g. a full-universe rollover). The rollover
  is idempotent and skips stocks that already have current-cycle levels, so
  simply re-running `scripts/run_full_rollover.py` backfills exactly the
  stocks that failed.

## Deferred (next phase)

- **Backtesting engine** (spec sections 34-38): strategy configuration,
  no-look-ahead historical reconstruction, trade statistics, level
  performance analysis (touch/bounce/breakout rates). Needs real accumulated
  `daily_scans` history to be meaningful — intentionally deferred until the
  scanner has been run for a while.
- **Statistical level-performance analysis**, built on the same history.
- Option-activity (live option volume/OI) as a signal-scoring factor — the
  slot exists in `compute_signal_score()` but isn't populated yet, since
  re-querying the option chain daily would hit DhanHQ's option-chain rate
  limit across the full universe.
