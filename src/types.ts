// ─── Shared types ──────────────────────────────────────────────────────────

export interface Bar {
  time: string;       // ISO timestamp
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IndicatorResult {
  rsi: number[];
  bb: {
    upper: number[];
    middle: number[];
    lower: number[];
  };
  macd: {
    MACD: number[];
    signal: number[];
    histogram: number[];
  };
}

export type SignalDirection = 'LONG' | 'SHORT' | 'NONE';

export interface TradeSignal {
  direction: SignalDirection;
  symbol: string;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  reason: string;
}

export interface PositionSize {
  qty: number;
  riskAmount: number;
}

export interface AccountInfo {
  equity: number;
  cash: number;
  buyingPower: number;
}
