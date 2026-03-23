import {
  RSI,
  BollingerBands,
  MACD,
} from 'technicalindicators';
import { Bar, IndicatorResult } from './types';

// ─── RSI (14) ──────────────────────────────────────────────────────────────

export function computeRSI(bars: Bar[], period: number = 14): number[] {
  const closes = bars.map((b) => b.close);
  return RSI.calculate({ values: closes, period });
}

// ─── Bollinger Bands (20, 2) ────────────────────────────────────────────────

export function computeBB(
  bars: Bar[],
  period: number = 20,
  stdDev: number = 2,
): { upper: number[]; middle: number[]; lower: number[] } {
  const closes = bars.map((b) => b.close);
  const results = BollingerBands.calculate({ values: closes, period, stdDev });
  return {
    upper: results.map((r) => r.upper),
    middle: results.map((r) => r.middle),
    lower: results.map((r) => r.lower),
  };
}

// ─── MACD (12, 26, 9) ──────────────────────────────────────────────────────

export function computeMACD(
  bars: Bar[],
  fastPeriod: number = 12,
  slowPeriod: number = 26,
  signalPeriod: number = 9,
): { MACD: number[]; signal: number[]; histogram: number[] } {
  const closes = bars.map((b) => b.close);
  const results = MACD.calculate({
    values: closes,
    fastPeriod,
    slowPeriod,
    signalPeriod,
    SimpleMAOscillator: false,
    SimpleMASignal: false,
  });
  return {
    MACD: results.map((r) => r.MACD ?? 0),
    signal: results.map((r) => r.signal ?? 0),
    histogram: results.map((r) => r.histogram ?? 0),
  };
}

// ─── All indicators at once ─────────────────────────────────────────────────

export function computeIndicators(bars: Bar[]): IndicatorResult {
  return {
    rsi: computeRSI(bars),
    bb: computeBB(bars),
    macd: computeMACD(bars),
  };
}

// ─── Candle pattern helpers ─────────────────────────────────────────────────

/**
 * Returns true when `curr` is a bullish engulfing candle vs `prev`.
 * Bullish engulfing: prev is bearish, curr is bullish, curr body wraps prev body.
 */
export function isBullishEngulfing(prev: Bar, curr: Bar): boolean {
  const prevBearish = prev.close < prev.open;
  const currBullish = curr.close > curr.open;
  const wraps = curr.open <= prev.close && curr.close >= prev.open;
  return prevBearish && currBullish && wraps;
}

/**
 * Returns true when `curr` is a bearish engulfing candle vs `prev`.
 * Bearish engulfing: prev is bullish, curr is bearish, curr body wraps prev body.
 */
export function isBearishEngulfing(prev: Bar, curr: Bar): boolean {
  const prevBullish = prev.close > prev.open;
  const currBearish = curr.close < curr.open;
  const wraps = curr.open >= prev.close && curr.close <= prev.open;
  return prevBullish && currBearish && wraps;
}
