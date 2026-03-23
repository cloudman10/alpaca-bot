import { Bar, TradeSignal, IndicatorResult } from './types';
import { isBullishEngulfing, isBearishEngulfing } from './indicators';
import { calcTakeProfit } from './riskManager';

// ─── Thresholds ─────────────────────────────────────────────────────────────

const RSI_OVERSOLD = 30;
const RSI_OVERBOUGHT = 70;

// ─── Signal detection — Ross Cameron 15-minute Momentum ────────────────────
//
//  LONG setup (all four conditions required):
//    1. Latest RSI < 30
//    2. Candle N-1 touched (low <= lower BB)
//    3. Candle N-1 was bearish, candle N is bullish engulfing candle N-1
//    4. Candle N closes inside the band AND has a higher low than candle N-1
//
//  SHORT setup (mirror conditions):
//    1. Latest RSI > 70
//    2. Candle N-1 pierced (high >= upper BB)
//    3. Candle N-1 was bullish, candle N is bearish engulfing candle N-1
//    4. Candle N closes inside the band AND has a lower high than candle N-1
//
//  Stop-loss: outer Bollinger Band of candle N-1 (lower for long, upper for short)
//  Take-profit: 1:2 risk-to-reward from entry
// ────────────────────────────────────────────────────────────────────────────

export function detectSignal(
  symbol: string,
  bars: Bar[],
  indicators: IndicatorResult,
): TradeSignal | null {
  const { rsi, bb } = indicators;

  // We need at least the two most-recent confirmed candles plus enough history
  // for indicators to have values.
  if (bars.length < 3 || rsi.length < 2 || bb.upper.length < 2) {
    return null;
  }

  // Align indicator arrays (they're shorter than bars because of look-back).
  // The last element of the indicator array corresponds to the last bar.
  const lastRsi = rsi[rsi.length - 1];

  // Bar indices (from the end):  N = most recent closed candle, N-1 = the one before it
  const barN = bars[bars.length - 1];    // most recent candle
  const barN1 = bars[bars.length - 2];   // previous candle

  // Corresponding BB values
  const bbN = {
    upper: bb.upper[bb.upper.length - 1],
    lower: bb.lower[bb.lower.length - 1],
  };
  const bbN1 = {
    upper: bb.upper[bb.upper.length - 2],
    lower: bb.lower[bb.lower.length - 2],
  };

  // ── LONG setup ────────────────────────────────────────────────────────────
  const longCond1 = lastRsi < RSI_OVERSOLD;
  const longCond2 = barN1.low <= bbN1.lower;                      // touched lower band
  const longCond3 = isBullishEngulfing(barN1, barN);              // engulfing pattern
  const longCond4 = barN.close > bbN.lower && barN.low > barN1.low; // closes inside + higher low

  if (longCond1 && longCond2 && longCond3 && longCond4) {
    const entry = barN.close;                     // buy at current close (limit)
    const stopLoss = bbN1.lower;                  // stop at lower band of trigger candle
    const takeProfit = calcTakeProfit(entry, stopLoss, 'LONG');

    return {
      direction: 'LONG',
      symbol,
      entryPrice: entry,
      stopLoss,
      takeProfit,
      reason:
        `LONG | RSI=${lastRsi.toFixed(1)} | ` +
        `LowTouchedBB(${barN1.low.toFixed(2)} <= ${bbN1.lower.toFixed(2)}) | ` +
        `BullishEngulfing | ClosedInsideBand`,
    };
  }

  // ── SHORT setup ───────────────────────────────────────────────────────────
  const shortCond1 = lastRsi > RSI_OVERBOUGHT;
  const shortCond2 = barN1.high >= bbN1.upper;                     // pierced upper band
  const shortCond3 = isBearishEngulfing(barN1, barN);              // engulfing pattern
  const shortCond4 = barN.close < bbN.upper && barN.high < barN1.high; // closes inside + lower high

  if (shortCond1 && shortCond2 && shortCond3 && shortCond4) {
    const entry = barN.close;
    const stopLoss = bbN1.upper;
    const takeProfit = calcTakeProfit(entry, stopLoss, 'SHORT');

    return {
      direction: 'SHORT',
      symbol,
      entryPrice: entry,
      stopLoss,
      takeProfit,
      reason:
        `SHORT | RSI=${lastRsi.toFixed(1)} | ` +
        `HighPiercedBB(${barN1.high.toFixed(2)} >= ${bbN1.upper.toFixed(2)}) | ` +
        `BearishEngulfing | ClosedInsideBand`,
    };
  }

  return null;
}
