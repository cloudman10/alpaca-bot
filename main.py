"""
main.py — Entry point for the Ross Cameron 15m Momentum trading bot.

Daily schedule (Eastern time):
  9:00 AM  — pre-market gap scanner runs automatically
  9:20 AM  — dynamic watchlist finalized from gap + RVOL filters
  9:30 AM  — RSI/BB/Engulfing entry logic activates on dynamic watchlist
  4:00 PM  — market close; scanner resets for next day

Heartbeat loop: scans the watchlist every 15 seconds during market hours.
"""

import os
import sys
import signal
import time
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import date as Date, datetime, timezone
from zoneinfo import ZoneInfo

from alpaca_service import (
    get_balance,
    get_15m_bars,
    place_bracket_order,
    close_all_positions,
    cancel_all_orders,
    is_market_open,
    get_open_positions,
)
from indicators import compute_indicators
from strategy import detect_signal
from risk_manager import calc_position_size, DailyKillSwitch
from scanner import run_gap_scanner, DEFAULT_WATCHLIST

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

# ── Config ────────────────────────────────────────────────────────────────────

HEARTBEAT_SEC = 15
BAR_LIMIT     = 50
ET            = ZoneInfo("America/New_York")

# ── State ─────────────────────────────────────────────────────────────────────

kill_switch:    DailyKillSwitch | None = None
is_running:     bool                   = False
active_symbols: set[str]               = set()

# Scanner state — resets each trading day
_scanner_ran_date: Date | None = None        # date scanner last ran
_dynamic_watchlist: list[str]  = list(DEFAULT_WATCHLIST)  # today's watchlist


# ── Time helpers ──────────────────────────────────────────────────────────────

def _et_now() -> datetime:
    return datetime.now(ET)


def _in_scanner_window() -> bool:
    """
    Returns True between 9:00 AM and 9:29 AM ET.
    This is when the gap scanner should run to build the day's watchlist.
    """
    now = _et_now()
    h, m = now.hour, now.minute
    return h == 9 and m < 30


def _in_trading_window() -> bool:
    """
    Returns True between 9:30 AM and 3:55 PM ET (regular market hours).
    Stops 5 min early to avoid placing orders right at close.
    """
    now = _et_now()
    h, m = now.hour, now.minute
    after_open  = (h == 9 and m >= 30) or (h > 9)
    before_close = h < 15 or (h == 15 and m < 55)
    return after_open and before_close


def _is_weekday() -> bool:
    return _et_now().weekday() < 5  # Mon–Fri


# ── Scanner ───────────────────────────────────────────────────────────────────

def _run_scanner_if_needed():
    """
    Runs the gap scanner once per day during the 9:00–9:29 AM ET window.
    Updates _dynamic_watchlist in place.
    """
    global _scanner_ran_date, _dynamic_watchlist

    if not _is_weekday():
        return

    today = _et_now().date()
    if _scanner_ran_date == today:
        return  # already ran today

    if not _in_scanner_window():
        return

    logger.info("──────────────────────────────────────────────────────")
    logger.info("PRE-MARKET SCANNER: building today's dynamic watchlist")
    logger.info("──────────────────────────────────────────────────────")

    try:
        _dynamic_watchlist = run_gap_scanner()
    except Exception as e:
        logger.error("Scanner failed (%s) — keeping default watchlist: %s", e, DEFAULT_WATCHLIST)
        _dynamic_watchlist = list(DEFAULT_WATCHLIST)

    _scanner_ran_date = today
    logger.info("Today's watchlist: %s", _dynamic_watchlist)
    logger.info("──────────────────────────────────────────────────────")


# ── Main scan loop ────────────────────────────────────────────────────────────

def scan():
    """One full heartbeat tick — runs scanner if needed, then scans watchlist."""
    global is_running, kill_switch

    # Always try to run the scanner (it self-gates by time + date)
    _run_scanner_if_needed()

    if is_running:
        logger.info("Previous scan still running — skipping this tick.")
        return

    # Only trade during regular market hours
    if not _in_trading_window():
        return

    is_running = True
    try:
        # 1. Check market hours (Alpaca clock confirmation)
        if not is_market_open():
            logger.info("Market is closed — skipping scan.")
            return

        # 2. Fetch current equity and check kill switch
        account = get_balance()
        logger.info(
            "Equity: $%.2f | Cash: $%.2f | Buying Power: $%.2f",
            account["equity"], account["cash"], account["buying_power"],
        )

        if kill_switch and kill_switch.check(account["equity"]):
            logger.warning("Kill switch is ACTIVE — no new trades will be placed.")
            return

        # 3. Sync active_symbols with real open positions
        open_positions   = get_open_positions()
        position_symbols = {p["symbol"] for p in open_positions}

        for sym in list(active_symbols):
            if sym not in position_symbols:
                active_symbols.discard(sym)
                logger.info("[%s] Position closed — slot freed.", sym)

        # 4. Scan dynamic watchlist
        for symbol in _dynamic_watchlist:
            if symbol in active_symbols:
                logger.info("[%s] Already in position — skipping.", symbol)
                continue

            try:
                df = get_15m_bars(symbol, BAR_LIMIT)

                if len(df) < 30:
                    logger.info("[%s] Not enough bars (%d) — skipping.", symbol, len(df))
                    continue

                df     = compute_indicators(df)
                signal = detect_signal(symbol, df)

                if not signal:
                    logger.info("[%s] No signal.", symbol)
                    continue

                logger.info("[%s] SIGNAL DETECTED: %s", symbol, signal["reason"])
                logger.info(
                    "  Entry: $%.2f | Stop: $%.2f | Target: $%.2f",
                    signal["entry_price"], signal["stop_loss"], signal["take_profit"],
                )

                # 5. Size the position
                try:
                    pos_size = calc_position_size(
                        account["equity"], signal["entry_price"], signal["stop_loss"]
                    )
                except ValueError as e:
                    logger.error("[%s] Position sizing failed: %s", symbol, e)
                    continue

                logger.info(
                    "  Qty: %s shares | Risk: $%.2f",
                    pos_size["qty"], pos_size["risk_amount"],
                )

                # 6. Check buying power
                order_cost = pos_size["qty"] * signal["entry_price"]
                if order_cost > account["buying_power"]:
                    logger.warning(
                        "[%s] Insufficient buying power (need $%.2f, have $%.2f) — skipping.",
                        symbol, order_cost, account["buying_power"],
                    )
                    continue

                # 7. Place bracket order
                side     = "buy" if signal["direction"] == "LONG" else "sell"
                order_id = place_bracket_order(
                    symbol,
                    pos_size["qty"],
                    side,
                    signal["entry_price"],
                    signal["stop_loss"],
                    signal["take_profit"],
                )

                active_symbols.add(symbol)
                logger.info("[%s] Bracket order placed. ID: %s", symbol, order_id)

            except Exception as e:
                logger.error("[%s] Error during scan: %s", symbol, e)

    except Exception as e:
        logger.error("Unexpected error during scan: %s", e)
    finally:
        is_running = False


# ── Shutdown ──────────────────────────────────────────────────────────────────

def shutdown(sig, frame):
    """Graceful shutdown — cancel orders and close positions."""
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

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("═══════════════════════════════════════════════════════")
    print("   Alpaca Trading Bot — Ross Cameron 15m Momentum       ")
    print("   + Pre-market Gap Scanner                             ")
    print("═══════════════════════════════════════════════════════")
    print(f"Started at:        {datetime.now(timezone.utc).isoformat()}")
    print(f"Default watchlist: {', '.join(DEFAULT_WATCHLIST)}")
    print(f"Heartbeat:         {HEARTBEAT_SEC}s")
    print("Scanner window:    9:00–9:29 AM ET (gap > 4%, RVOL > 2×)")
    print("Trading window:    9:30 AM–3:55 PM ET")
    print("───────────────────────────────────────────────────────")

    account = get_balance()
    print(f"Starting equity:  ${account['equity']:.2f}")
    print(f"Cash:             ${account['cash']:.2f}")
    print(f"Buying Power:     ${account['buying_power']:.2f}")
    print("───────────────────────────────────────────────────────\n")

    kill_switch = DailyKillSwitch(account["equity"])

    scan()
    while True:
        time.sleep(HEARTBEAT_SEC)
        scan()


if __name__ == "__main__":
    main()
