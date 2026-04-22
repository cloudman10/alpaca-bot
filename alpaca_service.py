"""
alpaca_service.py — Alpaca client using alpaca-py for account, market data, and orders.
"""

import json
import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

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

def get_1m_bars(symbol: str, limit: int = 10) -> pd.DataFrame:
    """Fetch 1-minute bars for a symbol over the last hour using IEX feed."""
    start = datetime.utcnow() - timedelta(hours=1)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Minute),
        start=start,
        limit=limit,
        feed="iex",
    )

    bars = data_client.get_stock_bars(request)
    bar_list = bars[symbol]

    records = []
    for bar in bar_list:
        records.append({
            "time":   bar.timestamp.isoformat(),
            "open":   float(bar.open),
            "high":   float(bar.high),
            "low":    float(bar.low),
            "close":  float(bar.close),
            "volume": int(bar.volume),
        })

    return pd.DataFrame(records)


def get_15m_bars(symbol: str, limit: int = 50) -> pd.DataFrame:
    """Fetch 15-minute bars for a symbol over the last 7 days using IEX feed."""
    start = datetime.utcnow() - timedelta(days=7)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(amount=15, unit=TimeFrameUnit.Minute),
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


# ── Slippage Guard ────────────────────────────────────────────────────────────

SLIPPAGE_THRESHOLD = 0.0075                                      # 0.75%
_VETO_LOG_PATH     = Path(__file__).parent / "logs" / "slippage_vetoes.json"


def _append_veto_event(symbol: str, signal_price: float, rt_price: float, delta_pct: float) -> None:
    """Atomically append a veto event to slippage_vetoes.json (capped at 50 entries)."""
    event = {
        "ts":           datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbol":       symbol,
        "signal_price": round(signal_price, 4),
        "rt_price":     round(rt_price, 4),
        "delta_pct":    round(delta_pct, 4),
    }
    try:
        _VETO_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        events: list = []
        if _VETO_LOG_PATH.exists():
            try:
                events = json.loads(_VETO_LOG_PATH.read_text())
            except Exception:
                events = []
        events.append(event)
        events = events[-50:]           # keep last 50 so the file doesn't grow unbounded
        tmp = _VETO_LOG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(events, indent=2))
        tmp.replace(_VETO_LOG_PATH)
    except Exception as exc:
        logger.warning("Failed to persist veto event: %s", exc)


# ── Order placement ──────────────────────────────────────────────────────────

def place_bracket_order(
    symbol: str,
    qty: int,
    side: str,
    limit_price: float,
    stop_loss: float,
    take_profit: float,
) -> str | None:
    """Place a bracket order (entry limit + stop-loss + take-profit).

    For BUY orders, a real-time slippage guard runs right before submit_order.
    If the live SIP price is more than 0.75% above the IEX signal price,
    the order is vetoed (returns None) and the event is logged + persisted.
    """
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

    # ── Slippage Guard (BUY only) ─────────────────────────────────────────────
    # IEX bars are 15-min delayed. Fetch the real-time SIP price right before
    # submitting so we never chase a price that has already moved away.
    if order_side == OrderSide.BUY:
        try:
            rt_price = get_latest_trade_price(symbol)
            slippage  = (rt_price - limit_price) / limit_price
            if slippage > SLIPPAGE_THRESHOLD:
                delta_pct = slippage * 100
                logger.critical(
                    "[SLIPPAGE GUARD] Vetoed entry on %s. "
                    "Signal: %.4f, Real-time: %.4f. Delta too high.",
                    symbol, limit_price, rt_price,
                )
                _append_veto_event(symbol, limit_price, rt_price, delta_pct)
                return None
            logger.info(
                "[%s] Slippage Guard OK — RT=%.4f vs Signal=%.4f (+%.3f%% < %.2f%% threshold)",
                symbol, rt_price, limit_price, slippage * 100, SLIPPAGE_THRESHOLD * 100,
            )
        except Exception as exc:
            logger.warning(
                "[%s] Slippage Guard fetch failed (%s) — allowing order", symbol, exc
            )

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


def get_latest_trade_price(symbol: str) -> float:
    """Fetch the latest real-time SIP trade price for a symbol."""
    req  = StockLatestTradeRequest(symbol_or_symbols=symbol)
    data = data_client.get_stock_latest_trade(req)
    return float(data[symbol].price)


def get_prev_day_high(symbol: str) -> float | None:
    """
    Fetch the previous trading day's high price for take-profit targeting.
    Returns None on error or if fewer than 2 daily bars are available.
    """
    from datetime import timezone
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=7)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        limit=5,
        feed="iex",
    )
    try:
        bars     = data_client.get_stock_bars(request)
        bar_list = bars[symbol]
        if len(bar_list) < 2:
            return None
        return float(bar_list[-2].high)   # second-to-last = previous trading day
    except Exception as e:
        logger.warning("get_prev_day_high failed for %s: %s", symbol, e)
        return None
