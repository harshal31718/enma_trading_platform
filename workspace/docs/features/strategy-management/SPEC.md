# Feature: Strategy Management

**Status:** Implemented
**Last updated:** 2026-07-15 — the in-app code-editing feature documented in the 2026-07-02
revision below was **removed** (Plan 3 Step 3.2, SEC-2: closed the any-user strategy-code RCE
path outright — confirmed dead client-side first, so this was a no-op removal, not a regression).
Strategy code is **view-only** again, same as the pre-2026-07-02 state. Only the removed-endpoint
notes below were updated; the rest of this doc's data-flow diagrams are otherwise unchanged.
Previous revision (2026-07-02) added the live code-editing feature (previously undocumented —
that doc only covered read-only "View Code"), the `label` param field, and a REST endpoints
table; version before that dated 2026-06-05.

---

## What It Does

Manages Python trading strategy files. Users can list all available strategies, **view** their
source code (read-only — in-app editing was removed 2026-07-15, see above), and extract their
configurable parameters. Users can also create new strategies from a blank template or clone an
existing strategy. Five built-in strategies are seeded on engine startup.

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

[REMOVED 2026-07-15 — Plan 3 Step 3.2, SEC-2] User edits strategy code
        ↓
PUT /api/v1/strategies/:id/code did NOT survive — this route, its Node proxy, the engine's
ast.parse validation, and the client editor UI were all removed outright (confirmed dead
client-side before removal). Strategy code is read-only via GET .../code above.

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
- ~~Code edits are validated before write~~ — **removed 2026-07-15 (Plan 3 Step 3.2).** In-app strategy
  code editing (and the `PUT /code` endpoint) no longer exists; code is read-only. See "Data Flow"
  above and `workspace/plan/3_service-to-service-trust.md`'s Shipped summary.
- **Prod's `enma_engine_strategies` named volume can diverge from the image (SYS-3, Plan 8 Step 8.1).**
  `docker-compose.prod.yml` mounts a named volume at `/app/strategies`, overlaying whatever
  strategy files are baked into the engine image at build time. Since `POST /strategies` (create/
  clone, "What It Does" above) writes new files straight into this running directory, the
  volume's actual contents can drift from what's checked into the repo/image: a strategy created
  or cloned via the app persists in the volume across container restarts and image rebuilds
  (redeploying a new image does NOT reset it), but was never committed to `engine/strategies/` in
  git — so the deployed code and the repo's source of truth are not guaranteed to match. There is
  no reconciliation/sync step today; a strategy created this way must be manually copied back into
  the repo if it's meant to be permanent (and the 5 seeded strategies are always safe regardless,
  since `services/strategy_seeder.py` re-creates any missing one idempotently on every startup).

---

## Built-in Strategies

All 6 are ported to the Narang Black-Box architecture: each defines `forecast()` and binds a
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
| `MarginSurge` | Breakout Scalper (Plan 23) | `AtrBracketRiskModel` + `RiskBudgetPortfolio` | Donchian breakout from a BB squeeze + rising ADX + MFI flow + EMA(200) trend — **⚠️ validation FAILED 2026-07-21, not recommended for live/further deployment; see `workspace/docs/strategies/MarginSurge.md`** |

---

## REST Endpoints

| Method | Path | Description |
|--------|------|--------------|
| GET | `/api/v1/strategies` | List all strategies |
| POST | `/api/v1/strategies` | Create (blank template) or clone a strategy |
| GET | `/api/v1/strategies/:id/code` | Read source code (view-only — no PUT route exists, removed 2026-07-15) |
| GET | `/api/v1/strategies/:id/params` | Reflect the `PARAMS` schema |

---

## Related Files

| File | Role |
|------|------|
| `client/src/pages/Strategies.jsx` | Main strategy list page |
| `client/src/features/strategies/StrategyCard.jsx` | Card per strategy with "View Code" button |
| `client/src/features/strategies/CodeViewer.jsx` | Source code modal (read-only — edit mode removed 2026-07-15) |
| `client/src/hooks/useStrategies.js` | TanStack Query hooks: `useStrategies()`, `useStrategyCode(id)` — `useUpdateStrategyCode()` removed 2026-07-15 |
| `server/src/routes/strategy.routes.js` | Route definitions — `PUT /:id/code` removed 2026-07-15 |
| `server/src/controllers/strategy.controller.js` | listStrategies, getStrategyCode, getStrategyParams — `updateStrategyCode` removed 2026-07-15 |
| `server/src/models/Strategy.js` | Mongoose model: name (unique), description, filePath |
| `engine/routers/strategies.py` | GET /strategies, GET /strategies/{name}/code, GET /strategies/{name}/params — `PUT .../code` removed 2026-07-15 |
| `engine/core/params.py` | Typed `IntParameter`/`FloatParameter`/etc. classes backing `param_to_dict()` (`label`/`description`/`categories`) |
