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
