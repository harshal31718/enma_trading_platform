# Feature: Strategy Management

**Status:** Implemented  
**Last updated:** 2026-06-05

---

## What It Does

Manages Python trading strategy files. Users can list all available strategies, view their source code, and extract their configurable parameters. Users can also create new strategies from a blank template or clone an existing strategy. Five built-in strategies are seeded on engine startup.

---

## Data Flow

```
Client loads Strategies page
        ↓
GET /api/v1/strategies  (Node server)
        ↓
Server queries MongoDB strategies collection
        ↓
Returns: id, name, description, filePath, createdAt, updatedAt

User clicks "View Code"
        ↓
GET /api/v1/strategies/:id/code  (Node server)
        ↓
Server proxies to engine GET /strategies/{name}/code
        ↓
Engine reads file from disk: strategies/{name}/__init__.py
        ↓
Returns raw source code string

User opens Backtest form (strategy params)
        ↓
GET /api/v1/strategies/:id/params  (Node server)
        ↓
Server proxies to engine GET /strategies/{name}/params
        ↓
Engine dynamically imports strategy class, reflects PARAMS schema
        ↓
Returns: { paramName: { type, default, min, max, description } }

User creates or clones a strategy
        ↓
POST /api/v1/strategies  (Node server)
        ↓
Server proxies to engine POST /strategies
        ↓
Engine writes a new strategy file and upserts MongoDB metadata
        ↓
Returns: { strategy: Strategy }
```

---

## Service Responsibilities

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| Client | Strategy list UI, code modal, param form rendering | Strategy logic |
| Node server | Route definitions, MongoDB queries for metadata | File reading, param extraction |
| Python engine | File reading from disk, dynamic import + PARAMS reflection | MongoDB strategy list |

---

## Key Invariants

- **Seeding is idempotent.** All 5 current strategies are seeded on engine startup; re-seeding skips existing names. (Three earlier strategies — SimpleEMACross, RSIReversion, DonchianBreakout — were removed 2026-06-14; see `workspace/docs/state/DEPRECATED.md`.)
- **Strategy files live on disk.** MongoDB only stores metadata (name, description, filePath). Source code is read from `strategies/{name}/__init__.py` at request time.
- **PARAMS schema is dynamic.** Each strategy class exposes a `PARAMS` class attribute. The engine reflects this at runtime — no schema is stored in the database.
- **Server never imports strategy code.** All Python reflection happens inside the engine only.

---

## Built-in Strategies

| Name | Type | Description |
|------|------|-------------|
| `MicroScalper` | Scalper | EMA(9/21) cross + ATR gate; stop-and-reverse via `forecast()` |
| `AdaptiveTrend` | Trend Following | EMA(200) regime + EMA(21/55) cross + ATR gate + chandelier trailing stop |
| `BestSupertrend` | Trend + MTF | HTF Supertrend + SMA(7/20) crossover |
| `MicroMacroRSIDivergence` | Divergence | RSI regular divergence on micro+macro pivot confluence |
| `MultiDivergence` | Divergence Confluence | 9-oscillator vote; entry when ≥N sources agree on direction |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/Strategies.jsx` | Main strategy list page |
| `client/src/features/strategies/StrategyCard.jsx` | Card per strategy with "View Code" button |
| `client/src/features/strategies/CodeViewer.jsx` | Read-only source code modal |
| `client/src/hooks/useStrategies.js` | TanStack Query hooks: `useStrategies()`, `useStrategyCode(id)` |
| `server/src/routes/strategy.routes.js` | Route definitions |
| `server/src/controllers/strategy.controller.js` | listStrategies, getStrategyCode, getStrategyParams |
| `server/src/models/Strategy.js` | Mongoose model: name (unique), description, filePath |
| `engine/routers/strategies.py` | GET /strategies, GET /strategies/{name}/code, GET /strategies/{name}/params |
