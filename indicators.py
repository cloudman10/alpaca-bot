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
