# Enma — Algorithmic Trading Platform

A full-stack platform for writing, backtesting, and running automated trading strategies. Write strategies in Python, backtest against historical Binance data, and run live/paper trades via a React dashboard.

Inspired by [Jesse.trade](https://docs.jesse.trade).

---

## Features

- **Strategy Editor** — Write Python strategies using a familiar API (compatible with Jesse)
- **Backtesting Engine** — Fast sequential candle replay with realistic fill simulation
- **Candle Importer** — Fetch OHLCV data from Binance (spot and futures)
- **Live Trading** — Run live or paper trading bots with real-time position monitoring
- **Dashboard** — Real-time charts, trade history, performance metrics
- **Hyperparameter Optimization** — Find optimal strategy parameters (Phase 6)

---

## Tech Stack

### Frontend
- **React 18** — UI framework
- **Vite 5** — Build tool with HMR
- **TailwindCSS 3** — Styling
- **Recharts 2** — Charts
- **Zustand 4** — Global state (UI)
- **TanStack Query 5** — Server state (caching, sync)
- **Socket.IO client** — Real-time updates

### Backend
- **Node.js 20** — API gateway
- **Express** — HTTP server
- **BullMQ** — Job queue
- **Socket.IO** — WebSocket transport
- **MongoDB** — Application data
- **TimescaleDB** — Time-series candle data
- **Redis** — Cache, queue backend, pub/sub

### Strategy Engine
- **Python 3.11** — Language
- **FastAPI** — Web framework
- **TA-Lib** — Technical indicators
- **ccxt** — Exchange connectivity
- **asyncpg** — Async PostgreSQL driver
- **motor** — Async MongoDB driver

---

## Quick Start

### Prerequisites

- Docker & Docker Compose installed
- Git
- Python 3.11+ (for local development, not required for Docker)

### Setup (Docker — Recommended)

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd enma_trading_platform
   ```

2. **Start all services**
   ```bash
   docker-compose up
   ```

   The compose file orchestrates:
   - `client` (React) on http://localhost:5173
   - `server` (Express API) on http://localhost:5000
   - `engine` (FastAPI) on http://localhost:8000
   - `mongo` on localhost:27017
   - `redis` on localhost:6379
   - `timescaledb` on localhost:5432

3. **Open the dashboard**
   - Navigate to http://localhost:5173
   - Sign up / log in

### Setup (Local development without Docker)

Not recommended. TA-Lib requires compilation and is included in the Docker image.

If you insist:
1. Install Python dependencies in `engine/` and `server/`
2. Install Node dependencies in `client/` and `server/`
3. Set up `.env` files in each directory (see `.env.example`)
4. Start MongoDB, Redis, TimescaleDB separately
5. Run `npm start` in `client/` and `server/`, `uvicorn` in `engine/`

---

## Project Structure

```
enma_trading_platform/
├── client/              ← React frontend (Vite)
├── server/              ← Node.js API gateway (Express)
├── engine/              ← Python strategy engine (FastAPI)
├── docker/              ← Dockerfile configs
├── docs/                ← Architecture, decisions, API specs
├── docker-compose.yml   ← Local dev orchestration
├── CLAUDE.md            ← Development guidelines (Claude Code)
└── README.md            ← This file
```

See **CLAUDE.md** for detailed development guidelines for Claude Code.

---

## Development Workflow

### Running the project

```bash
# Start all services (recommended)
docker-compose up

# Start one service
docker-compose up client

# Stop all services
docker-compose down

# Stop and delete data volumes (reset)
docker-compose down -v
```

### Hot reload

All services support hot reload during development:
- **client:** Vite HMR (automatic)
- **server:** nodemon (auto-restarts on code changes)
- **engine:** uvicorn --reload (auto-restarts on code changes)

### Database access

- **MongoDB:** `mongodb://localhost:27017/enma` (in-container) or via MongoDB Compass
- **TimescaleDB:** `postgres://postgres:postgres@localhost:5432/enma` via psql or GUI tools
- **Redis:** `redis://localhost:6379` via redis-cli

---

## API Routes

All routes prefixed `/api/v1/`

### Authentication
- `POST /auth/register` — Create account
- `POST /auth/login` — Log in
- `POST /auth/refresh` — Refresh JWT token

### Strategies
- `GET /strategies` — List all strategies
- `GET /strategies/:id` — Get strategy metadata
- `GET /strategies/:id/code` — Get strategy source code

### Candle Import
- `GET /candles/symbols` — Get available symbols
- `POST /candles/import` — Submit candle import job
- `GET /candles/import/:jobId` — Get import job status

### Backtesting
- `POST /backtest` — Submit backtest job
- `GET /backtest/:id` — Get backtest results
- `POST /backtest/:id/cancel` — Cancel running backtest

### Live Trading
- `POST /live/start` — Start a live/paper bot
- `POST /live/stop` — Stop a bot
- `GET /live/status` — Get bot status and positions

See **docs/API_CONTRACTS.md** for full endpoint specs.

---

## Strategy Writing

Every strategy extends `BaseStrategy`:

```python
from engine.core.strategy import BaseStrategy
import engine.indicators as ta

class MyStrategy(BaseStrategy):
    def should_long(self) -> bool:
        # Return True to open a long position
        sma = ta.sma(self.candles, period=20)
        return self.close > sma[-1]
    
    def should_short(self) -> bool:
        return False  # Not shorting in this example
    
    def go_long(self):
        # Define entry, stop-loss, take-profit for long
        self.buy = [self.balance * 0.9, self.close]  # Qty, price
        self.stop_loss = [self.balance * 0.9, self.close * 0.95]
        self.take_profit = [self.balance * 0.9, self.close * 1.05]
    
    def go_short(self):
        pass  # Not implemented
    
    def should_cancel_entry(self) -> bool:
        return False
```

**Available properties:**
- `self.candles` — OHLCV array
- `self.price`, `self.close`, `self.open`, `self.high`, `self.low`, `self.volume`
- `self.position` — Current position object
- `self.balance` — Current wallet balance
- `self.is_long`, `self.is_short`, `self.is_open`, `self.is_close`
- `self.buy`, `self.sell`, `self.stop_loss`, `self.take_profit`
- `self.liquidate()` — Close position at market
- `self.index` — Current candle index
- `self.vars` — Custom variables dict

**Available indicators** (via `engine.indicators`):
- Trend: `sma()`, `ema()`, `macd()`
- Momentum: `rsi()`, `stochastic()`
- Volatility: `bollinger_bands()`, `atr()`
- Volume: `obv()`, `vwap()`

See **docs/ARCHITECTURE.md** for the full strategy interface.

---

## Documentation

- **CLAUDE.md** — Development rules for Claude Code (includes all three services)
  - **client/CLAUDE.md** — React-specific rules
  - **server/CLAUDE.md** — Node.js-specific rules
  - **engine/CLAUDE.md** — Python-specific rules
- **docs/ARCHITECTURE.md** — System design, data ownership, service descriptions
- **docs/DECISIONS.md** — Append-only log of architectural decisions
- **docs/API_CONTRACTS.md** — REST endpoint specifications

---

## Build Phases

| Phase | Status | Features |
|---|---|---|
| 1 | 🔄 In Progress | Project scaffold, Docker, auth, dashboard shell |
| 2 | 🔲 Not started | Candle importer |
| 3 | 🔲 Not started | Strategy system (CRUD + editor) |
| 4 | 🔲 Not started | Backtesting (run + results + charts) |
| 5 | 🔲 Not started | Live / paper trading |
| 6 | 🔲 Not started | Optimization + Monte Carlo |

---

## Deployment

Deployment targets (after Phase 1 completion):

| Service | Target | Notes |
|---|---|---|
| Frontend | Vercel | Free tier, auto-deploy from main |
| Backend | Oracle Cloud Free VM | Always-on, Docker |
| Engine | Oracle Cloud Free VM | Same VM as backend |
| MongoDB | MongoDB Atlas Free | 512MB free tier |
| Redis | Upstash Free | 10k requests/day free |

---

## Security

- API keys stored encrypted in MongoDB (AES-256)
- JWT tokens expire in 7 days; refresh tokens in 30 days
- Binance keys never sent to frontend
- Rate limiting on all routes
- CORS restricted to frontend origin

---

## Troubleshooting

### Port already in use
```bash
# Kill process on port (e.g., 5173)
lsof -i :5173 | grep LISTEN | awk '{print $2}' | xargs kill -9
```

### Docker volumes not persisting
```bash
# Check volume status
docker volume ls | grep enma

# Remove volumes (WARNING: deletes data)
docker-compose down -v
```

### TA-Lib build fails
TA-Lib must be built inside Docker. Do not try to install it on the host machine. The engine Dockerfile handles compilation automatically.

### Hot reload not working
- **Client:** Check that Vite's HMR is enabled in `client/vite.config.js`
- **Server/Engine:** Ensure volumes are mounted correctly in `docker-compose.yml`

---

## Contributing

All development work is coordinated via CLAUDE.md. See [CLAUDE.md](./CLAUDE.md) for guidelines on:
- Code style and conventions
- Technology stack and version pinning
- What packages and patterns are approved

When making architectural decisions, append an entry to [docs/DECISIONS.md](./docs/DECISIONS.md).

---

## License

Proprietary. See LICENSE file (if present).

---

## References

- [Jesse.trade documentation](https://docs.jesse.trade) — Strategy API reference
- [TA-Lib documentation](https://mrjbq7.github.io/ta-lib/) — Indicator library
- [ccxt documentation](https://docs.ccxt.com/) — Exchange connectivity
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [TanStack Query documentation](https://tanstack.com/query/latest)
