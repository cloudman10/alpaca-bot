# Backtest Notes — Bot 2 (Ross Cameron Momentum Strategy)

## Strategy Overview

The live bot detects three simultaneous conditions on 15-minute bars:

| Signal | Condition 1 | Condition 2 | Condition 3 |
|--------|-------------|-------------|-------------|
| LONG   | RSI(14) < 30 | Prev candle low ≤ lower BB(20,2) | Bullish Engulfing |
| SHORT  | RSI(14) > 70 | Prev candle high ≥ upper BB(20,2) | Bearish Engulfing |

Stop-loss: outer Bollinger Band of the trigger candle
Take-profit: 1:2 risk-to-reward
Position sizing: 1% of capital at risk per trade

---

## Backtest Iterations

### Run 1 — Daily bars, original watchlist (SPY, QQQ, AAPL, TSLA, NVDA, AMD, META)

| Metric | Result |
|--------|--------|
| Bars loaded | 250 daily bars |
| Signals | LONG: 0 / SHORT: 1 |
| Trades executed | 1 |
| Total return | -0.42% |
| Win rate | 0.0% |
| Max drawdown | -0.42% |
| Sharpe ratio | -1.30 |

**Finding:** Switching daily bars in was the wrong timeframe. The strategy was built for
15-minute bars. On daily bars the triple condition almost never aligns on large-cap stocks.

---

### Run 2 — 15-minute bars, original watchlist (SPY, QQQ, AAPL, TSLA, NVDA, AMD, META)

| Metric | Result |
|--------|--------|
| Bars loaded | 8,824 per symbol |
| Signals | LONG: 3 / SHORT: 3 |
| Trades executed | 6 |
| Total return | -0.38% |
| Win rate | 50.0% |
| Max drawdown | -1.37% |
| Sharpe ratio | -0.50 |

**Finding:** Correct timeframe, but the watchlist is wrong. Large-cap liquid stocks (SPY,
QQQ, AAPL) rarely push RSI(14) below 30 or above 70 on a 15-minute window — that requires
3.5 hours of sustained directional pressure. Only 6 signals in a full year is far too small
a sample to draw any conclusions.

---

### Run 3 — 15-minute bars, high-beta watchlist (SMCI, MSTR, COIN, HOOD, TSLA, NVDA, AMD)

| Metric | Result |
|--------|--------|
| Bars loaded | 8,371 per symbol |
| Signals | LONG: 2 / SHORT: 7 |
| Trades executed | 9 |
| Total return | -3.16% |
| Win rate | 22.2% |
| Max drawdown | -3.28% |
| Sharpe ratio | -3.72 |

**Finding:** High-beta names produce slightly more signals, but the result is worse.
Still only 9 trades — statistically meaningless. The engulfing requirement on top of
RSI + BB is the binding constraint: all three conditions firing on the same 15-min bar
is an extremely low-probability event on any fixed watchlist.

---

### Run 4 — Simplified proxy (RSI + BB only, no engulfing), high-beta watchlist

Engulfing requirement removed to test whether the two-condition core has any edge.

| Metric | Result |
|--------|--------|
| Bars loaded | 8,371 per symbol |
| Signals | LONG: 322 / SHORT: 298 |
| Trades executed | 281 |
| Total return | -4.21% |
| Win rate | 38.4% |
| Max drawdown | -17.43% |
| Sharpe ratio | -0.40 |

**Finding:** Signal count jumped to 620 (281 executed). Sample size is now meaningful.
The result is negative despite a 1:2 R:R that should produce a positive EV at 38.4% win rate:

```
Theoretical EV = (0.384 × 2R) − (0.616 × 1R) = +0.152R  ← should be profitable
Actual result  = -4.21%                                    ← not profitable
```

The gap is explained by two factors:
1. **Mean-reversion signal on momentum stocks** — when RSI hits 30 and price touches
   the lower BB on SMCI/MSTR/COIN, these names frequently *continue* lower rather than
   bounce. RSI + BB is a mean-reversion tool; this watchlist is momentum-driven.
2. **Fee drag** — 0.1% × 2 sides × 281 trades compounds meaningfully against returns.

---

## Key Conclusions

### Why this strategy is hard to backtest with a static watchlist

Ross Cameron does not trade a fixed list of symbols. His actual workflow is:

1. Pre-market scan for stocks gapping >4% with high relative volume
2. Intraday scan for fresh momentum (unusual volume, news catalyst)
3. Apply the RSI + BB + engulfing setup to *that day's* active movers

A static backtest cannot replicate this. The strategy's edge comes from applying
triple-confirmation signals to stocks that are already in a heightened-volatility state
(news, earnings, short squeeze). On a fixed watchlist, those conditions rarely align.

### The engulfing condition is the edge, not the filter

Removing engulfing (Run 4) increased signals from ~9 to 620 but made performance
*worse*. The engulfing pattern is not just a confirmation — it is the primary mechanism
that filters out "falling knife" entries where RSI and BB conditions are satisfied but
price has not yet shown any reversal. Without it, the strategy buys into continued
momentum moves and gets stopped out repeatedly.

### Verdict

| Approach | Verdict |
|----------|---------|
| Static watchlist backtest | Not representative of how the strategy is used live |
| Daily bars | Wrong timeframe |
| 15-min + fixed large-caps | Too few signals to be meaningful |
| 15-min + high-beta fixed list | Still too few with engulfing; poor without it |
| Live dynamic scanner | How the strategy is actually designed to run |

**Recommendation:** Treat Bot 2 as a live scanning system, not a backtestable
rules-based strategy. Performance should be evaluated from live paper-trading results,
not historical simulation against a fixed watchlist.

---

## Files

| File | Purpose |
|------|---------|
| `backtest.py` | VectorBT backtest (15-min bars, full three-condition strategy, high-beta watchlist) |
| `strategy.py` | Live signal detection logic |
| `indicators.py` | RSI, BB, MACD, engulfing pattern implementations |
| `risk_manager.py` | Position sizing and kill-switch logic |
