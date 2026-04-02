"""
indicators.py — RSI(14), Bollinger Bands(20,2), MACD(12,26,9), Volume Avg(20), VWAP
              + candlestick patterns.
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


def _vwap(df: pd.DataFrame) -> pd.Series:
    """
    Compute VWAP, reset each trading day.
    VWAP = cumsum(typical_price × volume) / cumsum(volume) per day.
    Requires columns: high, low, close, volume, time.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical_price * df["volume"]

    # Group by calendar date so VWAP resets at midnight
    dates = pd.to_datetime(df["time"]).dt.date

    df_temp = df.assign(_tp_vol=tp_vol, _vol=df["volume"], _date=dates)
    cum_tp_vol = df_temp.groupby("_date")["_tp_vol"].cumsum()
    cum_vol    = df_temp.groupby("_date")["_vol"].cumsum()

    return cum_tp_vol / cum_vol


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute RSI(14), Bollinger Bands(20,2), MACD(12,26,9), Volume Avg(20), and VWAP."""
    df = df.copy()

    closes  = df["close"]
    volumes = df["volume"]

    # RSI
    df["RSI_14"] = _rsi(closes, 14)

    # Bollinger Bands
    df["BBU_20_2.0"], df["BBM_20_2.0"], df["BBL_20_2.0"] = _bbands(closes, 20, 2.0)

    # MACD
    df["MACD_12_26_9"], df["MACDs_12_26_9"], df["MACDh_12_26_9"] = _macd(closes, 12, 26, 9)

    # Volume climax filter: 20-bar average volume
    df["volume_avg_20"] = volumes.rolling(window=20).mean()

    # VWAP (resets each trading day)
    df["VWAP"] = _vwap(df)

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
