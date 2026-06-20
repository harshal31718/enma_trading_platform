# Deep Review & Optimization Task

**Objective:** Comprehensive review of Enma platform — question every architectural decision, research better alternatives, document findings in `plan/changes/` with granular .md files.

---

## Scope

Analyze **every layer** (client/server/engine) and **every workflow** (backtest/live trading/candle management/strategy execution) against:
- Current implementation (code + docs)
- Industry best practices (2026)
- Web research on alternatives
- Correctness & performance gaps

---

## Required Output Files in `plan/changes/`

| File | Purpose |
|------|---------|
| `01-architecture-review.md` | Layer boundaries, data ownership, 3-DB model, communication patterns |
| `02-backtest-pipeline-deep-dive.md` | Step-by-step backtest flow, correctness, performance, vectorization opportunities |
| `03-live-trading-review.md` | WebSocket handling, order execution, position sync, risk gates, reconnection logic |
| `04-indicator-architecture.md` | Pluggable provider design, TA-Lib vs pandas-ta, caching, pre-computation |
| `05-five-model-pipeline.md` | Alpha→Risk→Portfolio→Cost→Execution — contracts, correctness, extensibility |
| `06-margin-liquidation-math.md` | Isolated margin model, MMR tables, liquidation price calc, Binance parity |
| `07-candle-management.md` | Auto-fetch, TimescaleDB schema, idempotency, warmup, exchange separation |
| `08-risk-model-deep-dive.md` | Risk pct, RRR, drawdown breaker, liq buffer, sizing helpers, can_trade() |
| `09-strategy-contract.md` | BaseStrategy interface, PARAMS, flip_position, forecast(), model injection |
| `10-api-contracts-review.md` | REST/Socket.IO contracts, response formats, versioning, error codes |
| `11-security-audit.md` | API key storage, rate limits, auth gaps, CORS, input validation |
| `12-performance-baselines.md` | Current metrics, bottlenecks, target improvements, measurement plan |
| `13-web-research-alternatives.md` | Industry alternatives for each component (vectorbt, backtrader, ccxt, etc.) |
| `14-decision-registry.md` | Every DECISIONS.md entry questioned — keep/change/remove with rationale |
| `15-implementation-roadmap.md` | Prioritized, sequenced plan with effort/impact/risk |

---

## Research Methodology

For **each** component:
1. Read current implementation + docs
2. **Question the decision**: Why this way? What alternatives exist?
3. **Web search**: "best practice X 202026", "alternative to Y trading platform", "performance Z backtesting"
4. Document: current → alternatives → recommendation → migration path
5. Flag: correctness bugs, performance anti-patterns, architectural debt

---

## Key Questions to Answer

### Backtest Pipeline
- Is per-candle loop with `evaluate()` correct? Any lookahead bias?
- Why recompute indicators every candle instead of pre-computing sequential series?
- Is equity curve downsampling (linspace) statistically sound?
- Are metrics (Sharpe, Sortino) calculated correctly for irregular timeframes?
- Does `ensure_candles_available()` guarantee no gaps?
- Is atomic flip logic correct for both backtest and live?

### Live Trading
- Does WS reconnection handle all edge cases (partial fills, missed candles)?
- Is position sync on startup complete? What about orphaned SL/TP orders?
- Are risk gates (drawdown breaker, cost hurdle) active in live?
- Does `flip_position()` degrade correctly on Binance errors?
- Is fee_rate from Exchange Settings correctly injected?

### Architecture
- Is 3-DB split (Mongo/Timescale/Redis) optimal? Any cross-DB transaction needs?
- Should server ever write backtestTrades? (Currently engine-only — correct?)
- Is Binance isolation (engine-only) enforced everywhere?
- Are there any `user_id` leaks? (Single-user constraint)

### Indicators
- Does pluggable backend actually work? Pandas-ta fallback tested?
- MicroScalper's direct `import talib` — breaks abstraction. Fix?
- Pivot detection on arbitrary series — correct for divergence strategies?

### Five-Model Pipeline
- Is `evaluate()` called at right points in both engines?
- Cost model `is_worth_it()` — does it prevent negative-edge trades?
- Portfolio model `allocate()` — equal split only? Risk-parity possible?
- Execution model — backtest vs live parity?

---

## Acceptance Criteria

- [ ] All 15 output files created with substantive content
- [ ] Every DECISIONS.md entry reviewed with keep/change/remove verdict
- [ ] At least 3 web searches per major component documented
- [ ] Correctness issues flagged with severity (Critical/High/Medium/Low)
- [ ] Performance baselines measured where possible
- [ ] Roadmap is actionable (specific files, lines, tests)

---

## Constraints (from AGENTS.md)

- Single-user: No `user_id` anywhere
- Engine sole writer: backtestResults, backtestTrades
- TimescaleDB isolation: Engine only, candles only
- Binance isolation: Engine only calls Binance
- Testnet only: No mainnet yet
- No ccxt: Native httpx + HMAC
- P&L colors: emerald-400 / red-400
- No Redux: Zustand + TanStack Query
- Don't touch: .env, node_modules, host TA-Lib, DB configs

---

## Execution Notes

- Work in parallel where possible (multiple grep/read/websearch)
- Use `plan/changes/` as scratchpad — intermediate files OK
- Reference code with `file:line` format
- Update `docs/state/CURRENT_STATE.md` if discoveries change "Implemented" status
- No implementation — analysis only