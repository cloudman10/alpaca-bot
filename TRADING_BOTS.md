# Trading Bots Setup

## Overview
Two autonomous trading bots running via Alpaca Markets paper trading accounts.

---

## Bot 1 — Breakout Hunter

- **Account**: Paper Trading - my TradingApp ($149,536.63)
- **Account ID**: PA36MCEQOZKQ
- **Starting Capital**: $150,000
- **Repo**: `cloudman10/trading-bot`
- **Main file**: `main.py` (Python)
- **Run script**: `run_bot.bat` (Windows), `run_bot.sh` (Mac)
- **Folder**: `C:\Users\eriyun\trading-bot` (Windows PC1), `~/TradingApp` (Mac)

### Trading Strategy
- **Breakout Hunter** — enters when price breaks above the 20-day high with momentum confirmation
- Technical indicators: RSI(14), SMA200, ATR(14), ADX(14), 20-day high, volume
- Market regime detection (BULL / NEUTRAL / SIDEWAYS / BEAR) based on SPY vs SMA200
- 15-minute trading cycle

**Entry conditions (all must be met):**
1. Price > 20-day high (breakout)
2. RSI(14) > 60 (momentum strong, not overbought)
3. Volume > 1.5× 20-bar average
4. ADX(14) > 20 (trending market)

**Exit conditions:**
- ATR trailing stop: `highest_high_since_entry − (2.0 × ATR14)`
- Take-profit: 6% above entry
- RSI > 85 (extreme overbought exit)
- Max hold: 72 hours / 3 trading days
- Fallback: 2.5% fixed stop loss

**Position sizing:** 10% of equity per position | Max 3 positions | Kill switch: 2% daily loss

### API Keys
- `ALPACA_API_KEY=PKYFMTR7ZCC6GJDOTYFLLJZZAX`
- `ALPACA_SECRET_KEY=9dc2qxBQ8BpjLiL53ig9RzaAVg4vjKM9d2Z4xJ3G7agx`

### Running Status
- ✅ Windows PC1: Running
- ✅ Mac: Running (uses IEX data feed)

---

## Bot 2 — Gap-UP Momentum Scanner

- **Account**: Paper Trading - Trading App ($100,000)
- **Account ID**: PA3CSLKA75S0
- **Starting Capital**: $100,000
- **Repo**: `cloudman10/alpaca-bot`
- **Language**: Python
- **Main file**: `main.py`
- **Run script**: `bash run_bot.sh` (Mac), `python3 main.py` (all platforms)
- **Folder**: `C:\Users\eriyun\alpaca-bot` (Windows), `~/Desktop/alpaca-bot` (Mac)

### Trading Strategy
- **Gap-UP Momentum** — scans for pre-market gap-up stocks, enters on VWAP pullback reclaim in first 30 min only

**Daily schedule (Eastern time):**

| Time (ET) | Action |
|-----------|--------|
| 9:00 AM | Gap scanner runs — gap > 2%, RVOL > 1.0× |
| 9:20 AM | Dynamic watchlist finalized (top 5 gap-up candidates) |
| 9:30 AM | Entry window opens: VWAP pullback + reclaim signals active |
| 10:00 AM | IEX-delayed bars begin arriving (9:30 bar visible) |
| 10:15 AM | 2nd bar visible — VWAP pullback signals can fire |
| 10:30 AM | Entry window closes — no new positions after this |
| 4:00 PM | Market close; VWAP stop monitoring ends |

**Entry conditions (all must be met, 9:30–10:00 AM ET only):**
1. Previous 15m bar low touched/was at VWAP (pullback occurred)
2. Current 15m bar closes above VWAP (bullish reclaim)
3. Current bar is bullish (close > open)
4. RSI(14) 45–65
5. Volume > 1.5× 20-bar average on entry bar
6. SPY not making new lows

**Exit logic:**
- Take profit: previous day high (if above entry) OR +4% above entry
- Stop loss: VWAP at entry (bracket order static stop)
- VWAP mid-session stop: if price closes below VWAP → exit immediately
- Kill switch: 2% daily loss limit

**Position sizing:** 8% of equity per position | Max 3 positions

### Pre-market Gap Scanner (`scanner.py`)

**Filters:**
- Gap > 2% (gainers only)
- RVOL > 1.0× (relative volume vs 10-day average)
- Capped at top 5 symbols

**Fallback:** If no stocks pass filters, reverts to default watchlist: `SPY, QQQ, AAPL, TSLA, NVDA, AMD, META`

**Universe scanned:** AAPL, TSLA, NVDA, AMD, META, AMZN, MSFT, GOOGL, SPY, QQQ, SMCI, MSTR, COIN, HOOD, PLTR, RIVN, SOFI, UPST, SNAP, RBLX, SHOP, SQ, PYPL, ROKU, UBER, DKNG, PENN, GME, AMC, CVNA, BYND, SPCE (32 symbols)

> **Note on IEX pre-market data:** IEX free tier may not provide bars before 9:30 AM. If pre-market prices are unavailable, the scanner falls back to today's open vs yesterday's close. Gap + RVOL filters still apply.

### API Keys
- `APCA_API_KEY_ID=PKF72BM5QBJL2PKUKM5FPLK5ML`
- `APCA_API_SECRET_KEY=HRWRLmaLqBXUahGZYwcYqijB7pPuKUbx3tjnw56bP61v`
- `APCA_API_BASE_URL=https://paper-api.alpaca.markets`

### Running Status
- ✅ Windows PC2: Running
- ✅ Mac: Running

### Setup Steps (all platforms)
1. `git clone https://github.com/cloudman10/alpaca-bot.git`
2. `cd alpaca-bot`
3. `pip3 install -r requirements.txt`
4. Create `.env` with keys above
5. `bash run_bot.sh` to run (Mac) or `python3 main.py` (Windows)

---

## Machines

| Machine | Bot 1 | Bot 2 |
|---|---|---|
| Windows PC1 (eriyun) | ✅ Running | ✅ Running |
| Windows PC2 (Admin) | ✅ Running | ❌ Not set up |
| MacBook Pro (ericyun) | ✅ Running | ✅ Running |

---

## Optimization History

| Date | Change | Reason | Result |
|------|--------|--------|--------|
| Mar 28 | Converted from TypeScript to Python | Better library support, consistency with Bot 1 | ✅ Done |
| Mar 30 | Fixed TimeFrame bug in `get_15m_bars` | Bot was failing to fetch bars silently | ✅ Fixed |
| Mar 30 | Relaxed engulfing condition, heartbeat 60s→15s | No trades firing | ✅ More responsive |
| Mar 31 | Restored engulfing condition | Backtest showed it's the edge — without it win rate drops to 38% | ✅ Restored |
| Apr 1 | Added pre-market gap scanner + RVOL filter | Fixed watchlist was missing daily movers | ✅ Dynamic watchlist |
| Apr 2 | Added file logging to `logs/bot.log` | Could not debug what happened during market hours | ✅ Done |
| Apr 3 | Lowered RSI from 30 to 25 | TSLA hit RSI 20, AAPL RSI 28 — old threshold too high | ✅ Done |
| Apr 3 | Added volume climax filter (2× avg) | Confirms capitulation before bounce | ✅ Done |
| Apr 3 | Added VWAP take profit | Smarter exit than fixed 1:2 R:R | ✅ Done |
| Apr 3 | Added SPY stabilization filter (3 min) | Prevents buying into still-falling market | ✅ Done |
| Apr 9 | RVOL threshold 2.0×→1.5× | Broadened candidate pool | ✅ Done |
| Apr 10 | RVOL threshold 1.5×→1.0×; fixed docstring | 1.5× left only 1 symbol in watchlist — zero signal opportunities for 12 days | ✅ Done |
| Apr 11 | **Full rebuild: Gap-UP Momentum Scanner** — replaced BB/engulfing with VWAP pullback reclaim, entry only 9:30–10:00 AM ET, 8% equity sizing, VWAP bracket stop, prev_day_high TP, 2% kill switch | Original counter-trend strategy had zero trades in 2 weeks; gap-and-go momentum aligns with bull market conditions | ✅ Done |
| Apr 11 | Scanner: GAP_MIN_PCT 4%→2% | More gap candidates qualify | ✅ Done |
| Apr 11 | Modified: .githooks/pre-commit, | (see commit message) | ✅ Done |
| Apr 12 | Modified: main.py,scanner.py,strategy.py, | (see commit message) | ✅ Done |
| Apr 13 | Modified: main.py, | (see commit message) | ✅ Done |
| Apr 13 | Modified: main.py,strategy.py, | (see commit message) | ✅ Done |
| Apr 16 | SPY new-lows check: 1 tick → 3 consecutive ticks before blocking entry (main.py _spy_is_stable) | Single SPY dip at open blocked HOOD +19%, SNAP +17% on Apr 14-15 — brief open weakness doesn't mean sustained downtrend | ✅ Done |
| Apr 16 | Modified: main.py, | (see commit message) | ✅ Done |
| Apr 16 | Modified: .githooks/pre-commit, | (see commit message) | ✅ Done |
| Apr 17 | Fixed Bot 2 macOS suspend bug — sleep loop now uses pure `_is_active_period()` check instead of counter | Bot missed 25+ hours of sessions silently after Mac suspended overnight | ✅ Done |
| Apr 18 | Extended entry window 10:00 AM → 10:30 AM ET (`_in_entry_window()` in main.py) | IEX feed has 15-min delay: 9:30 bar not visible until 10:00 AM, 9:45 bar not until 10:15 AM — bot had 0 intraday bars during the entire original entry window, zero trades ever possible | ✅ Fixed |
| Apr 18 | Modified: main.py, | (see commit message) | ✅ Done |
| Apr 21 | Added USER_TIMEZONE=Australia/Sydney to .env + check_bots.sh shows Sydney time on every run | User timezone was not tracked anywhere in the project | ✅ Done |
| Apr 22 | Modified: main.py, | (see commit message) | ✅ Done |
| Apr 22 | Added Slippage Guard to Bot 2 (alpaca_service.py + main.py): before each BUY, fetches real-time SIP price via `get_latest_trade_price()`; if `(RT - Delayed) / Delayed > 0.75%` vetoes the order and logs `CRITICAL: Slippage Guard Veto` | IEX bars are 15-min delayed — without the guard the bot chases price that has already moved significantly above the signal | ✅ Done |
| Apr 22 | Directive 3 — Slippage Guard moved inside `place_bracket_order` (right before `submit_order`); exact log format `[SLIPPAGE GUARD] Vetoed entry on {symbol}. Signal: {signal_price}, Real-time: {real_price}. Delta too high.`; veto events persisted to `logs/slippage_vetoes.json`; dashboard `/api/bot2/alerts` endpoint + "Skipped Trades" panel in Bot 2 card (polled every 30s, newest-first) | Guard must be unskippable — living inside the order function guarantees it fires regardless of call site; dashboard panel lets user see tonight's vetoes in real time | ✅ Done |
| Apr 22 | Modified: alpaca_service.py,main.py, | (see commit message) | ✅ Done |
| Apr 22 | **Major architecture upgrade** — Marshal Agent watchdog (120s stale threshold, SIGTERM→SIGKILL, caffeinate -i restarts); heartbeat.json for all 3 bots (60s threads); Bot 2 Slippage Guard inside place_bracket_order (0.75% veto, logs/slippage_vetoes.json, dashboard alert panel); ADX-based regime model on Bot 1 (SUPER_TREND, BULL=ADX>20, SIDEWAYS=5-bar channel) | Self-healing multi-agent system; slippage guard prevents chasing IEX-delayed entries | ✅ Deployed & Verified |
| Apr 24 | Bot 2: Reduced minimum bars from 2→1 in `strategy.py` (Tier 1 VWAP signal) | Effective entry window was only 15 min (10:15–10:30 AM ET) — with 1-bar minimum it doubles to 30 min (10:00–10:30 AM ET). When only 1 bar exists, opening bar acts as both pullback and reclaim reference. Tier 2 ORB keeps 2-bar minimum (needs opening range + breakout bar) | ✅ Done |
| Apr 24 | Modified: strategy.py, | (see commit message) | ✅ Done |
| Apr 24 | Added `strategy_check.sh` (5 pre-session checks): (1) IEX feed age test — fetch SPY 15m bar, confirm delay in range; (2) entry window alignment — confirm IEX bar arrival vs window close (bar_duration + IEX_delay + window_end); (3) regime history — Bot 1 last 5 sessions non-BEAR; (4) VWAP signal backtest — replay yesterday's bars for SPY/NVDA/TSLA through Tier 1 conditions; (5) market condition — current regime from log with BEAR lock-out flag. Integrated into `~/Desktop/CheckBots.command` | Needed pre-session validation that data feed, windows, and signal logic are all functioning before each session | ✅ Done |

---

## Common Issues & Fixes

### 401 Unauthorized
- Check `.env` keys are correct and complete
- Make sure using Paper Trading keys, not Live keys

### SIP Data Error (Mac)
- Add `feed=DataFeed.IEX` to `StockBarsRequest` in `alpaca_service.py`

### Insufficient Bars
- Increase `days` parameter in bar fetch calls

### pip not found (Mac)
- Use `pip3` instead of `pip`
- Add `--break-system-packages` flag

### Module not found
- Run `pip3 install -r requirements.txt --break-system-packages` from the alpaca-bot folder
