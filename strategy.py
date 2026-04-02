"""
strategy.py — Ross Cameron 15-minute Momentum signal detection.

LONG setup (4 conditions):
  1. RSI < 25  (deeper oversold threshold, lowered from 30)
  2. Previous candle touched lower Bollinger Band (low <= lower BB)
  3. Bullish engulfing pattern
  4. Volume climax: current bar volume > 2× 20-bar average (capitulation confirmation)

SHORT setup (4 conditions):
  1. RSI > 70
  2. Previous candle pierced upper Bollinger Band (high >= upper BB)
  3. Bearish engulfing pattern
  4. Volume climax: current bar volume > 2× 20-bar average

Stop-loss:   outer BB of the trigger candle
Take-profit: VWAP if valid (above entry for LONG / below for SHORT), else 1:2 R:R
"""

import logging
import pandas as pd
from indicators import is_bullish_engulfing, is_bearish_engulfing
from risk_manager import calc_take_profit

logger = logging.getLogger(__name__)

RSI_OVERSOLD       = 25   # lowered from 30 — catches deeper oversold (e.g. TSLA RSI 20)
RSI_OVERBOUGHT     = 70
VOLUME_CLIMAX_MULT = 2.0  # current bar volume must be > 2× 20-bar avg


def detect_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """
    Detect buy/short signals on a DataFrame with indicator columns.
    Returns a signal dict or None.
    """
    if len(df) < 3:
        return None

    # Check that required indicator columns exist
    required = ["RSI_14", "BBL_20_2.0", "BBU_20_2.0", "volume_avg_20", "VWAP"]
    if not all(col in df.columns for col in required):
        return None

    # Drop rows where indicators haven't warmed up
    df_clean = df.dropna(subset=["RSI_14", "BBL_20_2.0", "BBU_20_2.0", "volume_avg_20"])
    if len(df_clean) < 2:
        return None

    # Most recent two candles
    bar_n  = df_clean.iloc[-1]  # current candle
    bar_n1 = df_clean.iloc[-2]  # previous candle

    last_rsi    = bar_n["RSI_14"]
    bb_lower_n1 = bar_n1["BBL_20_2.0"]
    bb_upper_n1 = bar_n1["BBU_20_2.0"]
    vol_avg     = bar_n["volume_avg_20"]
    vwap        = bar_n["VWAP"] if pd.notna(bar_n.get("VWAP")) else None

    # Volume climax: current bar volume > 2× 20-bar average
    volume_climax = (vol_avg > 0) and (bar_n["volume"] > VOLUME_CLIMAX_MULT * vol_avg)

    # ── LONG setup ───────────────────────────────────────────────────────
    long_cond1 = last_rsi < RSI_OVERSOLD
    long_cond2 = bar_n1["low"] <= bb_lower_n1        # touched lower band
    long_cond3 = is_bullish_engulfing(bar_n1, bar_n) # bullish engulfing
    long_cond4 = volume_climax                        # capitulation volume

    if long_cond1 and long_cond2 and long_cond3 and long_cond4:
        entry       = bar_n["close"]
        stop_loss   = bb_lower_n1
        take_profit = calc_take_profit(entry, stop_loss, "LONG", vwap=vwap)

        return {
            "direction":   "LONG",
            "symbol":      symbol,
            "entry_price": entry,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "reason": (
                f"LONG | RSI={last_rsi:.1f} | "
                f"LowTouchedBB({bar_n1['low']:.2f}<={bb_lower_n1:.2f}) | "
                f"BullishEngulfing | "
                f"VolClimax({bar_n['volume']:.0f}>{VOLUME_CLIMAX_MULT}x{vol_avg:.0f}) | "
                f"TP=VWAP({vwap:.2f})" if vwap else
                f"LONG | RSI={last_rsi:.1f} | "
                f"LowTouchedBB({bar_n1['low']:.2f}<={bb_lower_n1:.2f}) | "
                f"BullishEngulfing | "
                f"VolClimax({bar_n['volume']:.0f}>{VOLUME_CLIMAX_MULT}x{vol_avg:.0f}) | "
                f"TP=1:2RR"
            ),
        }

    # ── SHORT setup ──────────────────────────────────────────────────────
    short_cond1 = last_rsi > RSI_OVERBOUGHT
    short_cond2 = bar_n1["high"] >= bb_upper_n1       # pierced upper band
    short_cond3 = is_bearish_engulfing(bar_n1, bar_n) # bearish engulfing
    short_cond4 = volume_climax                        # capitulation volume

    if short_cond1 and short_cond2 and short_cond3 and short_cond4:
        entry       = bar_n["close"]
        stop_loss   = bb_upper_n1
        take_profit = calc_take_profit(entry, stop_loss, "SHORT", vwap=vwap)

        return {
            "direction":   "SHORT",
            "symbol":      symbol,
            "entry_price": entry,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "reason": (
                f"SHORT | RSI={last_rsi:.1f} | "
                f"HighPiercedBB({bar_n1['high']:.2f}>={bb_upper_n1:.2f}) | "
                f"BearishEngulfing | "
                f"VolClimax({bar_n['volume']:.0f}>{VOLUME_CLIMAX_MULT}x{vol_avg:.0f}) | "
                f"TP=VWAP({vwap:.2f})" if vwap else
                f"SHORT | RSI={last_rsi:.1f} | "
                f"HighPiercedBB({bar_n1['high']:.2f}>={bb_upper_n1:.2f}) | "
                f"BearishEngulfing | "
                f"VolClimax({bar_n['volume']:.0f}>{VOLUME_CLIMAX_MULT}x{vol_avg:.0f}) | "
                f"TP=1:2RR"
            ),
        }

    return None
