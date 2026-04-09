# Trading Bots Setup

## Overview
Two autonomous trading bots running via Alpaca Markets paper trading accounts.

---

## Bot 1 — Trading Strategy Engine

- **Account**: Paper Trading - my TradingApp ($149,536.63)
- **Account ID**: PA36MCEQOZKQ
- **Starting Capital**: $150,000
- **Repo**: `cloudman10/trading-bot`
- **Main file**: `main.py` (Python)
- **Run script**: `run_bot.bat` (Windows), `run_bot.sh` (Mac)
- **Folder**: `C:\Users\eriyun\trading-bot` (Windows PC1), `~/TradingApp` (Mac)

### Trading Strategy
- Technical indicators: RSI, SMA20, SMA50, SMA200, MACD, momentum, volume
- Market regime detection (BULL / BEAR / SIDEWAYS) based on SPY vs SMA200
- BEAR market: no new trades, only manage existing positions
- SIDEWAYS market: only strongest signals
- BULL market: full trading activity
- 15-minute trading cycle

### API Keys
- `ALPACA_API_KEY=PKYFMTR7ZCC6GJDOTYFLLJZZAX`
- `ALPACA_SECRET_KEY=9dc2qxBQ8BpjLiL53ig9RzaAVg4vjKM9d2Z4xJ3G7agx`

### Running Status
- ✅ Windows PC1: Running
- ✅ Mac: Running (uses IEX data feed, SMA_LONG_PERIOD reduced to 170)

### Mac-specific fixes applied
- `market_data_agent.py`: added `feed=DataFeed.IEX` to avoid SIP subscription error
- `core/config.py`: `SMA_LONG_PERIOD` changed from 200 to 170 (IEX data limitation)
- Dependencies installed with `--break-system-packages`

---

## Bot 2 — Ross Cameron 15m Momentum

- **Account**: Paper Trading - Trading App ($100,000)
- **Account ID**: PA3CSLKA75S0
- **Starting Capital**: $100,000
- **Repo**: `cloudman10/alpaca-bot`
- **Language**: Python
- **Main file**: `main.py`
- **Run script**: `python main.py` (all platforms)
- **Folder**: `C:\Users\eriyun\alpaca-bot` (Windows), `~/Desktop/alpaca-bot` (Mac)

### Current Entry Logic (as of Apr 3, 2026)

**LONG entry — ALL must be true:**
1. RSI < 25 (deeply oversold)
2. Price touched lower Bollinger Band
3. Bullish Engulfing candle pattern
4. Volume > 2× 20-bar average (volume climax)
5. SPY not making new lows in last 3 minutes

**SHORT entry — ALL must be true:**
1. RSI > 70 (overbought)
2. Price pierced upper Bollinger Band
3. Bearish Engulfing candle pattern
4. Volume > 2× 20-bar average

**Exit logic:**
- Take profit: VWAP level (falls back to 1:2 R:R if VWAP not valid)
- Stop loss: outer Bollinger Band
- Daily kill switch: 3% loss

**Other:**
- **Dynamic watchlist** — rebuilt every morning via pre-market gap scanner (see below)
- Heartbeat: 15 seconds

### Pre-market Gap Scanner (`scanner.py`)

Runs automatically at **9:00 AM ET** every trading day. Replaces the fixed watchlist with high-momentum candidates.

**Daily timeline:**

| Time (ET) | Action |
|-----------|--------|
| 9:00 AM | Scan ~35 volatile symbols; calculate gap % vs previous close |
| 9:10 AM | Calculate RVOL for gap candidates |
| 9:20 AM | Finalize dynamic watchlist (top 5 by gap %) |
| 9:30 AM | RSI/BB/Engulfing entry logic activates |

**Filters:**
- Gap > 4% (gainers only)
- RVOL > 2× (relative volume vs 10-day average)
- Capped at top 5 symbols

**Fallback:** If no stocks pass both filters, reverts to default watchlist: `SPY, QQQ, AAPL, TSLA, NVDA, AMD, META`

**Universe scanned:** AAPL, TSLA, NVDA, AMD, META, AMZN, MSFT, GOOGL, SPY, QQQ, SMCI, MSTR, COIN, HOOD, PLTR, RIVN, SOFI, UPST, SNAP, RBLX, SHOP, SQ, PYPL, ROKU, UBER, DKNG, PENN, GME, AMC, CVNA, BYND, SPCE (32 symbols)

> **Note on IEX pre-market data:** IEX free tier may not provide bars before 9:30 AM. If pre-market prices are unavailable, the scanner falls back to today's open vs yesterday's close (calculated at 9:30 AM first bar). Gap + RVOL filters still apply.

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
5. `python3 main.py` to run

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
| Apr 4 | Fixed BEAR regime bug root cause identified | SPY RSI 29.8 caused no regime to match, falling to BEAR default | ✅ Already fixed in Apr 1 merge |
| Apr 4 | Added detailed regime logging | Shows exact % diff and threshold each cycle | ✅ Done |
| Apr 4 | Modified: requirements.txt, | (see commit message) | ✅ Done |
| Apr 4 | Modified: .githooks/pre-commit,CLAUDE.md,setup.sh, | (see commit message) | ✅ Done |
| Apr 9 | Modified: scanner.py, | (see commit message) | ✅ Done |
| Apr 9 | Modified: main.py,run_bot.sh, | (see commit message) | ✅ Done |
| Apr 10 | RVOL threshold 1.5×→1.0×; fixed docstring to match (was still showing 2.0×) | 1.5× left only 1 symbol in watchlist all session — zero signal opportunities for 12 days | ✅ Done |
| Apr 10 | Modified: scanner.py, | (see commit message) | ✅ Done |

---

## Common Issues & Fixes

### 401 Unauthorized
- Check `.env` keys are correct and complete
- Make sure using Paper Trading keys, not Live keys

### SIP Data Error (Mac)
- Add `feed=DataFeed.IEX` to `StockBarsRequest` in `market_data_agent.py`

### Insufficient Bars
- Increase `days` parameter in `get_bars()` or reduce `SMA_LONG_PERIOD` in `config.py`

### pip not found (Mac)
- Use `pip3` instead of `pip`
- Add `--break-system-packages` flag

### Module not found
- Run `pip3 install -r requirements.txt --break-system-packages` from the TradingApp folder
