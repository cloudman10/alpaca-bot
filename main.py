"""
main.py — Entry point for the Ross Cameron 15m Momentum trading bot.
Heartbeat loop scans the watchlist every 15 seconds.
"""

import sys
import signal
import time
import logging
from datetime import datetime, timezone

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

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.Formatter.converter = time.gmtime
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────

WATCHLIST = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "META"]
HEARTBEAT_SEC = 15
BAR_LIMIT = 50

# ── State ────────────────────────────────────────────────────────────────────

kill_switch: DailyKillSwitch | None = None
is_running = False
active_symbols: set[str] = set()


def scan():
    """One full scan of the watchlist."""
    global is_running, kill_switch

    if is_running:
        logger.info("Previous scan still running — skipping this tick.")
        return

    is_running = True

    try:
        # 1. Check market hours
        if not is_market_open():
            logger.info("Market is closed — skipping scan.")
            return

        # 2. Fetch current equity and check kill switch
        account = get_balance()
        logger.info(
            f"Equity: ${account['equity']:.2f} | "
            f"Cash: ${account['cash']:.2f} | "
            f"Buying Power: ${account['buying_power']:.2f}"
        )

        if kill_switch and kill_switch.check(account["equity"]):
            logger.warning("Kill switch is ACTIVE — no new trades will be placed.")
            return

        # 3. Sync active symbols with real open positions
        open_positions = get_open_positions()
        position_symbols = {p["symbol"] for p in open_positions}

        for sym in list(active_symbols):
            if sym not in position_symbols:
                active_symbols.discard(sym)
                logger.info(f"Position for {sym} is closed — slot freed.")

        # 4. Scan watchlist
        for symbol in WATCHLIST:
            if symbol in active_symbols:
                logger.info(f"[{symbol}] Already in position — skipping.")
                continue

            try:
                df = get_15m_bars(symbol, BAR_LIMIT)

                if len(df) < 30:
                    logger.info(f"[{symbol}] Not enough bars ({len(df)}) — skipping.")
                    continue

                df = compute_indicators(df)
                signal = detect_signal(symbol, df)

                if not signal:
                    logger.info(f"[{symbol}] No signal.")
                    continue

                logger.info(f"[{symbol}] SIGNAL DETECTED: {signal['reason']}")
                logger.info(
                    f"  Entry: ${signal['entry_price']:.2f} | "
                    f"Stop: ${signal['stop_loss']:.2f} | "
                    f"Target: ${signal['take_profit']:.2f}"
                )

                # 5. Size the position
                try:
                    pos_size = calc_position_size(
                        account["equity"], signal["entry_price"], signal["stop_loss"]
                    )
                except ValueError as e:
                    logger.error(f"[{symbol}] Position sizing failed: {e}")
                    continue

                logger.info(
                    f"  Qty: {pos_size['qty']} shares | "
                    f"Risk: ${pos_size['risk_amount']:.2f}"
                )

                # 6. Check buying power
                order_cost = pos_size["qty"] * signal["entry_price"]
                if order_cost > account["buying_power"]:
                    logger.warning(
                        f"[{symbol}] Insufficient buying power "
                        f"(need ${order_cost:.2f}, have ${account['buying_power']:.2f}) — skipping."
                    )
                    continue

                # 7. Place bracket order
                side = "buy" if signal["direction"] == "LONG" else "sell"
                order_id = place_bracket_order(
                    symbol,
                    pos_size["qty"],
                    side,
                    signal["entry_price"],
                    signal["stop_loss"],
                    signal["take_profit"],
                )

                active_symbols.add(symbol)
                logger.info(f"[{symbol}] Bracket order placed. Order ID: {order_id}")

            except Exception as e:
                logger.error(f"[{symbol}] Error during scan: {e}")

    except Exception as e:
        logger.error(f"Unexpected error during scan: {e}")
    finally:
        is_running = False


def shutdown(sig, frame):
    """Graceful shutdown — cancel orders and close positions."""
    sig_name = signal.Signals(sig).name
    logger.info(f"Received {sig_name} — shutting down gracefully...")
    try:
        cancel_all_orders()
        close_all_positions()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    sys.exit(0)


def main():
    global kill_switch

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("═══════════════════════════════════════════════════")
    print("   Alpaca Trading Bot — Ross Cameron 15m Momentum  ")
    print("═══════════════════════════════════════════════════")
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    print(f"Watchlist:  {', '.join(WATCHLIST)}")
    print(f"Heartbeat:  {HEARTBEAT_SEC}s")
    print("───────────────────────────────────────────────────")

    # Fetch starting balance and initialize kill switch
    account = get_balance()
    print(f"Starting equity: ${account['equity']:.2f}")
    print(f"Cash:            ${account['cash']:.2f}")
    print(f"Buying Power:    ${account['buying_power']:.2f}")
    print("───────────────────────────────────────────────────\n")

    kill_switch = DailyKillSwitch(account["equity"])

    # Run immediately, then loop
    scan()
    while True:
        time.sleep(HEARTBEAT_SEC)
        scan()


if __name__ == "__main__":
    main()
