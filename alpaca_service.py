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
