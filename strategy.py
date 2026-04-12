"""
strategy.py — Gap-UP Momentum: VWAP pullback (Tier 1) and 15-min high breakout (Tier 2).

Tier 1 entry (VWAP pullback — all must be met):
  1. Current bar is within first 30 min of session (9:30–10:00 AM ET) — enforced by caller
  2. Previous bar's low touched or was at/below VWAP (pullback to VWAP occurred)
  3. Current bar closes ABOVE VWAP (bullish reclaim)
  4. Current bar is a bullish candle (close > open)
  5. RSI(14) between 45–65 (post-gap RSI in a healthy range, not overbought)
  6. Volume on current bar > 1.5× 20-bar average (buyers confirming the reclaim)
  7. SPY not making new lows (passed in as spy_stable)

Tier 2 entry (15-min opening high breakout — all must be met):
  1. Current bar is within first 30 min of session — enforced by caller
  2. Price breaks above the high of the first 15-min bar (opening range high)
  3. Current bar is a bullish candle (close > open)
  4. SPY not making new lows (passed in as spy_stable)
  Stop loss: low of the opening 15-min bar

Exit rules (managed in main.py):
  - Take Profit : previous day high (if above entry) OR 4% above entry
  - Stop Loss   : VWAP at entry (Tier 1) / opening bar low (Tier 2)
  - Kill Switch : 2% daily loss limit (DailyKillSwitch in risk_manager.py)
"""

import logging
import pandas as pd
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

RSI_MIN = 45    # lower bound — avoid entries when stock is still weak
RSI_MAX = 65    # upper bound — avoid chasing overbought gap continuation
VOL_MULT = 1.5  # volume must be > 1.5× 20-bar average on entry candle
ET = ZoneInfo("America/New_York")


def _today_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Return only bars from today's session (ET date match)."""
    from datetime import datetime
    today = datetime.now(ET).date()
    times = pd.to_datetime(df["time"]).dt.tz_localize("UTC", ambiguous="infer").dt.tz_convert(ET).dt.date
    return df[times == today].reset_index(drop=True)


def detect_signal(
    symbol: str,
    df: pd.DataFrame,
    spy_stable: bool = True,
) -> dict | None:
    """
    Detect a VWAP-reclaim entry signal on the 15-minute df with indicators.
    Returns a signal dict or None.

    Required columns: RSI_14, VWAP, volume_avg_20, time, open, high, low, close, volume.
    """
    if len(df) < 3:
        return None

    required = ["RSI_14", "VWAP", "volume_avg_20"]
    if not all(c in df.columns for c in required):
        logger.debug("[%s] Missing required columns — skipping", symbol)
        return None

    # ── Filter to today's bars only ───────────────────────────────────────────
    today = _today_bars(df)
    if len(today) < 2:
        logger.info("[%s] Less than 2 intraday bars today — waiting", symbol)
        return None

    bar_curr = today.iloc[-1]
    bar_prev = today.iloc[-2]

    vwap    = bar_curr.get("VWAP")
    rsi     = bar_curr.get("RSI_14")
    vol_avg = bar_curr.get("volume_avg_20")

    if any(pd.isna(x) for x in [vwap, rsi, vol_avg]):
        logger.debug("[%s] NaN in key indicators — skipping", symbol)
        return None

    vwap    = float(vwap)
    rsi     = float(rsi)
    vol_avg = float(vol_avg)

    # ── Condition 1: SPY market confirmation ──────────────────────────────────
    if not spy_stable:
        logger.info("[%s] SPY making new lows — skip entry", symbol)
        return None

    # ── Condition 2: RSI 45–65 ────────────────────────────────────────────────
    if not (RSI_MIN <= rsi <= RSI_MAX):
        logger.info("[%s] RSI %.1f outside %d–%d range — skip", symbol, rsi, RSI_MIN, RSI_MAX)
        return None

    # ── Condition 3: Previous bar touched/went below VWAP (pullback) ──────────
    if float(bar_prev["low"]) > vwap:
        logger.info(
            "[%s] No VWAP pullback: prev low (%.2f) > VWAP (%.2f) — skip",
            symbol, bar_prev["low"], vwap,
        )
        return None

    # ── Condition 4: Current bar closes above VWAP (reclaim) ─────────────────
    curr_close = float(bar_curr["close"])
    if curr_close <= vwap:
        logger.info("[%s] Price %.2f not above VWAP %.2f — skip", symbol, curr_close, vwap)
        return None

    # ── Condition 5: Bullish candle (close > open) ────────────────────────────
    curr_open = float(bar_curr["open"])
    if curr_close <= curr_open:
        logger.info("[%s] Not a bullish candle (close %.2f <= open %.2f) — skip",
                    symbol, curr_close, curr_open)
        return None

    # ── Condition 6: Volume > 1.5× average ───────────────────────────────────
    curr_vol = float(bar_curr["volume"])
    if vol_avg > 0 and curr_vol < vol_avg * VOL_MULT:
        logger.info(
            "[%s] Volume %.0f < %.0f (%.1fx avg) — skip",
            symbol, curr_vol, vol_avg * VOL_MULT, VOL_MULT,
        )
        return None

    # ── All conditions met ────────────────────────────────────────────────────
    entry     = curr_close
    stop_loss = vwap   # stop below VWAP at time of entry

    logger.info(
        "[%s] SIGNAL | VWAP reclaim | entry=%.2f VWAP=%.2f | RSI=%.1f | vol=%.0f/%.0f",
        symbol, entry, vwap, rsi, curr_vol, vol_avg * VOL_MULT,
    )

    return {
        "direction":   "LONG",
        "symbol":      symbol,
        "entry_price": entry,
        "stop_loss":   stop_loss,
        "vwap":        vwap,
        "tier":        1,
        "reason":      (
            f"Tier 1 gap detected (>4%%) | VWAP reclaim | RSI={rsi:.1f} | "
            f"prev_low={bar_prev['low']:.2f}<=VWAP={vwap:.2f} | "
            f"vol={curr_vol:.0f}/{vol_avg * VOL_MULT:.0f}"
        ),
    }


def detect_tier2_signal(
    symbol: str,
    df: pd.DataFrame,
    spy_stable: bool = True,
) -> dict | None:
    """
    Detect a Tier 2 entry: 15-minute opening range high breakout.
    No VWAP pullback required — enters on break of first 15-min bar's high.

    Conditions:
      1. SPY not making new lows
      2. Price (current close) > high of first 15-min bar (opening range high)
      3. Current bar is bullish (close > open)

    Stop loss: low of the first 15-min bar (opening range low).
    """
    if len(df) < 2:
        return None

    # ── Filter to today's bars only ───────────────────────────────────────────
    today = _today_bars(df)
    if len(today) < 2:
        logger.info("[%s] Tier 2: less than 2 intraday bars today — waiting", symbol)
        return None

    # ── Condition 1: SPY market confirmation ──────────────────────────────────
    if not spy_stable:
        logger.info("[%s] SPY making new lows — skip Tier 2 entry", symbol)
        return None

    opening_bar  = today.iloc[0]   # first 15-min bar: 9:30–9:45 AM ET
    opening_high = float(opening_bar["high"])
    opening_low  = float(opening_bar["low"])

    bar_curr   = today.iloc[-1]
    curr_close = float(bar_curr["close"])
    curr_open  = float(bar_curr["open"])

    # ── Condition 2: price breaks above opening range high ────────────────────
    if curr_close <= opening_high:
        logger.info(
            "[%s] Tier 2: price %.2f not above opening high %.2f — skip",
            symbol, curr_close, opening_high,
        )
        return None

    # ── Condition 3: bullish candle ───────────────────────────────────────────
    if curr_close <= curr_open:
        logger.info(
            "[%s] Tier 2: not a bullish candle (close %.2f <= open %.2f) — skip",
            symbol, curr_close, curr_open,
        )
        return None

    stop_loss = opening_low   # stop below opening range low

    logger.info(
        "[%s] TIER 2 SIGNAL | 15-min high breakout | entry=%.2f opening_high=%.2f stop=%.2f",
        symbol, curr_close, opening_high, stop_loss,
    )

    return {
        "direction":   "LONG",
        "symbol":      symbol,
        "entry_price": curr_close,
        "stop_loss":   stop_loss,
        "tier":        2,
        "reason":      (
            f"Tier 2 gap detected (>2%%) | 15-min high breakout | "
            f"entry={curr_close:.2f} > opening_high={opening_high:.2f} | "
            f"stop={stop_loss:.2f} (opening_low)"
        ),
    }
