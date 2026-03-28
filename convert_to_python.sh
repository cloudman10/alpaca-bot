#!/bin/bash
set -e

echo "═══════════════════════════════════════════════════"
echo "  Converting alpaca-bot from TypeScript to Python   "
echo "═══════════════════════════════════════════════════"

cd ~/Desktop/alpaca-bot || { echo "ERROR: ~/Desktop/alpaca-bot not found."; exit 1; }

git checkout master
git pull origin master

echo ""
echo ">>> Deleting old TypeScript files..."
rm -rf src/ dist/ node_modules/ package.json package-lock.json tsconfig.json start-bot.bat

echo ">>> Creating .gitignore..."
cat > .gitignore << 'GITIGNORE'
.env
__pycache__/
*.pyc
logs/
*.egg-info/
dist/
node_modules/
GITIGNORE

echo ">>> Creating .env..."
cat > .env << 'DOTENV'
# Alpaca API credentials (paper trading)
ALPACA_API_KEY_ID=PKF72BM5QBJL2PKUKM5FPLK5ML
ALPACA_API_SECRET_KEY=HRWRLmaLqBXUahGZYwcYqijB7pPuKUbx3tjnw56bP61v
ALPACA_PAPER=true
DOTENV

echo ">>> Creating requirements.txt..."
cat > requirements.txt << 'REQS'
alpaca-py>=0.13.0
pandas>=2.0.0
numpy>=1.24.0
python-dotenv>=1.0.0
pytz>=2024.1
REQS

echo ">>> Creating indicators.py..."
cat > indicators.py << 'PYFILE'
"""
indicators.py — RSI(14), Bollinger Bands(20,2), MACD(12,26,9) + candlestick patterns.
Pure pandas/numpy implementation — no external indicator library needed.
"""

import numpy as np
import pandas as pd


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using exponential moving average of gains/losses."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _bbands(series: pd.Series, period: int = 20, std: float = 2.0) -> tuple:
    """Compute Bollinger Bands (upper, middle, lower)."""
    middle = series.rolling(window=period).mean()
    rolling_std = series.rolling(window=period).std()
    upper = middle + std * rolling_std
    lower = middle - std * rolling_std
    return upper, middle, lower


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    """Compute MACD line, signal line, and histogram."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute RSI(14), Bollinger Bands(20,2), and MACD(12,26,9) on a bars DataFrame."""
    df = df.copy()

    closes = df["close"]

    # RSI
    df["RSI_14"] = _rsi(closes, 14)

    # Bollinger Bands
    df["BBU_20_2.0"], df["BBM_20_2.0"], df["BBL_20_2.0"] = _bbands(closes, 20, 2.0)

    # MACD
    df["MACD_12_26_9"], df["MACDs_12_26_9"], df["MACDh_12_26_9"] = _macd(closes, 12, 26, 9)

    return df


def is_bullish_engulfing(prev: pd.Series, curr: pd.Series) -> bool:
    """Bullish engulfing: prev bearish, curr bullish, curr body wraps prev body."""
    prev_bearish = prev["close"] < prev["open"]
    curr_bullish = curr["close"] > curr["open"]
    wraps = curr["open"] <= prev["close"] and curr["close"] >= prev["open"]
    return prev_bearish and curr_bullish and wraps


def is_bearish_engulfing(prev: pd.Series, curr: pd.Series) -> bool:
    """Bearish engulfing: prev bullish, curr bearish, curr body wraps prev body."""
    prev_bullish = prev["close"] > prev["open"]
    curr_bearish = curr["close"] < curr["open"]
    wraps = curr["open"] >= prev["close"] and curr["close"] <= prev["open"]
    return prev_bullish and curr_bearish and wraps
PYFILE

echo ">>> Creating alpaca_service.py..."
cat > alpaca_service.py << 'PYFILE'
"""
alpaca_service.py — Alpaca client using alpaca-py for account, market data, and orders.
"""

import os
import logging
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

load_dotenv()

logger = logging.getLogger(__name__)

# ── Clients ──────────────────────────────────────────────────────────────────

_api_key = os.getenv("ALPACA_API_KEY_ID", "")
_secret_key = os.getenv("ALPACA_API_SECRET_KEY", "")
_paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"

trading_client = TradingClient(_api_key, _secret_key, paper=_paper)
data_client = StockHistoricalDataClient(_api_key, _secret_key)


# ── Account ──────────────────────────────────────────────────────────────────

def get_balance() -> dict:
    """Returns account equity, cash, and buying power."""
    account = trading_client.get_account()
    return {
        "equity": float(account.equity),
        "cash": float(account.cash),
        "buying_power": float(account.buying_power),
    }


# ── Market data ──────────────────────────────────────────────────────────────

def get_15m_bars(symbol: str, limit: int = 50) -> pd.DataFrame:
    """Fetch 15-minute bars for a symbol over the last 7 days using IEX feed."""
    start = datetime.utcnow() - timedelta(days=7)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(15, "Min"),
        start=start,
        limit=limit,
        feed="iex",
    )

    bars = data_client.get_stock_bars(request)
    bar_list = bars[symbol]

    records = []
    for bar in bar_list:
        records.append({
            "time": bar.timestamp.isoformat(),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": int(bar.volume),
        })

    return pd.DataFrame(records)


# ── Order placement ──────────────────────────────────────────────────────────

def place_bracket_order(
    symbol: str,
    qty: int,
    side: str,
    limit_price: float,
    stop_loss: float,
    take_profit: float,
) -> str:
    """Place a bracket order (entry limit + stop-loss + take-profit)."""
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

    order_request = LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=order_side,
        time_in_force=TimeInForce.GTC,
        limit_price=round(limit_price, 2),
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=round(take_profit, 2)),
        stop_loss=StopLossRequest(stop_price=round(stop_loss, 2)),
    )

    order = trading_client.submit_order(order_request)
    return str(order.id)


# ── Position management ──────────────────────────────────────────────────────

def get_open_positions() -> list:
    """Returns list of open positions as dicts with symbol, qty, side."""
    positions = trading_client.get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "qty": abs(float(p.qty)),
            "side": p.side.value,
        }
        for p in positions
    ]


def close_all_positions():
    """Close all open positions."""
    positions = trading_client.get_all_positions()
    if not positions:
        return
    logger.info(f"Closing {len(positions)} open position(s)...")
    for pos in positions:
        try:
            trading_client.close_position(pos.symbol)
            logger.info(f"Closed position: {pos.symbol}")
        except Exception as e:
            logger.error(f"Failed to close {pos.symbol}: {e}")


def cancel_all_orders():
    """Cancel all open orders."""
    trading_client.cancel_orders()
    logger.info("All open orders cancelled.")


def is_market_open() -> bool:
    """Check if the market is currently open."""
    clock = trading_client.get_clock()
    return clock.is_open
PYFILE

echo ">>> Creating risk_manager.py..."
cat > risk_manager.py << 'PYFILE'
"""
risk_manager.py — Position sizing (1% rule), take-profit calc, and daily kill switch.
"""

import logging

logger = logging.getLogger(__name__)

RISK_PER_TRADE_PCT = 0.01   # 1% of equity per trade
REWARD_RATIO = 2             # 1:2 risk-to-reward
DAILY_LOSS_LIMIT_PCT = 0.03  # 3% daily drawdown kill switch
MAX_SHARES = 2000            # hard cap on position size


def calc_position_size(equity: float, entry: float, stop_loss: float) -> dict:
    """
    Calculate shares so that distance between entry and stop_loss equals 1% of equity.
    Capped at MAX_SHARES.
    Returns: {"qty": int, "risk_amount": float}
    """
    risk_amount = equity * RISK_PER_TRADE_PCT
    stop_distance = abs(entry - stop_loss)

    if stop_distance == 0:
        raise ValueError("Stop distance is zero — cannot size position.")

    qty = int(risk_amount / stop_distance)
    qty = min(qty, MAX_SHARES)

    if qty < 1:
        raise ValueError(
            f"Position size rounds to 0 shares (equity={equity}, stop_dist={stop_distance})."
        )

    return {"qty": qty, "risk_amount": risk_amount}


def calc_take_profit(entry: float, stop_loss: float, direction: str) -> float:
    """Returns take-profit price at 1:2 risk-to-reward ratio."""
    risk = abs(entry - stop_loss)
    if direction == "LONG":
        return entry + risk * REWARD_RATIO
    else:
        return entry - risk * REWARD_RATIO


class DailyKillSwitch:
    """Trips when daily drawdown hits 3%. Once tripped, stays halted for the session."""

    def __init__(self, start_equity: float):
        self.start_equity = start_equity
        self.halted = False
        limit = start_equity * DAILY_LOSS_LIMIT_PCT
        logger.info(
            f"[KillSwitch] Initialized. Start equity: ${start_equity:.2f}. "
            f"Daily loss limit: {DAILY_LOSS_LIMIT_PCT * 100}% (${limit:.2f})"
        )

    def check(self, current_equity: float) -> bool:
        if self.halted:
            return True

        loss = self.start_equity - current_equity
        loss_pct = loss / self.start_equity

        if loss_pct >= DAILY_LOSS_LIMIT_PCT:
            self.halted = True
            logger.warning(
                f"[KillSwitch] TRIGGERED — daily loss {loss_pct * 100:.2f}% "
                f"(${loss:.2f}). Bot halted for today."
            )

        return self.halted

    def is_halted(self) -> bool:
        return self.halted
PYFILE

echo ">>> Creating strategy.py..."
cat > strategy.py << 'PYFILE'
"""
strategy.py — Ross Cameron 15-minute Momentum signal detection.

LONG setup (all four conditions):
  1. RSI < 30
  2. Previous candle touched lower Bollinger Band (low <= lower BB)
  3. Bullish engulfing pattern
  4. Current candle closes inside band with higher low

SHORT setup (mirror):
  1. RSI > 70
  2. Previous candle pierced upper Bollinger Band (high >= upper BB)
  3. Bearish engulfing pattern
  4. Current candle closes inside band with lower high

Stop-loss: outer BB of the trigger candle
Take-profit: 1:2 risk-to-reward
"""

import logging
import pandas as pd
from indicators import is_bullish_engulfing, is_bearish_engulfing
from risk_manager import calc_take_profit

logger = logging.getLogger(__name__)

RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


def detect_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """
    Detect buy/short signals on a DataFrame with indicator columns.
    Returns a signal dict or None.
    """
    if len(df) < 3:
        return None

    # Check that indicator columns exist
    if "RSI_14" not in df.columns or "BBL_20_2.0" not in df.columns:
        return None

    # Drop rows where indicators haven't warmed up
    df_clean = df.dropna(subset=["RSI_14", "BBL_20_2.0", "BBU_20_2.0"])
    if len(df_clean) < 2:
        return None

    # Most recent two candles
    bar_n = df_clean.iloc[-1]   # current candle
    bar_n1 = df_clean.iloc[-2]  # previous candle

    last_rsi = bar_n["RSI_14"]
    bb_lower_n = bar_n["BBL_20_2.0"]
    bb_upper_n = bar_n["BBU_20_2.0"]
    bb_lower_n1 = bar_n1["BBL_20_2.0"]
    bb_upper_n1 = bar_n1["BBU_20_2.0"]

    # ── LONG setup ───────────────────────────────────────────────────────
    long_cond1 = last_rsi < RSI_OVERSOLD
    long_cond2 = bar_n1["low"] <= bb_lower_n1                         # touched lower band
    long_cond3 = is_bullish_engulfing(bar_n1, bar_n)                  # engulfing
    long_cond4 = bar_n["close"] > bb_lower_n and bar_n["low"] > bar_n1["low"]  # inside + higher low

    if long_cond1 and long_cond2 and long_cond3 and long_cond4:
        entry = bar_n["close"]
        stop_loss = bb_lower_n1
        take_profit = calc_take_profit(entry, stop_loss, "LONG")

        return {
            "direction": "LONG",
            "symbol": symbol,
            "entry_price": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reason": (
                f"LONG | RSI={last_rsi:.1f} | "
                f"LowTouchedBB({bar_n1['low']:.2f} <= {bb_lower_n1:.2f}) | "
                f"BullishEngulfing | ClosedInsideBand"
            ),
        }

    # ── SHORT setup ──────────────────────────────────────────────────────
    short_cond1 = last_rsi > RSI_OVERBOUGHT
    short_cond2 = bar_n1["high"] >= bb_upper_n1                        # pierced upper band
    short_cond3 = is_bearish_engulfing(bar_n1, bar_n)                  # engulfing
    short_cond4 = bar_n["close"] < bb_upper_n and bar_n["high"] < bar_n1["high"]  # inside + lower high

    if short_cond1 and short_cond2 and short_cond3 and short_cond4:
        entry = bar_n["close"]
        stop_loss = bb_upper_n1
        take_profit = calc_take_profit(entry, stop_loss, "SHORT")

        return {
            "direction": "SHORT",
            "symbol": symbol,
            "entry_price": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reason": (
                f"SHORT | RSI={last_rsi:.1f} | "
                f"HighPiercedBB({bar_n1['high']:.2f} >= {bb_upper_n1:.2f}) | "
                f"BearishEngulfing | ClosedInsideBand"
            ),
        }

    return None
PYFILE

echo ">>> Creating main.py..."
cat > main.py << 'PYFILE'
"""
main.py — Entry point for the Ross Cameron 15m Momentum trading bot.
Heartbeat loop scans the watchlist every 60 seconds.
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
HEARTBEAT_SEC = 60
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
PYFILE

echo ""
echo ">>> All files created. Final structure:"
ls -la *.py requirements.txt .gitignore .env

echo ""
echo ">>> Staging, committing, and pushing..."
git add -A
git commit -m "convert: rewrite bot2 from TypeScript to Python - Ross Cameron 15m Momentum strategy"
git push origin master

echo ""
echo "═══════════════════════════════════════════════════"
echo "  DONE! Bot converted and pushed to GitHub.        "
echo "═══════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  cd ~/Desktop/alpaca-bot"
echo "  pip3 install -r requirements.txt"
echo "  python3 main.py"
