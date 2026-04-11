"""
risk_manager.py — Position sizing (1% rule), take-profit calc, and daily kill switch.
"""

import logging

logger = logging.getLogger(__name__)

RISK_PER_TRADE_PCT = 0.01   # 1% of equity per trade
REWARD_RATIO = 2             # 1:2 risk-to-reward
DAILY_LOSS_LIMIT_PCT = 0.02  # 2% daily drawdown kill switch (tightened from 3%)
MAX_SHARES = 2000            # hard cap on position size


def calc_position_size(equity: float, entry: float, stop_loss: float) -> dict:
    """
    Calculate shares so that distance between entry and stop_loss equals 1% of equity.
    Capped at MAX_SHARES.
    Returns: {"qty": int, "risk_amount": float}
    """
    risk_amount = equity * RISK_PER_TRADE_PCT
    stop_distance = abs(entry - stop_loss)

    if stop_distance == 0:
        raise ValueError("Stop distance is zero — cannot size position.")

    qty = int(risk_amount / stop_distance)
    qty = min(qty, MAX_SHARES)

    if qty < 1:
        raise ValueError(
            f"Position size rounds to 0 shares (equity={equity}, stop_dist={stop_distance})."
        )

    return {"qty": qty, "risk_amount": risk_amount}


def calc_take_profit(
    entry: float,
    stop_loss: float,
    direction: str,
    vwap: float | None = None,
) -> float:
    """
    Returns take-profit price.
    Uses VWAP if it is valid for the trade direction, otherwise falls back to 1:2 R:R.
      LONG:  valid if VWAP > entry
      SHORT: valid if VWAP < entry
    """
    if vwap is not None:
        if direction == "LONG" and vwap > entry:
            return vwap
        if direction == "SHORT" and vwap < entry:
            return vwap

    risk = abs(entry - stop_loss)
    if direction == "LONG":
        return entry + risk * REWARD_RATIO
    else:
        return entry - risk * REWARD_RATIO


class DailyKillSwitch:
    """Trips when daily drawdown hits 3%. Once tripped, stays halted for the session."""

    def __init__(self, start_equity: float):
        self.start_equity = start_equity
        self.halted = False
        limit = start_equity * DAILY_LOSS_LIMIT_PCT
        logger.info(
            f"[KillSwitch] Initialized. Start equity: ${start_equity:.2f}. "
            f"Daily loss limit: {DAILY_LOSS_LIMIT_PCT * 100}% (${limit:.2f})"
        )

    def check(self, current_equity: float) -> bool:
        if self.halted:
            return True

        loss = self.start_equity - current_equity
        loss_pct = loss / self.start_equity

        if loss_pct >= DAILY_LOSS_LIMIT_PCT:
            self.halted = True
            logger.warning(
                f"[KillSwitch] TRIGGERED — daily loss {loss_pct * 100:.2f}% "
                f"(${loss:.2f}). Bot halted for today."
            )

        return self.halted

    def is_halted(self) -> bool:
        return self.halted
