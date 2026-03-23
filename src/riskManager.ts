import { PositionSize } from './types';

// ─── Constants ─────────────────────────────────────────────────────────────

const RISK_PER_TRADE_PCT = 0.01;   // 1% of equity per trade
const REWARD_RATIO = 2;            // 1:2 risk-to-reward
const DAILY_LOSS_LIMIT_PCT = 0.03; // 3% daily drawdown kill switch

// ─── Position sizing ───────────────────────────────────────────────────────

/**
 * Calculates the number of shares to buy/sell so that the distance between
 * `entry` and `stopLoss` equals exactly 1% of account equity.
 *
 * @param equity     Current account equity in USD
 * @param entry      Planned entry price
 * @param stopLoss   Planned stop-loss price
 * @returns          { qty, riskAmount }
 */
export function calcPositionSize(
  equity: number,
  entry: number,
  stopLoss: number,
): PositionSize {
  const riskAmount = equity * RISK_PER_TRADE_PCT;
  const stopDistance = Math.abs(entry - stopLoss);

  if (stopDistance === 0) {
    throw new Error('[RiskManager] Stop distance is zero — cannot size position.');
  }

  const qty = Math.floor(riskAmount / stopDistance);

  if (qty < 1) {
    throw new Error(
      `[RiskManager] Position size rounds to 0 shares (equity=${equity}, stopDist=${stopDistance}).`,
    );
  }

  return { qty, riskAmount };
}

// ─── Take-profit calculation ────────────────────────────────────────────────

/**
 * Returns the take-profit price at a 1:2 risk-to-reward ratio.
 */
export function calcTakeProfit(
  entry: number,
  stopLoss: number,
  direction: 'LONG' | 'SHORT',
): number {
  const risk = Math.abs(entry - stopLoss);
  return direction === 'LONG'
    ? entry + risk * REWARD_RATIO
    : entry - risk * REWARD_RATIO;
}

// ─── Daily kill-switch ─────────────────────────────────────────────────────

export class DailyKillSwitch {
  private startEquity: number;
  private halted: boolean = false;

  constructor(startEquity: number) {
    this.startEquity = startEquity;
    console.log(
      `[KillSwitch] Initialized. Start equity: $${startEquity.toFixed(2)}. ` +
      `Daily loss limit: ${DAILY_LOSS_LIMIT_PCT * 100}% ($${(startEquity * DAILY_LOSS_LIMIT_PCT).toFixed(2)})`,
    );
  }

  /**
   * Returns true (and logs) when daily drawdown has hit 3%.
   * Once tripped, remains halted for the rest of the session.
   */
  check(currentEquity: number): boolean {
    if (this.halted) return true;

    const loss = this.startEquity - currentEquity;
    const lossPct = loss / this.startEquity;

    if (lossPct >= DAILY_LOSS_LIMIT_PCT) {
      this.halted = true;
      console.warn(
        `[KillSwitch] TRIGGERED — daily loss ${(lossPct * 100).toFixed(2)}% ` +
        `($${loss.toFixed(2)}). Bot halted for today.`,
      );
    }

    return this.halted;
  }

  isHalted(): boolean {
    return this.halted;
  }
}
