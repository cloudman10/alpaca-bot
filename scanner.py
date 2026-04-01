"""
scanner.py — Pre-market gap scanner for Bot 2 (Ross Cameron 15m Momentum).

Daily timeline (all times Eastern):
  9:00 AM  — fetch pre-market prices, calculate gaps vs previous close
  9:10 AM  — calculate RVOL for gap candidates
  9:20 AM  — finalize dynamic watchlist (top 5)
  9:30 AM  — hand off to main.py for RSI/BB/Engulfing entry logic

Gap detection:
  - Scans a broad volatile universe (no ScreenerClient required)
  - Gap % = (latest_price - prev_close) / prev_close
  - Pre-market price: latest 1-min bar available via IEX (may be limited pre-9:30)
  - Fallback: today's open vs prev_close if pre-market bars unavailable

RVOL filter:
  - Fetches 10 days of daily bars
  - RVOL = today_volume / avg_10day_volume
  - Only keeps stocks with RVOL > 2.0

Result:
  - Returns top 5 symbols sorted by gap % (descending)
  - Falls back to DEFAULT_WATCHLIST if no candidates pass filters
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

GAP_MIN_PCT = 0.04   # 4% minimum gap (gainers only)
RVOL_MIN    = 2.0    # 2× relative volume minimum
MAX_SYMBOLS = 5      # cap dynamic watchlist at 5


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


def run_gap_scanner(
    gap_min: float = GAP_MIN_PCT,
    rvol_min: float = RVOL_MIN,
    max_symbols: int = MAX_SYMBOLS,
) -> list[str]:
    """
    Full pre-market gap scan pipeline.

    Stage 1 — Gap filter (9:00 AM ET):
      Scan SCAN_UNIVERSE, keep gainers with gap >= gap_min (default 4%).

    Stage 2 — RVOL filter (9:10 AM ET):
      For each gap candidate, calculate RVOL. Keep RVOL >= rvol_min (default 2×).
      If ALL candidates fail RVOL, fall back to gap-only list.

    Stage 3 — Finalize (9:20 AM ET):
      Sort by gap % descending. Return top max_symbols (default 5).
      If no candidates at all, return DEFAULT_WATCHLIST.

    Returns:
      list[str] — symbol list for today's trading session
    """
    logger.info(
        "=== Gap Scanner: scanning %d symbols (gap > %.0f%%, RVOL > %.1fx) ===",
        len(SCAN_UNIVERSE), gap_min * 100, rvol_min,
    )

    # ── Stage 1: Gap filter ──────────────────────────────────────────────────
    gap_candidates: list[tuple[str, float]] = []

    for symbol in SCAN_UNIVERSE:
        gap = calculate_gap(symbol)
        if gap is None:
            continue
        if gap >= gap_min:
            gap_candidates.append((symbol, gap))
            logger.info("[%s] GAP +%.1f%% ✓", symbol, gap * 100)
        else:
            logger.debug("[%s] gap %.1f%% below threshold", symbol, gap * 100)

    if not gap_candidates:
        logger.warning(
            "No symbols gapping > %.0f%% — falling back to default watchlist: %s",
            gap_min * 100, DEFAULT_WATCHLIST,
        )
        return DEFAULT_WATCHLIST

    logger.info(
        "Stage 1 complete: %d gap candidates — %s",
        len(gap_candidates), [s for s, _ in gap_candidates],
    )

    # ── Stage 2: RVOL filter ─────────────────────────────────────────────────
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
        logger.warning(
            "No candidates passed RVOL filter — using gap-only list (RVOL requirement relaxed)",
        )
        rvol_candidates = [(s, g, 0.0) for s, g in gap_candidates]

    # ── Stage 3: Finalize ────────────────────────────────────────────────────
    rvol_candidates.sort(key=lambda x: x[1], reverse=True)
    watchlist = [s for s, _, _ in rvol_candidates[:max_symbols]]

    logger.info(
        "=== Dynamic watchlist finalized (%d symbols): %s ===",
        len(watchlist), watchlist,
    )
    return watchlist
