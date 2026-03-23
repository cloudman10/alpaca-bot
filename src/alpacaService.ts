import Alpaca from '@alpacahq/alpaca-trade-api';
import { Bar, AccountInfo } from './types';

// ─── Client singleton ──────────────────────────────────────────────────────

const alpaca = new Alpaca({
  keyId: process.env.ALPACA_API_KEY_ID!,
  secretKey: process.env.ALPACA_API_SECRET_KEY!,
  paper: process.env.ALPACA_PAPER === 'true',
});

// ─── Account ───────────────────────────────────────────────────────────────

export async function getAccount(): Promise<AccountInfo> {
  const acct = await alpaca.getAccount();
  return {
    equity: parseFloat(acct.equity),
    cash: parseFloat(acct.cash),
    buyingPower: parseFloat(acct.buying_power),
  };
}

// ─── Market data ───────────────────────────────────────────────────────────

/**
 * Fetch the last `limit` 15-minute bars for `symbol` using the v2 data API.
 */
export async function get15mBars(symbol: string, limit: number = 50): Promise<Bar[]> {
  const bars: Bar[] = [];

  const response = alpaca.getBarsV2(symbol, {
    timeframe: '15Min',
    limit,
    feed: 'iex',          // IEX feed works on paper accounts without a data subscription
  });

  for await (const bar of response) {
    bars.push({
      time: bar.Timestamp as string,
      open: bar.OpenPrice as number,
      high: bar.HighPrice as number,
      low: bar.LowPrice as number,
      close: bar.ClosePrice as number,
      volume: bar.Volume as number,
    });
  }

  return bars;
}

// ─── Order placement ───────────────────────────────────────────────────────

export interface LimitOrderParams {
  symbol: string;
  qty: number;
  side: 'buy' | 'sell';
  limitPrice: number;
  clientOrderId?: string;
}

export async function placeLimitOrder(params: LimitOrderParams): Promise<string> {
  const order = await alpaca.createOrder({
    symbol: params.symbol,
    qty: params.qty,
    side: params.side,
    type: 'limit',
    time_in_force: 'day',
    limit_price: params.limitPrice.toFixed(2),
    client_order_id: params.clientOrderId,
  });
  return order.id as string;
}

/**
 * Place a bracket order (entry + stop + take-profit) as limit orders.
 * Alpaca's bracket order attaches stop-loss and take-profit legs automatically.
 */
export async function placeBracketOrder(
  symbol: string,
  qty: number,
  side: 'buy' | 'sell',
  limitPrice: number,
  stopLoss: number,
  takeProfit: number,
): Promise<string> {
  const order = await alpaca.createOrder({
    symbol,
    qty,
    side,
    type: 'limit',
    time_in_force: 'gtc',
    limit_price: limitPrice.toFixed(2),
    order_class: 'bracket',
    stop_loss: { stop_price: stopLoss.toFixed(2) },
    take_profit: { limit_price: takeProfit.toFixed(2) },
  });
  return order.id as string;
}

// ─── Position management ───────────────────────────────────────────────────

export async function getOpenPositions(): Promise<Array<{ symbol: string; qty: number; side: string }>> {
  const positions = await alpaca.getPositions();
  return positions.map((p: Record<string, unknown>) => ({
    symbol: p.symbol as string,
    qty: Math.abs(parseFloat(p.qty as string)),
    side: p.side as string,
  }));
}

export async function closeAllPositions(): Promise<void> {
  const positions = await alpaca.getPositions();
  if (positions.length === 0) return;

  console.log(`[AlpacaService] Closing ${positions.length} open position(s)…`);
  for (const pos of positions) {
    try {
      await alpaca.closePosition(pos.symbol as string);
      console.log(`[AlpacaService] Closed position: ${pos.symbol as string}`);
    } catch (err) {
      console.error(`[AlpacaService] Failed to close ${pos.symbol as string}:`, err);
    }
  }
}

export async function cancelAllOrders(): Promise<void> {
  await alpaca.cancelAllOrders();
  console.log('[AlpacaService] All open orders cancelled.');
}

// ─── Market hours ──────────────────────────────────────────────────────────

export async function isMarketOpen(): Promise<boolean> {
  const clock = await alpaca.getClock();
  return clock.is_open as boolean;
}
