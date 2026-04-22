"""
main.py — Gap-UP Momentum Scanner (Bot 2).

Daily schedule (Eastern time):
  9:00 AM  — pre-market gap scanner runs (gap > 2%, RVOL > 1.0×)
  9:20 AM  — dynamic watchlist finalized (top 5 gap-up candidates)
  9:30 AM  — entry window opens: VWAP pullback + reclaim signals active
  10:30 AM — entry window closes (IEX 15-min delay; bars available from 10:15 AM)
  4:00 PM  — market close; VWAP stop monitoring ends

Entry logic (all must be met):
  1. Within first 30 min of session (9:30–10:00 AM ET)
  2. Previous 15m bar low touched/was at VWAP (pullback occurred)
  3. Current 15m bar closes above VWAP (bullish reclaim)
  4. Current bar is bullish (close > open)
  5. RSI(14) 45–65
  6. Volume > 1.5× 20-bar average on entry bar
  7. SPY not making new lows

Exit logic:
  - Take profit: previous day high (if above entry) OR 4% above entry
  - Stop loss: VWAP at entry (bracket order static stop)
  - VWAP monitoring: if price closes below VWAP mid-session, exit immediately
  - Kill switch: 2% daily loss limit
"""

import json
import os
import sys
import signal
import threading
import time
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path
import pytz

from alpaca_service import (
    get_balance,
    get_1m_bars,
    get_15m_bars,
    get_prev_day_high,
    place_bracket_order,
    close_all_positions,
    cancel_all_orders,
    is_market_open,
    get_open_positions,
)
from indicators import compute_indicators
from strategy import detect_signal, detect_tier2_signal
from risk_manager import calc_position_size, DailyKillSwitch
from scanner import run_gap_scanner, DEFAULT_WATCHLIST, get_scan_tier

# ── Logging ───────────────────────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)

_log_fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
_log_fmt.converter = time.gmtime

_file_handler = TimedRotatingFileHandler(
    "logs/bot.log", when="midnight", backupCount=7, utc=True
)
_file_handler.setFormatter(_log_fmt)

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_log_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_stream_handler, _file_handler])
logger = logging.getLogger(__name__)

# ── Marshal heartbeat ─────────────────────────────────────────────────────────

_HEARTBEAT_PATH = Path.home() / "TradingApp/logs/heartbeat.json"
_HEARTBEAT_KEY  = "bot2"


def _write_heartbeat() -> None:
    """Atomically update bot2's entry in the shared heartbeat file."""
    try:
        data: dict = {}
        if _HEARTBEAT_PATH.exists():
            try:
                data = json.loads(_HEARTBEAT_PATH.read_text())
            except Exception:
                data = {}
        data[_HEARTBEAT_KEY] = {"ts": time.time(), "pid": os.getpid()}
        tmp = _HEARTBEAT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(_HEARTBEAT_PATH)
    except Exception:
        pass   # non-fatal


def _heartbeat_loop() -> None:
    """Background daemon thread — writes heartbeat every 60 s."""
    while True:
        _write_heartbeat()
        time.sleep(60)


# ── Config ────────────────────────────────────────────────────────────────────

HEARTBEAT_SEC         = 15
BAR_LIMIT             = 50
POSITION_SIZE_PCT     = 0.08   # Tier 1: 8% of equity per position
POSITION_SIZE_PCT_T2  = 0.04   # Tier 2: 4% of equity (half position)
MAX_POSITIONS         = 3
ET               = pytz.timezone("America/New_York")

# ── State ─────────────────────────────────────────────────────────────────────

kill_switch:    DailyKillSwitch | None = None
is_running:     bool                   = False
active_symbols: set[str]               = set()
_symbol_tier:   dict[str, int]         = {}   # tier (1 or 2) per active symbol

_scanner_ran_date:  Date | None = None
_dynamic_watchlist: list[str]   = list(DEFAULT_WATCHLIST)


# ── Time helpers ──────────────────────────────────────────────────────────────

def _et_now() -> datetime:
    return datetime.now(ET)


def _is_weekday() -> bool:
    return _et_now().weekday() < 5


def _in_scanner_window() -> bool:
    """9:00–9:29 AM ET — gap scanner window."""
    now = _et_now()
    return now.hour == 9 and now.minute < 30


def _in_entry_window() -> bool:
    """9:30–10:30 AM ET — VWAP pullback entry window (first 60 min of session).

    Extended from 10:00 to 10:30 AM: IEX feed has a 15-minute data delay, so
    15-minute bars only become available ~15 min after they close. The 9:30 bar
    isn't visible until ~10:00 AM and the 9:45 bar not until ~10:15 AM. Keeping
    the window at 10:00 AM meant the strategy never had 2 intraday bars in time
    to fire a signal. Extending to 10:30 gives a real 15-min scanning window
    (10:15–10:30 AM) once IEX catches up.
    """
    now = _et_now()
    h, m = now.hour, now.minute
    return (h == 9 and m >= 30) or (h == 10 and m <= 30)


def _in_trading_window() -> bool:
    """9:30 AM–3:55 PM ET — position monitoring window."""
    now = _et_now()
    h, m = now.hour, now.minute
    after_open   = (h == 9 and m >= 30) or h > 9
    before_close = h < 15 or (h == 15 and m < 55)
    return after_open and before_close


def _is_active_period() -> bool:
    """True between 8:55 AM and 4:05 PM ET on weekdays."""
    if not _is_weekday():
        return False
    now = _et_now()
    h, m = now.hour, now.minute
    after_premarket  = h > 8 or (h == 8 and m >= 55)
    before_eod_close = h < 16 or (h == 16 and m <= 5)
    return after_premarket and before_eod_close


def _seconds_until_premarket() -> float:
    """Seconds until 8:55 AM ET on the next trading weekday (DST-safe via pytz.localize)."""
    now = _et_now()

    def _target(d) -> datetime:
        return ET.localize(datetime(d.year, d.month, d.day, 8, 55, 0))

    target = _target(now.date())
    if now >= target:
        target = _target(now.date() + timedelta(days=1))
    while target.weekday() >= 5:
        target = _target(target.date() + timedelta(days=1))
    return max(0.0, (target - now).total_seconds())


# ── SPY stability filter ──────────────────────────────────────────────────────
# Require 3 consecutive new-low detections before blocking entry.
# A single SPY dip at the open (common on gap-up days) no longer blocks;
# only a sustained 3-tick downtrend does.
_spy_new_low_streak: int = 0
SPY_NEW_LOW_THRESHOLD = 3   # consecutive new-low ticks required to block

def _spy_is_stable() -> bool:
    """Returns True unless SPY has made new lows on 3 consecutive scan ticks."""
    global _spy_new_low_streak
    try:
        df = get_1m_bars("SPY", 3)
        if len(df) < 3:
            _spy_new_low_streak = 0
            return True
        low_now = df["low"].iloc[-1]
        low_1   = df["low"].iloc[-2]
        low_2   = df["low"].iloc[-3]
        is_new_low = low_now < low_1 or low_now < low_2
        if is_new_low:
            _spy_new_low_streak += 1
            logger.info(
                "SPY new low detected (streak %d/%d) — %s",
                _spy_new_low_streak, SPY_NEW_LOW_THRESHOLD,
                "blocking entries" if _spy_new_low_streak >= SPY_NEW_LOW_THRESHOLD
                else "waiting for confirmation",
            )
        else:
            if _spy_new_low_streak > 0:
                logger.info("SPY stabilized — resetting new-low streak")
            _spy_new_low_streak = 0
        return _spy_new_low_streak < SPY_NEW_LOW_THRESHOLD
    except Exception as e:
        logger.warning("SPY check error (%s) — allowing entry", e)
        return True


# ── Scanner ───────────────────────────────────────────────────────────────────

def _run_scanner_if_needed():
    """Run gap scanner once per day during 9:00–9:29 AM ET window."""
    global _scanner_ran_date, _dynamic_watchlist

    if not _is_weekday():
        return
    today = _et_now().date()
    if _scanner_ran_date == today or not _in_scanner_window():
        return

    logger.info("──────────────────────────────────────────────────────")
    logger.info("PRE-MARKET SCANNER: Tier1 >4%%, Tier2 >2%%, RVOL > 1.0×")
    logger.info("──────────────────────────────────────────────────────")

    try:
        _dynamic_watchlist = run_gap_scanner()
    except Exception as e:
        logger.error("Scanner failed (%s) — keeping default watchlist", e)
        _dynamic_watchlist = list(DEFAULT_WATCHLIST)

    _scanner_ran_date = today
    tier = get_scan_tier()
    tier_label = {1: "Tier 1 (>4%% full pos)", 2: "Tier 2 (>2%% half pos)", 0: "default (no gap)"}
    logger.info("Today's watchlist: %s  [%s]", _dynamic_watchlist, tier_label.get(tier, "unknown"))
    logger.info("──────────────────────────────────────────────────────")


# ── Position exit monitoring (VWAP stop) ─────────────────────────────────────

def _monitor_positions_for_vwap_stop():
    """
    Check all open positions: if price closes below current VWAP → exit immediately.
    Called every heartbeat during trading window.
    """
    positions = get_open_positions()
    if not positions:
        return

    today = _et_now().date()

    for pos in positions:
        symbol = pos["symbol"]
        try:
            df = get_15m_bars(symbol, BAR_LIMIT)
            if df.empty:
                continue
            df = compute_indicators(df)

            # Filter to today's bars for accurate VWAP
            import pandas as pd
            _t = pd.to_datetime(df["time"])
            times = (_t.dt.tz_localize("UTC") if _t.dt.tz is None else _t.dt.tz_convert("UTC")).dt.tz_convert(ET).dt.date
            today_df = df[times == today]
            if today_df.empty:
                continue

            current_vwap  = float(today_df["VWAP"].iloc[-1])
            current_price = float(today_df["close"].iloc[-1])

            logger.info(
                "[%s] VWAP check: price=%.2f VWAP=%.2f",
                symbol, current_price, current_vwap,
            )

            if current_price < current_vwap:
                logger.info(
                    "[%s] Price %.2f < VWAP %.2f — VWAP stop triggered, closing all",
                    symbol, current_price, current_vwap,
                )
                cancel_all_orders()
                close_all_positions()
                active_symbols.clear()
                return   # exit after closing — re-check next tick

        except Exception as e:
            logger.error("[%s] VWAP stop check error: %s", symbol, e)


# ── Main scan loop ────────────────────────────────────────────────────────────

def scan():
    """One heartbeat tick."""
    global is_running

    _run_scanner_if_needed()

    if is_running:
        return

    if not _in_trading_window():
        return

    is_running = True
    try:
        if not is_market_open():
            logger.info("Market is closed — skipping scan.")
            return

        account = get_balance()
        logger.info(
            "Equity: $%.2f | Cash: $%.2f | Buying Power: $%.2f",
            account["equity"], account["cash"], account["buying_power"],
        )

        if kill_switch and kill_switch.check(account["equity"]):
            logger.warning("Kill switch ACTIVE — no new trades.")
            return

        # ── Monitor existing positions for VWAP-based exit ────────────────
        _monitor_positions_for_vwap_stop()

        # ── Entry logic: only within first 30 min of session ─────────────
        if not _in_entry_window():
            logger.info("Outside entry window (9:30–10:00 AM ET) — monitoring only.")
            return

        logger.info(
            "ENTRY WINDOW OPEN (9:30–10:00 AM ET) — scanning %d symbols: %s",
            len(_dynamic_watchlist), _dynamic_watchlist,
        )

        if len(active_symbols) >= MAX_POSITIONS:
            logger.info("Max positions (%d) reached — no new entries.", MAX_POSITIONS)
            return

        open_positions   = get_open_positions()
        position_symbols = {p["symbol"] for p in open_positions}

        # Sync active_symbols with real positions
        for sym in list(active_symbols):
            if sym not in position_symbols:
                active_symbols.discard(sym)
                _symbol_tier.pop(sym, None)
                logger.info("[%s] Position closed — slot freed.", sym)

        spy_stable   = _spy_is_stable()
        current_tier = get_scan_tier()

        for symbol in _dynamic_watchlist:
            if symbol in active_symbols:
                continue
            if len(active_symbols) >= MAX_POSITIONS:
                break

            try:
                df = get_15m_bars(symbol, BAR_LIMIT)
                if len(df) < 30:
                    logger.info("[%s] Not enough bars (%d) — skipping.", symbol, len(df))
                    continue

                df = compute_indicators(df)

                # ── Choose entry strategy based on tier ───────────────────
                if current_tier == 2:
                    # Tier 2: 15-min opening high breakout, no VWAP required
                    signal = detect_tier2_signal(symbol, df, spy_stable=spy_stable)
                else:
                    # Tier 1 or default: VWAP pullback entry
                    signal = detect_signal(symbol, df, spy_stable=spy_stable)

                if not signal:
                    logger.info("[%s] No signal.", symbol)
                    continue

                logger.info("[%s] SIGNAL: %s", symbol, signal["reason"])

                # ── Position sizing: 8% (Tier 1) or 4% (Tier 2) ──────────
                entry     = signal["entry_price"]
                equity    = account["equity"]
                size_pct  = POSITION_SIZE_PCT_T2 if current_tier == 2 else POSITION_SIZE_PCT
                alloc     = equity * size_pct
                qty       = int(alloc / entry)

                logger.info(
                    "[%s] Tier %d position size: %.0f%% of equity ($%.2f → %d shares)",
                    symbol, current_tier if current_tier in (1, 2) else 1,
                    size_pct * 100, alloc, qty,
                )

                if qty < 1:
                    logger.warning("[%s] Position size rounds to 0 — skip.", symbol)
                    continue

                order_cost = qty * entry
                if order_cost > account["buying_power"]:
                    logger.warning(
                        "[%s] Insufficient buying power (need $%.2f, have $%.2f) — skip.",
                        symbol, order_cost, account["buying_power"],
                    )
                    continue

                # ── Take profit: prev_day_high (if above entry) OR 4% ─────
                prev_high   = get_prev_day_high(symbol)
                take_profit = entry * 1.04   # default: 4% above entry
                if prev_high and prev_high > entry * 1.01:
                    take_profit = min(prev_high, entry * 1.04)
                    logger.info(
                        "[%s] TP set to %.2f (prev_day_high=%.2f, 4%%=%.2f)",
                        symbol, take_profit, prev_high, entry * 1.04,
                    )

                stop_loss = signal["stop_loss"]   # VWAP at entry time

                logger.info(
                    "[%s] Entry=%.2f SL=%.2f (VWAP) TP=%.2f qty=%d cost=$%.2f",
                    symbol, entry, stop_loss, take_profit, qty, order_cost,
                )

                # place_bracket_order runs the Slippage Guard internally.
                # Returns None if vetoed (RT price > signal + 0.75%).
                order_id = place_bracket_order(
                    symbol, qty, "buy", entry, stop_loss, take_profit
                )

                if order_id is None:
                    continue   # vetoed — log already written inside alpaca_service

                active_symbols.add(symbol)
                _symbol_tier[symbol] = current_tier
                logger.info("[%s] Order placed. ID: %s", symbol, order_id)

            except Exception as e:
                logger.error("[%s] Error during scan: %s", symbol, e)

    except Exception as e:
        logger.error("Unexpected error during scan: %s", e)
    finally:
        is_running = False


# ── Shutdown ──────────────────────────────────────────────────────────────────

def shutdown(sig, frame):
    sig_name = signal.Signals(sig).name
    logger.info("Received %s — shutting down gracefully...", sig_name)
    try:
        cancel_all_orders()
        close_all_positions()
    except Exception as e:
        logger.error("Error during shutdown: %s", e)
    sys.exit(0)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global kill_switch

    # Write PID so healthcheck can detect this process regardless of how it was launched.
    Path("logs/bot2.pid").write_text(str(os.getpid()))

    # Start Marshal heartbeat — writes every 60 s so the watchdog knows we're alive.
    _write_heartbeat()
    threading.Thread(target=_heartbeat_loop, daemon=True, name="heartbeat").start()

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("═══════════════════════════════════════════════════════")
    print("   Gap-UP Momentum Scanner — Bot 2                     ")
    print("   Tiered Gap System | Tier1 VWAP + Tier2 ORB          ")
    print("═══════════════════════════════════════════════════════")
    print(f"Started at:       {datetime.now(timezone.utc).isoformat()}")
    print(f"Default watchlist: {', '.join(DEFAULT_WATCHLIST)}")
    print(f"Heartbeat:         {HEARTBEAT_SEC}s")
    print("Scanner window:    9:00–9:29 AM ET (Tier1 >4%, Tier2 >2%, RVOL > 1.0×)")
    print("Entry window:      9:30–10:30 AM ET (IEX delay; bars arrive ~10:15 AM)")
    print("  Tier 1 (>4%):   VWAP pullback entry | 8% of equity")
    print("  Tier 2 (>2%):   15-min high breakout | 4% of equity (half pos)")
    print("Stop loss:         VWAP at entry (T1) / opening low (T2) | TP: prev_day_high or +4%")
    print("Kill switch:       2% daily loss limit")
    print("Thresholds optimized: 10D High added, 2% Gap fallback active")
    print("───────────────────────────────────────────────────────")

    account = get_balance()
    print(f"Starting equity:  ${account['equity']:.2f}")
    print(f"Cash:             ${account['cash']:.2f}")
    print(f"Buying Power:     ${account['buying_power']:.2f}")
    print("───────────────────────────────────────────────────────\n")

    kill_switch = DailyKillSwitch(account["equity"])

    scan()
    while True:
        if not _is_active_period():
            secs = _seconds_until_premarket()
            logger.info(
                "Outside market hours — sleeping %.1f hours until pre-market (8:55 AM ET).",
                secs / 3600,
            )
            # Sleep in 60-second chunks checking _is_active_period() each time.
            # Do NOT use a slept-counter: time.sleep() pauses during macOS system
            # suspend, so the counter under-counts elapsed wall-clock time and the
            # bot can sleep past the next trading session silently.
            while not _is_active_period():
                time.sleep(60)
            continue
        time.sleep(HEARTBEAT_SEC)
        scan()


if __name__ == "__main__":
    main()
