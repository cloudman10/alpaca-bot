"""
backtest.py — VectorBT backtest for the Ross Cameron Momentum Strategy (Bot 2).

Strategy signals on 15-minute bars:
  LONG : RSI(14) < 30  +  prev candle low <= lower BB  +  Bullish Engulfing
  SHORT: RSI(14) > 70  +  prev candle high >= upper BB  +  Bearish Engulfing

Stop-loss : outer Bollinger Band of the trigger candle (converted to %)
Take-profit: 1:2 risk-to-reward
Position sizing: 1% of initial capital risked per trade (risk / sl_pct)

Usage:
    python3 backtest.py
"""

import os
import sys
import warnings

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import vectorbt as vbt
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
WATCHLIST     = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "META"]
INIT_CASH     = 100_000.0
RISK_PCT      = 0.01          # 1% of capital risked per trade
REWARD_RATIO  = 2.0           # 1:2 risk-to-reward
FEE_PCT       = 0.001         # 0.1% commission per side
MIN_SL_PCT    = 0.005         # 0.5% minimum stop distance (floor)
MAX_POS_VALUE = INIT_CASH * 0.30  # hard cap: max 30% of initial capital per trade
OUTPUT_FILE   = "backtest_results.png"


# ── Data fetching ─────────────────────────────────────────────────────────────
def fetch_15min_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Return dict of wide DataFrames (datetime × symbol) for open/high/low/close/volume."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    api_key    = os.getenv("ALPACA_API_KEY_ID", "")
    secret_key = os.getenv("ALPACA_API_SECRET_KEY", "")
    if not api_key or not secret_key:
        print("ERROR: ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set in .env")
        sys.exit(1)

    client = StockHistoricalDataClient(api_key, secret_key)
    end    = datetime.now(timezone.utc)
    start  = end - timedelta(days=365)

    print(f"Fetching {len(symbols)} symbols: {start.date()} → {end.date()} "
          f"(15-min bars, IEX feed) ...")
    print("This may take a moment — ~6,500 bars per symbol ...")
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame(amount=15, unit=TimeFrameUnit.Minute),
        start=start,
        end=end,
        feed="iex",
    )
    raw = client.get_stock_bars(req).df   # MultiIndex: (symbol, timestamp)

    ohlcv: dict[str, pd.DataFrame] = {}
    for field in ("open", "high", "low", "close", "volume"):
        pivot = raw[field].unstack(level=0)           # timestamp × symbol
        pivot.index = pd.DatetimeIndex(pivot.index)   # keep full datetime (no normalize)
        pivot = pivot[symbols]                         # ensure column order
        ohlcv[field] = pivot.dropna(how="all")

    rows = len(ohlcv["close"])
    print(f"Loaded {rows} 15-min bars per symbol.")
    return ohlcv


# ── Indicator helpers (vectorized, operate on DataFrame columns) ──────────────
def _rsi(close: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs       = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _bbands(close: pd.DataFrame, period: int = 20, std: float = 2.0):
    """Returns (upper, middle, lower)."""
    mid   = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    return mid + std * sigma, mid, mid - std * sigma


# ── Signal generation ─────────────────────────────────────────────────────────
def build_signals(ohlcv: dict) -> tuple:
    """
    Returns:
        long_entries, short_entries : bool DataFrames
        sl_stop, tp_stop            : float DataFrames (% stop at entry bar)
        size                        : float DataFrame  (dollar value at entry bar)
    """
    open_  = ohlcv["open"]
    high   = ohlcv["high"]
    low    = ohlcv["low"]
    close  = ohlcv["close"]

    rsi                    = _rsi(close)
    bb_upper, _, bb_lower  = _bbands(close)

    # ── Candlestick patterns ─────────────────────────────────────────────────
    prev_bear      = close.shift(1) < open_.shift(1)
    curr_bull      = close > open_
    bull_wrap      = (open_ <= close.shift(1)) & (close >= open_.shift(1))
    bullish_engulf = prev_bear & curr_bull & bull_wrap

    prev_bull      = close.shift(1) > open_.shift(1)
    curr_bear      = close < open_
    bear_wrap      = (open_ >= close.shift(1)) & (close <= open_.shift(1))
    bearish_engulf = prev_bull & curr_bear & bear_wrap

    # ── Entry conditions ─────────────────────────────────────────────────────
    long_entries  = (rsi < 30) & (low.shift(1)  <= bb_lower.shift(1)) & bullish_engulf
    short_entries = (rsi > 70) & (high.shift(1) >= bb_upper.shift(1)) & bearish_engulf

    # Resolve conflicts (same bar/symbol): long takes priority
    conflict      = long_entries & short_entries
    short_entries = short_entries & ~conflict

    # ── Stop distances as fraction of entry price ────────────────────────────
    sl_long  = ((close - bb_lower.shift(1)) / close).clip(lower=MIN_SL_PCT)
    sl_short = ((bb_upper.shift(1) - close) / close).clip(lower=MIN_SL_PCT)

    # ── Build combined arrays (only meaningful at entry bars) ────────────────
    risk_dollar = INIT_CASH * RISK_PCT   # $1,000 at risk per trade

    sl_stop = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    tp_stop = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    size    = pd.DataFrame(np.nan, index=close.index, columns=close.columns)

    sl_stop[long_entries]  = sl_long[long_entries]
    tp_stop[long_entries]  = (sl_long * REWARD_RATIO)[long_entries]
    size[long_entries]     = (risk_dollar / sl_long).clip(upper=MAX_POS_VALUE)[long_entries]

    sl_stop[short_entries] = sl_short[short_entries]
    tp_stop[short_entries] = (sl_short * REWARD_RATIO)[short_entries]
    size[short_entries]    = (risk_dollar / sl_short).clip(upper=MAX_POS_VALUE)[short_entries]

    # Replace NaN with 0 for non-signal bars (vectorbt ignores these)
    sl_stop = sl_stop.fillna(0)
    tp_stop = tp_stop.fillna(0)
    size    = size.fillna(0)

    return long_entries, short_entries, sl_stop, tp_stop, size


# ── Portfolio backtest ────────────────────────────────────────────────────────
def run_backtest(ohlcv: dict) -> vbt.Portfolio:
    close = ohlcv["close"]

    long_entries, short_entries, sl_stop, tp_stop, size = build_signals(ohlcv)

    n_long  = long_entries.values.sum()
    n_short = short_entries.values.sum()
    print(f"Signals — LONG: {n_long}  SHORT: {n_short}")

    no_exit = pd.DataFrame(False, index=close.index, columns=close.columns)

    pf = vbt.Portfolio.from_signals(
        close         = close,
        entries       = long_entries,
        exits         = no_exit,
        short_entries = short_entries,
        short_exits   = no_exit,
        sl_stop       = sl_stop,
        tp_stop       = tp_stop,
        size          = size,
        size_type     = "value",
        init_cash     = INIT_CASH,
        fees          = FEE_PCT,
        freq          = "15min",
        group_by      = True,
        cash_sharing  = True,
    )
    return pf


# ── Results ───────────────────────────────────────────────────────────────────
def print_results(pf: vbt.Portfolio) -> None:
    total_ret = float(pf.total_return()) * 100
    max_dd    = float(pf.max_drawdown())  * 100
    sharpe    = float(pf.sharpe_ratio())
    n_trades  = int(pf.trades.count())
    win_rate  = float(pf.trades.win_rate()) * 100 if n_trades > 0 else 0.0

    print()
    print("=" * 58)
    print("  Bot 2 — Ross Cameron Strategy  |  VectorBT Backtest")
    print("=" * 58)
    print(f"  Symbols         : {', '.join(WATCHLIST)}")
    print(f"  Timeframe       : 1 year 15-minute bars")
    print(f"  Starting Capital: ${INIT_CASH:>12,.0f}")
    print(f"  Fees            : {FEE_PCT * 100:.1f}% per trade")
    print(f"  Risk per trade  : {RISK_PCT * 100:.1f}%  (1:2 R:R)")
    print("-" * 58)
    print(f"  Total Return    : {total_ret:>+8.2f}%")
    print(f"  Win Rate        : {win_rate:>8.1f}%")
    print(f"  Max Drawdown    : {max_dd:>8.2f}%")
    print(f"  Sharpe Ratio    : {sharpe:>8.3f}")
    print(f"  Number of Trades: {n_trades:>8d}")
    print("=" * 58)


def save_chart(pf: vbt.Portfolio) -> None:
    equity  = pf.value()
    drawdown = pf.drawdown() * 100

    total_ret = float(pf.total_return()) * 100
    max_dd    = float(pf.max_drawdown())  * 100
    sharpe    = float(pf.sharpe_ratio())
    n_trades  = int(pf.trades.count())
    win_rate  = float(pf.trades.win_rate()) * 100 if n_trades > 0 else 0.0

    fig, axes = plt.subplots(3, 1, figsize=(14, 11))
    fig.suptitle(
        "Bot 2 — Ross Cameron Momentum Strategy  |  VectorBT Backtest (1 Year, 15-Min Bars)",
        fontsize=13, fontweight="bold", y=0.98,
    )

    # Panel 1: equity curve
    axes[0].plot(equity.index, equity.values, color="steelblue", linewidth=1.8, label="Portfolio")
    axes[0].axhline(INIT_CASH, color="gray", linestyle="--", linewidth=0.9, label="Starting capital")
    axes[0].set_title("Portfolio Value", fontsize=11)
    axes[0].set_ylabel("USD ($)")
    axes[0].yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    axes[0].legend(fontsize=9)
    axes[0].grid(True, alpha=0.3)

    # Panel 2: drawdown
    axes[1].fill_between(drawdown.index, drawdown.values, 0, color="crimson", alpha=0.55)
    axes[1].set_title("Drawdown (%)", fontsize=11)
    axes[1].set_ylabel("%")
    axes[1].grid(True, alpha=0.3)

    # Panel 3: trade P&L bars
    trades = pf.trades.records_readable
    if len(trades) > 0 and "PnL" in trades.columns:
        pnl    = trades["PnL"].values
        colors = ["green" if p > 0 else "red" for p in pnl]
        axes[2].bar(range(len(pnl)), pnl, color=colors, alpha=0.75, width=0.8)
        axes[2].axhline(0, color="black", linewidth=0.8)
        axes[2].set_title("Trade P&L ($)", fontsize=11)
        axes[2].set_ylabel("P&L ($)")
        axes[2].set_xlabel("Trade #")
    else:
        axes[2].text(0.5, 0.5, "No closed trades", transform=axes[2].transAxes,
                     ha="center", va="center", fontsize=12)
        axes[2].set_title("Trade P&L ($)", fontsize=11)
    axes[2].grid(True, alpha=0.3)

    stats_text = (
        f"Return: {total_ret:+.1f}%   |   Win Rate: {win_rate:.1f}%   |   "
        f"Max DD: {max_dd:.1f}%   |   Sharpe: {sharpe:.2f}   |   Trades: {n_trades}"
    )
    fig.text(0.5, 0.005, stats_text, ha="center", fontsize=10,
             bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.85))

    plt.tight_layout(rect=[0, 0.04, 1, 0.97])
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches="tight")
    print(f"\nChart saved → {OUTPUT_FILE}")


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    print("\nBot 2 — Ross Cameron Strategy  |  VectorBT Backtest")
    print("-" * 50)

    ohlcv = fetch_15min_bars(WATCHLIST)
    pf    = run_backtest(ohlcv)
    print_results(pf)
    save_chart(pf)


if __name__ == "__main__":
    main()
