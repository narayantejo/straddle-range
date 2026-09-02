from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import config
from app.alerts import notifiers
from app.alerts.rules import ALL_CONDITIONS, ALL_LEVELS, default_rules
from app.backtest.expiry_calendar import CURRENT_REGIME_START, months_between
from app.backtest.historical_levels import HistoricalDataError, reconstruct_monthly_cycle
from app.backtest.level_stats import aggregate_level_stats, analyze_cycle
from app.backtest.price_series import PriceSeriesError, get_cycle_price_series
from app.backtest.results import compute_results, compute_results_by_level, compute_results_by_strategy
from app.backtest.simulator import simulate_cycle
from app.backtest.strategy import DEFAULT_STRATEGIES, StrategyConfig
from app.data.dhan_client import DhanClient, DhanApiError
from app.data.dhan_constants import EXCHANGE_SEGMENT_NSE_EQ, INSTRUMENT_EQUITY
from app.data.universe import get_fno_universe
from app.db import database as db
from app.engine.confirmation import ConfirmationConfig
from app import pipeline


def backtest_month_options(last_completed_year: int, last_completed_month: int) -> list[str]:
    start_year, start_month = CURRENT_REGIME_START.year, CURRENT_REGIME_START.month
    return [f"{y:04d}-{m:02d}" for y, m in months_between(start_year, start_month, last_completed_year, last_completed_month)]

st.set_page_config(page_title="NSE F&O Straddle S/R Scanner", layout="wide")
db.init_db()

st.title("NSE F&O Straddle-Based Monthly Support & Resistance Scanner")
st.caption(
    "Monthly levels are derived from the previous monthly expiry's EOD spot and the "
    "next-month ATM CE/PE premiums, and stay fixed for the whole cycle. "
    "These are calculated potential zones and scanner signals, not guaranteed support/"
    "resistance or trading recommendations."
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Configuration")

    if not config.DHAN_CLIENT_ID or not config.DHAN_ACCESS_TOKEN:
        st.error("DhanHQ credentials not found in .env")
        st.stop()
    else:
        st.success(f"DhanHQ client ID: {config.DHAN_CLIENT_ID}")

    zone_pct_display = st.selectbox(
        "Zone width (±%)", [1, 2, 3, 4, 5], index=4, help="Applied on the NEXT monthly rollover."
    )
    zone_pct = zone_pct_display / 100.0

    with st.expander("Breakout/breakdown confirmation rules"):
        st.caption("A single tick beyond a level is never enough on its own -- these must ALL pass.")
        require_candle_close = st.checkbox("Candle close beyond level", value=True)
        require_pct_penetration = st.checkbox("Minimum % penetration", value=True)
        pct_penetration_threshold = st.number_input(
            "Penetration threshold (%)", min_value=0.1, max_value=5.0, value=0.5, step=0.1
        )
        require_consecutive_closes = st.checkbox("Consecutive candle closes", value=False)
        consecutive_closes_needed = st.number_input(
            "Consecutive closes needed", min_value=2, max_value=5, value=2
        )
        require_volume_confirmation = st.checkbox("Volume confirmation", value=False)
        volume_ratio_threshold = st.number_input(
            "Volume ratio threshold (vs avg)", min_value=1.0, max_value=5.0, value=1.5, step=0.1
        )
        require_oi_confirmation = st.checkbox("Futures OI confirmation", value=False)
        oi_change_pct_threshold = st.number_input(
            "OI change threshold (%)", min_value=0.5, max_value=20.0, value=2.0, step=0.5
        )

    confirmation_config = ConfirmationConfig(
        require_candle_close=require_candle_close,
        require_pct_penetration=require_pct_penetration,
        pct_penetration_threshold=pct_penetration_threshold,
        require_consecutive_closes=require_consecutive_closes,
        consecutive_closes_needed=int(consecutive_closes_needed),
        require_volume_confirmation=require_volume_confirmation,
        volume_ratio_threshold=volume_ratio_threshold,
        require_oi_confirmation=require_oi_confirmation,
        oi_change_pct_threshold=oi_change_pct_threshold,
    )

    st.divider()
    st.subheader("Data pipeline")

    if st.button("1) Refresh F&O universe", use_container_width=True):
        with st.spinner("Downloading instrument master and rebuilding F&O universe..."):
            stocks = get_fno_universe(refresh=True)
        st.session_state["universe"] = stocks
        st.success(f"Universe refreshed: {len(stocks)} F&O stocks")

    stocks = st.session_state.get("universe") or get_fno_universe()
    st.session_state["universe"] = stocks
    st.caption(f"Current universe: {len(stocks)} stocks")

    rollover_limit = st.number_input(
        "Rollover: max stocks this run",
        min_value=1,
        max_value=len(stocks) if stocks else 1,
        value=min(20, len(stocks)) if stocks else 1,
        help="Option-chain calls are rate-limited to 1 per 3 seconds, so a full "
        "universe rollover takes ~10+ minutes. Run in batches.",
    )

    if st.button("2) Run monthly rollover (missing cycles)", use_container_width=True):
        client = DhanClient()
        progress = st.progress(0.0, text="Starting rollover...")
        target_stocks = stocks[: int(rollover_limit)]

        def _cb(done, total, symbol):
            progress.progress(done / total if total else 1.0, text=f"{symbol} ({done}/{total})")

        succeeded, errors = pipeline.run_universe_rollover(
            client, target_stocks, zone_pct=zone_pct, progress_cb=_cb
        )
        progress.empty()
        st.success(f"Rollover complete: {len(succeeded)} succeeded")
        if errors:
            with st.expander(f"{len(errors)} errors"):
                for e in errors:
                    st.text(e)

    if st.button("3) Run daily scan", use_container_width=True):
        client = DhanClient()
        with st.spinner("Fetching live quotes and scanning..."):
            results, errors, alerts = pipeline.run_universe_daily_scan(
                client, stocks, confirmation_config=confirmation_config
            )
        st.success(f"Scan complete: {len(results)} stocks scanned, {len(alerts)} alerts fired")
        if errors:
            with st.expander(f"{len(errors)} errors / DATA ERRORS"):
                for e in errors:
                    st.text(e)

    st.divider()
    st.subheader("Alerts")
    existing_rules = db.get_all_alert_rules(enabled_only=False)
    st.caption(f"{len(existing_rules)} alert rules configured")
    if st.button("Load default alert rules", use_container_width=True):
        if existing_rules:
            st.warning("Rules already exist -- delete them first if you want to reset to defaults.")
        else:
            for r in default_rules():
                db.insert_alert_rule(db.AlertRuleRow(**r))
            st.success(f"Loaded {len(default_rules())} default rules")

    st.caption(
        f"Email alerts: {'configured' if notifiers.email_configured() else 'not configured (set SMTP_* in .env)'}"
    )
    st.caption(
        f"Telegram alerts: {'configured' if notifiers.telegram_configured() else 'not configured (set TELEGRAM_* in .env)'}"
    )
    st.caption("Dashboard alerts (Alerts tab) always work regardless of email/Telegram setup.")

# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------
rows = pipeline.get_dashboard_rows()

if not rows:
    st.info(
        "No monthly levels stored yet. In the sidebar: refresh the universe, then run the "
        "monthly rollover, then run the daily scan."
    )
    st.stop()

df = pd.DataFrame(rows)

(
    tab_all,
    tab_support,
    tab_resistance,
    tab_breakout,
    tab_breakdown,
    tab_options,
    tab_alerts,
    tab_chart,
    tab_audit,
    tab_backtest,
) = st.tabs(
    [
        "All F&O Stocks",
        "Support Watch",
        "Resistance Watch",
        "Breakout Watch",
        "Breakdown Watch",
        "Option Buying Mode",
        "Alerts",
        "Chart",
        "Calculation Audit",
        "Backtest",
    ]
)

ZONE_COLORS = {
    "TOUCH": "background-color: #ff4d4d; color: white",
    "INSIDE_ZONE": "background-color: #ffb84d",
    "VERY_CLOSE": "background-color: #ffd24d",
    "APPROACHING": "background-color: #ffe999",
    "BOUNCE": "background-color: #4dd965; color: white",
    "REJECTED": "background-color: #4d94ff; color: white",
    "BREAKOUT": "background-color: #2ecc71; color: white; font-weight: bold",
    "BREAKDOWN": "background-color: #e74c3c; color: white; font-weight: bold",
    "FAR": "",
}


def _style_zone(val):
    return ZONE_COLORS.get(val, "")


with tab_all:
    st.subheader(f"Complete F&O Universe ({len(df)} stocks with active monthly levels)")
    display_cols = [
        "Symbol", "Company", "Spot", "S2", "S1", "R1", "R2",
        "Nearest Support", "Dist % (Support)", "Nearest Resistance", "Dist % (Resistance)",
        "Nearest Level", "Dist %", "Zone (Nearest)", "Direction", "Signal Type", "Signal Score",
        "Last Scan",
    ]
    st.dataframe(
        df[display_cols].sort_values("Dist %", key=lambda s: s.abs()).style.map(
            _style_zone, subset=["Zone (Nearest)"]
        ),
        use_container_width=True,
        height=600,
    )

with tab_support:
    st.subheader("Support Watch -- stocks nearest to S1/S2")
    support_df = df[df["Nearest Level"].isin(["S1", "S2"])].copy()
    max_dist = st.slider("Within % of support", 0.5, 15.0, 5.0, step=0.5, key="supp_slider")
    support_df = support_df[support_df["Dist %"].abs() <= max_dist].sort_values(
        "Dist %", key=lambda s: s.abs()
    )
    st.dataframe(
        support_df[
            ["Symbol", "Company", "Spot", "S2", "S1", "Nearest Level", "Dist %", "Zone (Nearest)",
             "Direction", "Signal Type", "Signal Score"]
        ].style.map(_style_zone, subset=["Zone (Nearest)"]),
        use_container_width=True,
        height=600,
    )

with tab_resistance:
    st.subheader("Resistance Watch -- stocks nearest to R1/R2")
    resistance_df = df[df["Nearest Level"].isin(["R1", "R2"])].copy()
    max_dist = st.slider("Within % of resistance", 0.5, 15.0, 5.0, step=0.5, key="res_slider")
    resistance_df = resistance_df[resistance_df["Dist %"].abs() <= max_dist].sort_values(
        "Dist %", key=lambda s: s.abs()
    )
    st.dataframe(
        resistance_df[
            ["Symbol", "Company", "Spot", "R1", "R2", "Nearest Level", "Dist %", "Zone (Nearest)",
             "Direction", "Signal Type", "Signal Score"]
        ].style.map(_style_zone, subset=["Zone (Nearest)"]),
        use_container_width=True,
        height=600,
    )

with tab_breakout:
    st.subheader("Breakout Watch -- confirmed or developing breaks above R1/R2")
    st.caption(
        "A single tick above resistance is never shown here as confirmed -- only reactions the "
        "confirmation rules (sidebar) actually validated."
    )
    breakout_df = df[
        (df["Reaction R1"] == "BREAKOUT") | (df["Reaction R2"] == "BREAKOUT")
    ].copy()
    breakout_df["Breaking Level"] = breakout_df.apply(
        lambda r: "R2" if r["Reaction R2"] == "BREAKOUT" else "R1", axis=1
    )
    breakout_df = breakout_df.sort_values("Signal Score", ascending=False)
    if breakout_df.empty:
        st.info("No confirmed breakouts in the latest scan.")
    else:
        st.dataframe(
            breakout_df[
                ["Symbol", "Company", "Spot", "Breaking Level", "R1", "R2", "Direction",
                 "Signal Type", "Signal Score", "Volume Chg %", "Futures OI Chg %"]
            ],
            use_container_width=True,
            height=500,
        )

with tab_breakdown:
    st.subheader("Breakdown Watch -- confirmed or developing breaks below S1/S2")
    breakdown_df = df[
        (df["Reaction S1"] == "BREAKDOWN") | (df["Reaction S2"] == "BREAKDOWN")
    ].copy()
    breakdown_df["Breaking Level"] = breakdown_df.apply(
        lambda r: "S2" if r["Reaction S2"] == "BREAKDOWN" else "S1", axis=1
    )
    breakdown_df = breakdown_df.sort_values("Signal Score", ascending=False)
    if breakdown_df.empty:
        st.info("No confirmed breakdowns in the latest scan.")
    else:
        st.dataframe(
            breakdown_df[
                ["Symbol", "Company", "Spot", "Breaking Level", "S1", "S2", "Direction",
                 "Signal Type", "Signal Score", "Volume Chg %", "Futures OI Chg %"]
            ],
            use_container_width=True,
            height=500,
        )

with tab_options:
    st.subheader("Option Buying Mode")
    st.warning(
        "CE WATCH / PE WATCH flag that price is engaged with a support/resistance zone. "
        "Proximity alone is NOT a buy signal -- check Direction, Signal Type/Score, and the "
        "confirmation rules in the sidebar before treating anything here as a setup. These are "
        "scanner signals, not guaranteed trading recommendations."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**CE WATCH** -- price engaged with support (potential bounce zone)")
        ce_df = df[df["CE Watch"]].sort_values("Signal Score", ascending=False)
        st.dataframe(
            ce_df[["Symbol", "Spot", "S1", "S2", "Reaction S1", "Reaction S2", "Direction", "Signal Score"]],
            use_container_width=True,
            height=450,
        )
    with c2:
        st.markdown("**PE WATCH** -- price engaged with resistance (potential rejection zone)")
        pe_df = df[df["PE Watch"]].sort_values("Signal Score", ascending=False)
        st.dataframe(
            pe_df[["Symbol", "Spot", "R1", "R2", "Reaction R1", "Reaction R2", "Direction", "Signal Score"]],
            use_container_width=True,
            height=450,
        )

with tab_alerts:
    st.subheader("Alerts")
    sub_recent, sub_rules = st.tabs(["Recent alerts", "Manage rules"])

    with sub_recent:
        recent = db.get_recent_alerts(limit=200)
        if not recent:
            st.info("No alerts fired yet. Load default rules in the sidebar and run a daily scan.")
        else:
            alerts_df = pd.DataFrame([dict(r) for r in recent])
            st.dataframe(
                alerts_df[["fired_at", "symbol", "level_type", "condition_type", "message", "channels_sent"]],
                use_container_width=True,
                height=500,
            )

    with sub_rules:
        rules = db.get_all_alert_rules(enabled_only=False)
        if rules:
            rules_df = pd.DataFrame([dict(r) for r in rules])
            st.dataframe(rules_df, use_container_width=True, height=300)

        with st.form("add_alert_rule"):
            st.markdown("**Add a rule**")
            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                new_symbol = st.text_input("Symbol (blank = all stocks)")
                new_level = st.selectbox("Level", ALL_LEVELS)
            with rc2:
                new_condition = st.selectbox("Condition", ALL_CONDITIONS)
                new_threshold = st.number_input("Threshold % (WITHIN_PCT only)", value=2.0, min_value=0.1)
            with rc3:
                new_channels = st.multiselect("Channels", ["dashboard", "email", "telegram"], default=["dashboard"])
            submitted = st.form_submit_button("Add rule")
            if submitted:
                db.insert_alert_rule(
                    db.AlertRuleRow(
                        symbol=new_symbol.strip().upper() or None,
                        level_type=new_level,
                        condition_type=new_condition,
                        threshold_pct=new_threshold,
                        channels=",".join(new_channels) if new_channels else "dashboard",
                    )
                )
                st.success("Rule added")
                st.rerun()

with tab_chart:
    st.subheader("Interactive Price Chart with Monthly S/R Levels")
    symbol = st.selectbox("Stock", sorted(df["Symbol"].unique()), key="chart_symbol")
    lookback_days = st.slider("Lookback (days)", 30, 180, 90)

    stock = next(s for s in stocks if s.symbol == symbol)
    row = df[df["Symbol"] == symbol].iloc[0]

    try:
        client = DhanClient()
        to_date = date.today() + timedelta(days=1)
        from_date = to_date - timedelta(days=lookback_days)
        hist = client.get_historical_daily(
            security_id=stock.equity_security_id,
            exchange_segment=EXCHANGE_SEGMENT_NSE_EQ,
            instrument=INSTRUMENT_EQUITY,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
        )
        timestamps = pd.to_datetime(hist["timestamp"], unit="s")
        fig = go.Figure()
        fig.add_trace(
            go.Candlestick(
                x=timestamps,
                open=hist["open"],
                high=hist["high"],
                low=hist["low"],
                close=hist["close"],
                name=symbol,
            )
        )
        for level_name, color in [("R2", "red"), ("R1", "orange"), ("S1", "green"), ("S2", "darkgreen")]:
            fig.add_hline(
                y=row[level_name],
                line_dash="dash",
                line_color=color,
                annotation_text=f"{level_name}: {row[level_name]:.2f}",
                annotation_position="right",
            )
        fig.update_layout(height=650, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
    except DhanApiError as e:
        st.error(f"Could not load chart data: {e}")

with tab_audit:
    st.subheader("Calculation Audit Trail")
    symbol = st.selectbox("Stock", sorted(df["Symbol"].unique()), key="audit_symbol")
    row = df[df["Symbol"] == symbol].iloc[0]
    history = db.get_monthly_level_history(symbol)
    latest = history[-1]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""
**Stock:** {symbol} -- {row['Company']}
**Reference (previous) monthly expiry:** {latest['reference_expiry_date']}
**Reference EOD Spot (SPOT_LEVEL):** ₹{latest['reference_spot_price']:.2f}
**Next monthly expiry (pricing):** {latest['pricing_expiry_date']}
**ATM Strike:** ₹{latest['atm_strike']:.2f}
**ATM CE:** ₹{latest['atm_ce']:.2f}
**ATM PE:** ₹{latest['atm_pe']:.2f}
**Straddle (CE+PE):** ₹{latest['straddle_value']:.2f}
**Midpoint:** ₹{latest['midpoint']:.2f}
**Zone:** ±{latest['zone_pct']*100:.1f}%
**Calculated at:** {latest['calculation_timestamp']}
**Data source:** {latest['data_source']}
""")
    with c2:
        st.markdown(f"""
| Level | Value | Zone Lower | Zone Upper |
|---|---:|---:|---:|
| R2 = SPOT + CE + PE | ₹{latest['r2']:.2f} | ₹{latest['r2_lower_zone']:.2f} | ₹{latest['r2_upper_zone']:.2f} |
| R1 = SPOT + CE | ₹{latest['r1']:.2f} | ₹{latest['r1_lower_zone']:.2f} | ₹{latest['r1_upper_zone']:.2f} |
| SPOT LEVEL | ₹{latest['reference_spot_price']:.2f} | -- | -- |
| S1 = SPOT − PE | ₹{latest['s1']:.2f} | ₹{latest['s1_lower_zone']:.2f} | ₹{latest['s1_upper_zone']:.2f} |
| S2 = SPOT − CE − PE | ₹{latest['s2']:.2f} | ₹{latest['s2_lower_zone']:.2f} | ₹{latest['s2_upper_zone']:.2f} |
""")

    st.divider()
    st.subheader("Historical monthly cycles")
    hist_df = pd.DataFrame([dict(r) for r in history])
    st.dataframe(hist_df, use_container_width=True)

with tab_backtest:
    st.subheader("Backtest")
    st.warning(
        "Trades the underlying EQUITY/SPOT price, not actual CE/PE options -- the level "
        "calculation itself still uses the real ATM CE+PE straddle. Historical S/R levels are "
        "reconstructed from NSE's official Bhav Copy, scoped to the verified current Tuesday-"
        "expiry regime (2025-09-01 onward). P&L is a simple per-trade % return, not a "
        "compounded equity curve or capital-sized portfolio. These are backtested scanner "
        "signals, not guaranteed future performance."
    )

    today = date.today()
    last_completed_year, last_completed_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)

    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        bt_symbols = st.multiselect(
            "Stocks", sorted(s.symbol for s in stocks), default=["RELIANCE"], key="bt_symbols"
        )
    with bc2:
        bt_start = st.selectbox(
            "Start month", backtest_month_options(last_completed_year, last_completed_month),
            index=0, key="bt_start",
        )
    with bc3:
        bt_end = st.selectbox(
            "End month", backtest_month_options(last_completed_year, last_completed_month),
            index=len(backtest_month_options(last_completed_year, last_completed_month)) - 1, key="bt_end",
        )

    bc4, bc5, bc6 = st.columns(3)
    with bc4:
        bt_strategy_names = st.multiselect(
            "Strategies", [s.name for s in DEFAULT_STRATEGIES],
            default=[s.name for s in DEFAULT_STRATEGIES], key="bt_strategies",
        )
    with bc5:
        bt_stop = st.number_input("Stop loss %", min_value=0.5, max_value=20.0, value=2.0, step=0.5)
    with bc6:
        bt_target = st.number_input("Target %", min_value=0.5, max_value=20.0, value=4.0, step=0.5)
    bt_max_hold = st.number_input("Max holding days", min_value=1, max_value=60, value=10)

    if st.button("Run backtest", use_container_width=True, key="run_backtest"):
        if not bt_symbols:
            st.error("Select at least one stock.")
        else:
            start_y, start_m = map(int, bt_start.split("-"))
            end_y, end_m = map(int, bt_end.split("-"))
            months = months_between(start_y, start_m, end_y, end_m)
            selected_strategies = tuple(
                StrategyConfig(s.name, s.level_types, s.trigger_reaction, s.direction, bt_stop, bt_target, int(bt_max_hold))
                for s in DEFAULT_STRATEGIES if s.name in bt_strategy_names
            )

            client = DhanClient()
            all_trades = []
            all_level_events = []
            errors = []
            progress = st.progress(0.0, text="Starting backtest...")
            total = len(bt_symbols) * len(months)
            done = 0

            for symbol in bt_symbols:
                stock_obj = next(s for s in stocks if s.symbol == symbol)
                for y, m in months:
                    done += 1
                    progress.progress(done / total, text=f"{symbol} {y}-{m:02d} ({done}/{total})")
                    try:
                        cycle = reconstruct_monthly_cycle(symbol, y, m)
                        bars = get_cycle_price_series(client, stock_obj, cycle.reference_expiry, cycle.pricing_expiry)
                        all_trades.extend(simulate_cycle(cycle, bars, selected_strategies))
                        all_level_events.extend(analyze_cycle(cycle, bars))
                    except (HistoricalDataError, PriceSeriesError) as e:
                        errors.append(str(e))
            progress.empty()

            st.session_state["bt_results"] = {
                "trades": all_trades,
                "level_events": all_level_events,
                "errors": errors,
            }

    if "bt_results" in st.session_state:
        result_data = st.session_state["bt_results"]
        all_trades = result_data["trades"]
        all_level_events = result_data["level_events"]
        errors = result_data["errors"]

        st.success(f"{len(all_trades)} trades simulated" + (f", {len(errors)} cycle(s) skipped" if errors else ""))
        if errors:
            with st.expander(f"{len(errors)} skipped cycles (DATA ERROR)"):
                for e in errors:
                    st.text(e)

        if all_trades:
            overall = compute_results(all_trades)
            st.markdown("### Overall results")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total trades", overall.total_trades)
            m1.metric("Win rate", f"{overall.win_rate_pct:.1f}%")
            m2.metric("Net P&L (sum of trade %)", f"{overall.net_profit_pct:+.2f}%")
            m2.metric("Expectancy / trade", f"{overall.expectancy_pct:+.2f}%")
            m3.metric("Profit factor", f"{overall.profit_factor:.2f}" if overall.profit_factor else "N/A")
            m3.metric("Max drawdown", f"{overall.max_drawdown_pct:.2f}%")
            m4.metric("Avg holding days", f"{overall.avg_holding_days:.1f}")
            m4.metric("Max consec. wins / losses", f"{overall.max_consecutive_wins} / {overall.max_consecutive_losses}")

            trades_df = pd.DataFrame([t.__dict__ for t in all_trades]).sort_values("entry_date")
            trades_df["cumulative_pnl_pct"] = trades_df["pnl_pct"].cumsum()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=list(range(len(trades_df))), y=trades_df["cumulative_pnl_pct"], mode="lines+markers", name="Cumulative P&L %"))
            fig.update_layout(height=350, title="Cumulative P&L (sum of trade %, chronological order)", xaxis_title="Trade #", yaxis_title="Cumulative %")
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("### By strategy")
            by_strategy = compute_results_by_strategy(all_trades)
            st.dataframe(
                pd.DataFrame([{**{"strategy": name}, **r.__dict__} for name, r in by_strategy.items()]),
                use_container_width=True,
            )

            st.markdown("### By level")
            by_level = compute_results_by_level(all_trades)
            st.dataframe(
                pd.DataFrame([{**{"level": lvl}, **r.__dict__} for lvl, r in by_level.items()]),
                use_container_width=True,
            )

            st.markdown("### Trade log")
            st.dataframe(trades_df, use_container_width=True, height=400)

        if all_level_events:
            st.markdown("### Level performance statistics (Section 38)")
            st.caption("Touch/bounce/rejection/breakout rates and average reaction, independent of any trading strategy.")
            level_stats = aggregate_level_stats(all_level_events)
            st.dataframe(
                pd.DataFrame([r.__dict__ for r in level_stats.values()]),
                use_container_width=True,
            )
