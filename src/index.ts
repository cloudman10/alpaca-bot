import 'dotenv/config';
import {
  getAccount,
  get15mBars,
  placeBracketOrder,
  closeAllPositions,
  cancelAllOrders,
  isMarketOpen,
  getOpenPositions,
} from './alpacaService';
import { computeIndicators } from './indicators';
import { detectSignal } from './strategy';
import { calcPositionSize, DailyKillSwitch } from './riskManager';

// ─── Watchlist ─────────────────────────────────────────────────────────────
// Add or remove tickers as desired.  The bot scans all symbols every tick.

const WATCHLIST: string[] = ['SPY', 'QQQ', 'AAPL', 'TSLA', 'NVDA', 'AMD', 'META'];

// ─── Bot configuration ─────────────────────────────────────────────────────

const HEARTBEAT_MS = 60_000; // 60 seconds between scans
const BAR_LIMIT = 50;        // number of 15-min candles to fetch per symbol

// ─── State ─────────────────────────────────────────────────────────────────

let killSwitch: DailyKillSwitch;
let isRunning = false;

// Track symbols where we already have an open bracket order this session
// so we don't double-enter the same trade.
const activeSymbols = new Set<string>();

// ─── Core scan loop ────────────────────────────────────────────────────────

async function scan(): Promise<void> {
  if (isRunning) {
    console.log('[Bot] Previous scan still running — skipping this tick.');
    return;
  }

  isRunning = true;
  const scanStart = new Date().toISOString();

  try {
    // 1. Check market hours
    const marketOpen = await isMarketOpen();
    if (!marketOpen) {
      console.log(`[${scanStart}] Market is closed — skipping scan.`);
      return;
    }

    // 2. Fetch current equity and check kill switch
    const account = await getAccount();
    console.log(
      `[${scanStart}] Equity: $${account.equity.toFixed(2)} | ` +
      `Cash: $${account.cash.toFixed(2)} | ` +
      `Buying Power: $${account.buyingPower.toFixed(2)}`,
    );

    if (killSwitch.check(account.equity)) {
      console.warn('[Bot] Kill switch is ACTIVE — no new trades will be placed.');
      return;
    }

    // 3. Sync active symbols with real open positions
    const openPositions = await getOpenPositions();
    const positionSymbols = new Set(openPositions.map((p) => p.symbol));

    // Remove from activeSymbols if position was closed externally
    for (const sym of activeSymbols) {
      if (!positionSymbols.has(sym)) {
        activeSymbols.delete(sym);
        console.log(`[Bot] Position for ${sym} is closed — slot freed.`);
      }
    }

    // 4. Scan watchlist
    for (const symbol of WATCHLIST) {
      if (activeSymbols.has(symbol)) {
        console.log(`[${symbol}] Already in position — skipping.`);
        continue;
      }

      try {
        const bars = await get15mBars(symbol, BAR_LIMIT);

        if (bars.length < 30) {
          console.log(`[${symbol}] Not enough bars (${bars.length}) — skipping.`);
          continue;
        }

        const indicators = computeIndicators(bars);
        const signal = detectSignal(symbol, bars, indicators);

        if (!signal || signal.direction === 'NONE') {
          console.log(`[${symbol}] No signal.`);
          continue;
        }

        console.log(`\n[${symbol}] SIGNAL DETECTED: ${signal.reason}`);
        console.log(
          `  Entry: $${signal.entryPrice.toFixed(2)} | ` +
          `Stop: $${signal.stopLoss.toFixed(2)} | ` +
          `Target: $${signal.takeProfit.toFixed(2)}`,
        );

        // 5. Size the position
        let positionSize;
        try {
          positionSize = calcPositionSize(account.equity, signal.entryPrice, signal.stopLoss);
        } catch (err) {
          console.error(`[${symbol}] Position sizing failed:`, (err as Error).message);
          continue;
        }

        console.log(
          `  Qty: ${positionSize.qty} shares | ` +
          `Risk: $${positionSize.riskAmount.toFixed(2)}`,
        );

        // 6. Check we have enough buying power
        const orderCost = positionSize.qty * signal.entryPrice;
        if (orderCost > account.buyingPower) {
          console.warn(
            `[${symbol}] Insufficient buying power ` +
            `(need $${orderCost.toFixed(2)}, have $${account.buyingPower.toFixed(2)}) — skipping.`,
          );
          continue;
        }

        // 7. Place bracket order (entry + stop + take-profit as one order)
        const side = signal.direction === 'LONG' ? 'buy' : 'sell';
        const orderId = await placeBracketOrder(
          symbol,
          positionSize.qty,
          side,
          signal.entryPrice,
          signal.stopLoss,
          signal.takeProfit,
        );

        activeSymbols.add(symbol);
        console.log(`[${symbol}] Bracket order placed. Order ID: ${orderId}\n`);

      } catch (symbolErr) {
        // Per-symbol errors should not crash the full scan
        console.error(`[${symbol}] Error during scan:`, symbolErr);
      }
    }

  } catch (err) {
    console.error('[Bot] Unexpected error during scan:', err);
  } finally {
    isRunning = false;
  }
}

// ─── Graceful shutdown ─────────────────────────────────────────────────────

async function shutdown(signal: string): Promise<void> {
  console.log(`\n[Bot] Received ${signal} — shutting down gracefully…`);
  try {
    await cancelAllOrders();
    await closeAllPositions();
  } catch (err) {
    console.error('[Bot] Error during shutdown:', err);
  }
  process.exit(0);
}

process.on('SIGINT', () => void shutdown('SIGINT'));
process.on('SIGTERM', () => void shutdown('SIGTERM'));

// ─── Entry point ───────────────────────────────────────────────────────────

async function main(): Promise<void> {
  console.log('═══════════════════════════════════════════════════');
  console.log('   Alpaca Trading Bot — Ross Cameron 15m Momentum  ');
  console.log('═══════════════════════════════════════════════════');
  console.log(`Started at: ${new Date().toISOString()}`);
  console.log(`Watchlist:  ${WATCHLIST.join(', ')}`);
  console.log(`Heartbeat:  ${HEARTBEAT_MS / 1000}s`);
  console.log('───────────────────────────────────────────────────');

  // Fetch starting balance and initialize kill switch
  const account = await getAccount();
  console.log(`Starting equity: $${account.equity.toFixed(2)}`);
  console.log(`Cash:            $${account.cash.toFixed(2)}`);
  console.log(`Buying Power:    $${account.buyingPower.toFixed(2)}`);
  console.log('───────────────────────────────────────────────────\n');

  killSwitch = new DailyKillSwitch(account.equity);

  // Run immediately, then on an interval
  await scan();
  setInterval(() => void scan(), HEARTBEAT_MS);
}

main().catch((err) => {
  console.error('[Bot] Fatal error during startup:', err);
  process.exit(1);
});
