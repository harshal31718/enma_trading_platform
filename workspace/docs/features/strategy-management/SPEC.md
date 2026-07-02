# Feature: Strategy Management

**Status:** Implemented
**Last updated:** 2026-07-02 — added the live code-editing feature (previously undocumented — this
doc only covered read-only "View Code"), the `label` param field, and a REST endpoints table;
previous version dated 2026-06-05.

---

## What It Does

Manages Python trading strategy files. Users can list all available strategies, view and **edit**
their source code, and extract their configurable parameters. Users can also create new strategies
from a blank template or clone an existing strategy. Five built-in strategies are seeded on engine
startup.

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
Returns: { paramName: { type, default, min, max, label, description } }
(`categorical`/`boolean` params return `categories` instead of `min`/`max`)

User edits strategy code
        ↓
PUT /api/v1/strategies/:id/code  (Node server)  Req: { code: string }
        ↓
Server proxies to engine PUT /strategies/{name}/code
        ↓
Engine validates syntax via ast.parse, enforces the top-level class name matches the strategy
name, writes the file, and hot-reloads the module
        ↓
Returns: { savedAt: string }  (400 with a validation error if syntax/class-name check fails)

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
- **Param overrides reject, don't clamp (F-015/F-016).** An out-of-range param value raises a
  `ValueError` instead of being silently clamped to `min`/`max`.
- **Code edits are validated before write.** `ast.parse` syntax check + top-level class-name match are
  enforced server-side (engine) before a `PUT /code` write is accepted; the module is hot-reloaded on
  success, no engine restart required.

---

## Built-in Strategies

All 5 are ported to the Narang Black-Box architecture: each defines `forecast()` and binds a
specific `RiskModel` + `PortfolioModel` pair (see `workspace/docs/core/MODELS.md`); none own
`go_long`/`go_short`/`update_position` directly. The seeder also prunes any MongoDB strategy document
whose name isn't in `DEFAULT_STRATEGIES` (e.g. a stale removed-strategy remnant).

| Name | Type | Risk / Portfolio Model | Description |
|------|------|-------------------------|-------------|
| `MicroScalper` | Scalper | `AtrBracketRiskModel` + `RiskBudgetPortfolio` | EMA(9/21) cross + ATR gate; stop-and-reverse via `forecast()` |
| `AdaptiveTrend` | Trend Following | `ChandelierRiskModel` + `RiskBudgetPortfolio` | EMA(200) regime + EMA(21/55) cross + ATR gate + chandelier trailing stop |
| `BestSupertrend` | Trend + MTF | `AtrBracketRiskModel` + `NotionalPortfolio` | HTF Supertrend + SMA(7/20) crossover with a hard ATR stop (replaced the earlier `SignalExitRiskModel`); closes via `_close_at_open` (intentional behavioral change from the prior `liquidate()`); `_safe_sma()` guards against `period > data_length` TA errors |
| `MicroMacroRSIDivergence` | Divergence | `AtrBracketRiskModel` + `RiskBudgetPortfolio` | RSI regular divergence on micro+macro pivot confluence; optional opposite-divergence exit |
| `MultiDivergence` | Divergence Confluence | `AtrBracketRiskModel` + `RiskBudgetPortfolio` | 9-oscillator vote (RSI, MFI, Stochastic, Z-Score, ADX, MACD, OBV, price-action, swing-volume); entry when ≥N sources agree on direction |

---

## REST Endpoints

| Method | Path | Description |
|--------|------|--------------|
| GET | `/api/v1/strategies` | List all strategies |
| POST | `/api/v1/strategies` | Create (blank template) or clone a strategy |
| GET | `/api/v1/strategies/:id/code` | Read source code |
| PUT | `/api/v1/strategies/:id/code` | Edit source code (validated, hot-reloaded) |
| GET | `/api/v1/strategies/:id/params` | Reflect the `PARAMS` schema |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/Strategies.jsx` | Main strategy list page |
| `client/src/features/strategies/StrategyCard.jsx` | Card per strategy with "View Code" button |
| `client/src/features/strategies/CodeViewer.jsx` | Source code modal (read + edit) |
| `client/src/hooks/useStrategies.js` | TanStack Query hooks: `useStrategies()`, `useStrategyCode(id)`, `useUpdateStrategyCode(id)` |
| `server/src/routes/strategy.routes.js` | Route definitions, incl. `PUT /:id/code` |
| `server/src/controllers/strategy.controller.js` | listStrategies, getStrategyCode, updateStrategyCode, getStrategyParams |
| `server/src/models/Strategy.js` | Mongoose model: name (unique), description, filePath |
| `engine/routers/strategies.py` | GET /strategies, GET/PUT /strategies/{name}/code, GET /strategies/{name}/params |
| `engine/core/params.py` | Typed `IntParameter`/`FloatParameter`/etc. classes backing `param_to_dict()` (`label`/`description`/`categories`) |
