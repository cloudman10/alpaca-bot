"""
scanner.py — Pre-market gap scanner for Bot 2 (Gap-UP Momentum).

Daily timeline (all times Eastern):
  9:00 AM  — fetch pre-market prices, calculate gaps vs previous close
  9:10 AM  — calculate RVOL and apply quality filters
  9:20 AM  — finalize dynamic watchlist (top 5)
  9:30 AM  — hand off to main.py for entry logic

Tiered gap system:
  Tier 1: Gap > 4%  → full position (8% of equity), VWAP pullback entry
  Tier 2: Gap > 2%  → half position (4% of equity), 15-min high breakout entry
  Both tiers require: RVOL > 1.0×, Market Cap > $1B, pre-market volume > 50k
  Fallback (no gaps): default watchlist, no gap entry attempted

Use get_scan_tier() in main.py to check which tier fired after scanner runs.
"""

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed
from alpaca_service import data_client

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

# Universe to scan — volatile/high-beta names that commonly gap
SCAN_UNIVERSE = [
    # Mega-cap / index
    "AAPL", "TSLA", "NVDA", "AMD", "META", "AMZN", "MSFT", "GOOGL", "SPY", "QQQ",
    # High-beta momentum
    "SMCI", "MSTR", "COIN", "HOOD", "PLTR", "RIVN", "SOFI", "UPST", "SNAP",
    "RBLX", "SHOP", "SQ", "PYPL", "ROKU", "UBER", "DKNG", "PENN",
    # Speculative
    "GME", "AMC", "CVNA", "BYND", "SPCE",
]

DEFAULT_WATCHLIST = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "META"]

# Tiered gap thresholds
TIER1_GAP_PCT     = 0.04    # Tier 1: full position (8% of equity)
TIER2_GAP_PCT     = 0.02    # Tier 2 fallback: half position (4% of equity)
PREMARKET_VOL_MIN = 50_000  # minimum pre-market volume (both tiers)
RVOL_MIN          = 1.0     # 1.0× relative volume minimum (both tiers)
MAX_SYMBOLS       = 5       # cap dynamic watchlist at 5

# Market cap > $1B filter (static allow-list from SCAN_UNIVERSE)
# Excludes BYND (~$150M), SPCE (<$100M) which are too small
LARGE_CAP_UNIVERSE = {
    "AAPL", "TSLA", "NVDA", "AMD", "META", "AMZN", "MSFT", "GOOGL", "SPY", "QQQ",
    "SMCI", "MSTR", "COIN", "HOOD", "PLTR", "RIVN", "SOFI", "UPST", "SNAP",
    "RBLX", "SHOP", "SQ", "PYPL", "ROKU", "UBER", "DKNG", "PENN",
    "GME", "AMC", "CVNA",
}

# ── Module-level tier state ───────────────────────────────────────────────────

_scan_tier: int = 0   # 0=default, 1=tier1 (>4%), 2=tier2 (>2%)


def get_scan_tier() -> int:
    """Return the tier detected by the most recent scan.

    0 = default watchlist (no gap candidates)
    1 = Tier 1 (gap > 4%) — full position, VWAP entry
    2 = Tier 2 (gap > 2%) — half position, 15-min high breakout entry
    """
    return _scan_tier


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_daily_bars(symbol: str, days: int = 15) -> pd.DataFrame:
    """Fetch recent daily bars for a symbol via IEX."""
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    req  = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed=DataFeed.IEX,
    )
    bars = data_client.get_stock_bars(req)
    df   = bars.df

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")

    return df.sort_index()


def _get_latest_intraday_price(symbol: str) -> float | None:
    """
    Get the latest available price for gap calculation.
    Uses 1-min bars from the last 2 hours — picks up pre-market on SIP;
    on IEX free tier this returns the most recent bar (may be yesterday's close
    if pre-market is not yet available).
    Returns None if no data is found.
    """
    end   = datetime.now(timezone.utc)
    start = end - timedelta(hours=2)

    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Minute),
        start=start,
        end=end,
        feed=DataFeed.IEX,
    )
    try:
        bars = data_client.get_stock_bars(req)
        df   = bars.df

        if df.empty:
            return None

        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")

        return float(df["close"].iloc[-1]) if not df.empty else None
    except Exception:
        return None


def _get_premarket_volume(symbol: str) -> float | None:
    """
    Get total pre-market volume from 4:00 AM to now (or 9:30 AM ET) today.
    Best-effort — returns None if data unavailable (IEX may not cover pre-market).
    """
    end   = datetime.now(timezone.utc)
    start = end - timedelta(hours=6)   # approx 4 AM ET coverage

    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Minute),
        start=start,
        end=end,
        feed=DataFeed.IEX,
    )
    try:
        bars = data_client.get_stock_bars(req)
        df   = bars.df

        if df.empty:
            return None

        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")

        return float(df["volume"].sum()) if not df.empty else None
    except Exception:
        return None


# ── Public interface ──────────────────────────────────────────────────────────

def calculate_gap(symbol: str) -> float | None:
    """
    Calculate gap % vs previous day's close.
      gap = (latest_price - prev_close) / prev_close

    Priority order for 'latest_price':
      1. Latest 1-min bar from _get_latest_intraday_price (pre-market if available)
      2. Today's open from the daily bar (fallback at/after 9:30 AM ET)

    Returns None on any error.
    """
    try:
        daily = _get_daily_bars(symbol, days=5)
        if len(daily) < 2:
            return None

        prev_close = float(daily["close"].iloc[-2])
        if prev_close <= 0:
            return None

        latest = _get_latest_intraday_price(symbol)

        if latest is None:
            # Fallback: use today's open from daily bar (available after 9:30 AM)
            today_open = float(daily["open"].iloc[-1])
            if today_open > 0:
                latest = today_open
            else:
                return None

        return (latest - prev_close) / prev_close

    except Exception as e:
        logger.debug("[%s] Gap calc error: %s", symbol, e)
        return None


def calculate_rvol(symbol: str) -> float | None:
    """
    Calculate Relative Volume = today's volume / 10-day average daily volume.
    Returns None on error.
    """
    try:
        daily = _get_daily_bars(symbol, days=15)
        if len(daily) < 2:
            return None

        avg_vol = float(daily["volume"].iloc[:-1].tail(10).mean())
        if avg_vol <= 0:
            return None

        today_vol = float(daily["volume"].iloc[-1])
        return today_vol / avg_vol

    except Exception as e:
        logger.debug("[%s] RVOL calc error: %s", symbol, e)
        return None


def _find_candidates(
    gap_min: float,
    rvol_min: float = RVOL_MIN,
    max_symbols: int = MAX_SYMBOLS,
) -> list[str]:
    """
    Internal: scan LARGE_CAP_UNIVERSE for gap >= gap_min, apply RVOL and
    pre-market volume filters. Returns sorted symbol list (empty if none pass).
    """
    # Stage 1: gap filter (large-cap universe only)
    gap_candidates: list[tuple[str, float]] = []

    for symbol in SCAN_UNIVERSE:
        if symbol not in LARGE_CAP_UNIVERSE:
            logger.debug("[%s] Not in large-cap universe — skip", symbol)
            continue

        gap = calculate_gap(symbol)
        if gap is None:
            continue
        if gap >= gap_min:
            gap_candidates.append((symbol, gap))
            logger.info("[%s] GAP +%.1f%% ✓", symbol, gap * 100)
        else:
            logger.debug("[%s] gap %.1f%% below %.0f%% threshold", symbol, gap * 100, gap_min * 100)

    if not gap_candidates:
        return []

    logger.info(
        "Stage 1 complete: %d gap candidates — %s",
        len(gap_candidates), [s for s, _ in gap_candidates],
    )

    # Stage 2: RVOL filter
    rvol_candidates: list[tuple[str, float, float]] = []

    for symbol, gap in gap_candidates:
        rvol = calculate_rvol(symbol)
        if rvol is None:
            logger.debug("[%s] RVOL unavailable — skipping", symbol)
            continue
        if rvol >= rvol_min:
            rvol_candidates.append((symbol, gap, rvol))
            logger.info("[%s] RVOL %.1fx ✓", symbol, rvol)
        else:
            logger.info("[%s] RVOL %.1fx below %.1fx threshold", symbol, rvol, rvol_min)

    if not rvol_candidates:
        logger.warning("No candidates passed RVOL filter — using gap-only list")
        rvol_candidates = [(s, g, 0.0) for s, g in gap_candidates]

    # Stage 3: Pre-market volume filter (best-effort — skip if data unavailable)
    vol_filtered: list[tuple[str, float, float]] = []
    for symbol, gap, rvol in rvol_candidates:
        pm_vol = _get_premarket_volume(symbol)
        if pm_vol is None:
            # IEX may not have pre-market data — allow through
            logger.debug("[%s] Pre-market volume unavailable — allowing through", symbol)
            vol_filtered.append((symbol, gap, rvol))
        elif pm_vol >= PREMARKET_VOL_MIN:
            logger.info("[%s] Pre-market vol %.0f ✓", symbol, pm_vol)
            vol_filtered.append((symbol, gap, rvol))
        else:
            logger.info("[%s] Pre-market vol %.0f < %d threshold — skip", symbol, pm_vol, PREMARKET_VOL_MIN)

    if not vol_filtered:
        logger.warning("No candidates passed pre-market volume filter — relaxing")
        vol_filtered = rvol_candidates

    # Stage 4: Finalize — sort by gap, return top N
    vol_filtered.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _, _ in vol_filtered[:max_symbols]]


def run_gap_scanner(
    rvol_min: float = RVOL_MIN,
    max_symbols: int = MAX_SYMBOLS,
) -> list[str]:
    """
    Full pre-market gap scan pipeline with tiered fallback.

    Tier 1 (gap > 4%): Full position size (8% of equity), VWAP pullback entry.
    Tier 2 (gap > 2%): Half position size (4% of equity), 15-min high breakout entry.
    Default: no gap candidates — return DEFAULT_WATCHLIST, no gap entry attempted.

    Call get_scan_tier() after this returns to determine which tier fired.
    """
    global _scan_tier

    logger.info(
        "=== Gap Scanner: scanning %d symbols (Tier1 >%.0f%%, Tier2 >%.0f%%, RVOL > %.1fx) ===",
        len(SCAN_UNIVERSE), TIER1_GAP_PCT * 100, TIER2_GAP_PCT * 100, rvol_min,
    )

    # ── Try Tier 1 (gap > 4%) ────────────────────────────────────────────────
    tier1 = _find_candidates(TIER1_GAP_PCT, rvol_min, max_symbols)
    if tier1:
        _scan_tier = 1
        logger.info(
            "=== Tier 1 gap detected (>4%%): %d symbols — full position (8%% equity), VWAP entry ===",
            len(tier1),
        )
        logger.info("=== Dynamic watchlist finalized (%d symbols): %s ===", len(tier1), tier1)
        return tier1

    logger.info("No Tier 1 candidates (>4%%) — trying Tier 2 fallback (>2%%)")

    # ── Try Tier 2 fallback (gap > 2%) ───────────────────────────────────────
    tier2 = _find_candidates(TIER2_GAP_PCT, rvol_min, max_symbols)
    if tier2:
        _scan_tier = 2
        logger.info(
            "=== Tier 2 gap detected (>2%%): %d symbols — HALF position (4%% equity), 15-min high breakout entry ===",
            len(tier2),
        )
        logger.info("=== Dynamic watchlist finalized (%d symbols): %s ===", len(tier2), tier2)
        return tier2

    # ── No candidates — default watchlist ────────────────────────────────────
    _scan_tier = 0
    logger.warning(
        "No gap candidates (Tier1 or Tier2) — falling back to default watchlist: %s",
        DEFAULT_WATCHLIST,
    )
    return DEFAULT_WATCHLIST
