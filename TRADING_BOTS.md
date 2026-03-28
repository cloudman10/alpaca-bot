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

### Trading Strategy
- Ross Cameron 15-minute momentum strategy
- Watchlist: SPY, QQQ, AAPL, TSLA, NVDA, AMD, META
- RSI-based entry/exit signals
- KillSwitch: 3% daily loss limit ($3,000)
- Heartbeat: 60 seconds

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
