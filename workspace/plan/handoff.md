---
## 2026-06-24 — Risk Model Improvements (workstream #2) — ALL 5 STEPS COMPLETE ✅

**Goal:** Five additive risk-model changes across `engine/core/models/risk.py`, `engine/core/models/portfolio.py`, `engine/services/backtest_runner.py`, `engine/core/live_bot_manager.py`.

**Steps done:**
- **Step 1 — Trailing stop on `AtrBracketRiskModel`**: Added `__init__`/`_reset()` with `_current_stop`/`_initialized`. Maintain path gates on `trail_atr_mult > 0`; ratchets stop using `price ± trail_mult × ATR`. Default 0 = static (golden-master safe).
- **Step 2 — Breakeven move**: Expanded state with `_entry_price`, `_initial_risk`, `_signal_price`. Maintain path gates on `breakeven_r > 0`; floors stop at `_entry_price` once `price >= entry + breakeven_r × initial_risk`. Both features share one stateful init block.
- **Step 3 — ATR percentile filter**: Added `_atr_history` (session-level, not reset between trades). Accumulates `s.vars["atr"]` each candle (O(1)). Entry path gates on `atr_percentile_min > 0` + ≥20 samples; uses `bisect.bisect_left` for rank. Default 0 = disabled.
- **Step 4 — Cost gate injection default**: Changed `_risk.get("min_edge_mult", 0.0)` → `0.05` in both `backtest_runner.py:310` and `live_bot_manager.py:242`. Golden master unchanged (ATR-based edge >> 5% of fee for all 5 strategies).
- **Step 5 — Portfolio exposure cap**: Added cap in `DefaultPortfolioModel.construct()` after sizing: `(risk_per_unit × qty) / equity > max_portfolio_risk` → veto. Injected from `risk_params` with default 0.06 in both runners. Golden master unchanged (default risk_pct=1% << 6% cap).

**Golden master:** `ws2_final` == `baseline` within tol=1e-6 (all 5 strategies). No re-baseline needed — all defaults are neutral for the golden dataset. Boundary suite 20/20.

**Files changed:** `engine/core/models/risk.py`, `engine/core/models/portfolio.py`, `engine/services/backtest_runner.py`, `engine/core/live_bot_manager.py`, `workspace/docs/state/CURRENT_STATE.md`, `workspace/plan/INDEX.md`, `workspace/plan/STATUS.md`, `workspace/plan/handoff.md`.

**Next:** Seq #3 — Dashboard page restructure (`dashboardPage_restructure.md`): 8 KPI stat cards, equity sparkline, drawdown chart, performance calendar heatmap, new backend aggregation endpoints.

**Open questions:** None.

---
## 2026-06-24 — Strategy Performance Refactor (workstream #1) — Phases 1–8 COMPLETE ✅

**Goal:** Two-phase strategy contract (`prepare()` batch + index-only `before()`) to kill the
O(N²) indicator recompute in the backtest loop, with live parity. Branch:
`refactor/precompute-strategies` (merged to `dev`).

**ALL PHASES DONE & golden-master gated (byte-equivalent, tol 1e-6, all 5 strategies):**
- **P1** — `BaseStrategy.prepare(candles)` default no-op (`core/strategy.py`) + one-time
  `strategy.prepare(candles_np)` in `services/backtest_runner.py` (step 6a', after validate_params).
- **P2** — MicroMacroRSIDivergence: RSI/ATR/4 pivots/smoothed-RSI → prepare(); dropped `candles[off:]`
  windowing; no-lookahead via `i-right` horizon in `_last_two_visible`. (17 trades / -273.30)
- **P3** — MultiDivergence: ATR + price pivots + every enabled oscillator's pivot arrays → prepare();
  `before()` reads up to horizon `c = i-L`. 9× O(N)→1×. (55 / -1688.49)
- **P4** — MicroScalper: fast/slow EMA + ATR seq → prepare(); index at i and i-1. (9 / -131.61)
- **P5** — BestSupertrend (hardest): SMA cross arrays (per-index cross_up/dn = exits + most-recent
  state machine = old backward scan) + HTF supertrend precomputed once; `tsl[-2]` via bucket index
  `k → htf_tsl[k-1]`. **Found & fixed a latent pandas-2.x `datetime64[ms]` epoch bug** in the bucket
  map (now uses `reindex(ffill)` on datetimes). Verified 0 per-candle signal diffs. (61 / -117.56)
- **P6** — AdaptiveTrend: trend/fast/slow EMA + ATR seq → prepare(); index at i, i-1, i-slope_lookback.
  (7 / +1543.91)
- **P7** — Live parity (`core/live_bot_manager.py`): `prepare()` re-run on the rolling ≤500 window
  each closed candle (+ warmup replay), `index=len-1`, then index-only `before()`. Same code path as
  backtest → exact parity, no drift, **no per-strategy `append_candle`** (rejected doc §3 approach).
- **P8** — boundary tests 20/20 ✅; py_compile all 8 changed files ✅ (ruff not in container);
  CURRENT_STATE.md updated; this handoff.

**Files changed:** `core/strategy.py`, `services/backtest_runner.py`, `core/live_bot_manager.py`,
all 5 `strategies/*/__init__.py`, `scripts/golden/{baseline,phase1..6}.json`,
`workspace/docs/state/CURRENT_STATE.md`, `workspace/plan/handoff.md`.

**Verify command (re-confirm any time, in engine container):**
```
docker compose exec engine python -m scripts.golden_master compare --a baseline --b phase6
docker compose exec engine python -m pytest tests/test_boundaries.py -q
```

**NOT done / next:**
- **Workstream #2 (risk-model improvements)** — separate, behavior-changing, re-baselines golden.
  Note the doc's "enable cost gate" item is WRONG about mechanism: changing the class default
  `min_edge_mult` is a no-op; both `backtest_runner.py:299` and `live_bot_manager.py:242` inject it
  from `risk_params` defaulting 0.0 — change the **injection default** instead.
- Known limitation flagged in code: BestSupertrend weekly (`W-MON`, right-labeled) HTF bucket mapping
  is off-by-one; not golden-covered (golden uses daily). Revisit if weekly HTF is ever used.
- Update `/add-strategy` skill template to require `prepare()` + index-only `before()` (deferred).

**Open questions:** None.

**Decisions (vs. written docs):** Live path (P7) uses `prepare()` on the rolling ≤500 window per
closed candle — NOT per-strategy `append_candle()` incremental (doc §3 rejected: drift/IndexError/
5 custom methods). Backtest index alignment is direct (`strategy.index = t`).

---
## 2026-06-24 — Strategy Performance Refactor (workstream #1) — Phase 1 COMPLETE

**Goal:** Two-phase strategy contract (`prepare()` batch + index-only `before()`) to kill O(N²)
indicator recompute in the backtest loop. Plan: `C:\Users\harsh\.claude\plans\go-to-workspace-plan-index-md-we-cuddly-gosling.md`. Branch: `refactor/precompute-strategies`.

**Decisions (vs. written docs):** Live path (Phase 7) uses `prepare()` on the rolling ≤500 window
per closed candle — NOT per-strategy `append_candle()` incremental (doc §3 rejected: drift/IndexError/
5 custom methods). Backtest index alignment is direct (`strategy.index = t` = absolute index into the
full `candles_np` passed to `prepare()`).

**Done this session (Phase 1 — no-op foundation):**
- `engine/core/strategy.py`: added `BaseStrategy.prepare(candles)` default no-op + clarified `before()` docstring (index-only for migrated strategies).
- `engine/services/backtest_runner.py`: one-time `strategy.prepare(candles_np)` call inserted after `validate_params()` (step 6a', before sim loop). Alpha params (which indicators need) are injected before this; risk params (step 6b) are not needed by prepare().
- **Golden master:** captured `baseline` on current HEAD, then `phase1` → `compare` = **GOLDEN-MASTER OK (5 strategies, tol 1e-06)**. Byte-equivalent (prepare() is no-op).

**Baseline metrics (for reference):** MicroScalper trades=9 np=-131.61 · AdaptiveTrend 7/+1543.91 · BestSupertrend 61/-117.56 · MicroMacroRSIDivergence 17/-273.30 · MultiDivergence 55/-1688.49.

**Next:** Phase 2 — migrate `MicroMacroRSIDivergence` (move RSI/ATR/4 pivots/smoothed-RSI to `prepare()`, drop `win` windowing, `before()` index-only). Gate: `run --label phase2` then `compare --a baseline --b phase2` must be OK. Watch the windowing-equivalence risk (full-array pivots vs. windowed `_last_two`).

**Open questions:** None.

---
## 2026-06-24 — Plan seq #1 (Live PnL fix) + #2 (Backtest UI refactor) COMPLETE

**Goal:** Implement the two highest-priority isolated plans, verify, and update workspace docs + plan tracking.

**Done this session:**
- **Live PnL `—` on reload (Option A — persistent DB):** Added `positionDetails` (`Object`, default `{}`) to `LiveSession` schema. `handleEngineStats` now `$set`s the per-symbol snapshot `{ side, qty, price, leverage }` on `position:open` and `$unset`s it on `position:close` (folded into the existing log `$push` updates). `SessionCard` seeds `positionDetails` state from `session.positionDetails` via lazy `useState`, so live PnL resolves after reload instead of showing `—`.
- **Backtest UI refactor:** Overview headline grid `grid-cols-5` (10) → `grid-cols-7` (14) — added Leverage, Fee Rate, Total Fees, Liquidations; Max Drawdown now shows `actual / allowed` (`riskParams?.max_session_dd ?? 0.20`). "Export JSON" relocated from the bottom card into the tab header bar (right-aligned, `ml-auto mr-4`, sized `px-4 py-2 text-sm` to match the page-header "Run Backtest" button). Removed the bottom "Simulation Config" and "Export Results" blocks; dropped the now-unused `Calendar` import.
- **Verified:** `npm run build` clean twice (8–10s, only pre-existing chunk-size warning). User-confirmed screenshot shows the 2×7 grid + `14.16% / 20.00%` drawdown rendering.
- **Docs:** `CURRENT_STATE.md` (Algo Trading + Backtesting), `API_CONTRACTS.md` (`LiveSession.positionDetails`). Archived both plans to `workspace/plan/archive/`; `INDEX.md` + `STATUS.md` renumbered remaining sequence (#1 strategy-perf refactor workstream, #2 risk improvements).

**Files changed:**
- `server/src/models/LiveSession.js`, `server/src/controllers/algo.controller.js`
- `client/src/components/algo/SessionCard.jsx`, `client/src/pages/Backtest.jsx`
- `workspace/docs/state/CURRENT_STATE.md`, `workspace/docs/core/API_CONTRACTS.md`
- `workspace/plan/INDEX.md`, `workspace/plan/STATUS.md`, `workspace/plan/handoff.md`
- moved → `workspace/plan/archive/{live_pnl_fix_plan,backtest_ui_refactor}.md`

**Heads-up (intentional, per the approved plan):** deleting the "Simulation Config" block also dropped **Date Range**, **Symbol / Exchange**, and **Net Funding** from the Overview tab. Leverage/Fee Rate/Total Fees/Liquidations survive in the new grid; Net Funding is not currently shown anywhere on Overview. Re-add as a 15th metric if it's needed.

**Next session:** seq #1 — strategy performance refactor workstream (`plans/migration_checklist.md`, Phases 0–8, golden-master gated). Not started.

**Open questions:** None.

---
## 2026-06-22 — Title Block Shades, Dialog Widths, and Title Descriptions COMPLETE

**Goal:** Standardize background shades to `#0d1117` via `--title-bg`, enforce fixed widths for Chaos & New Bot wizard dialogs, remove section descriptions, and fix any build errors.

**Done this session:**
- **Standardized background shades:** Defined global `--title-bg` CSS variable mapping to `#0d1117` in `index.css` and registered color `'title-bg'` in `tailwind.config.js`. Updated `Navbar`, `card.jsx`, `dialog.jsx`, `SessionCard`, `StrategyCard`, `StrategyCreateDialog`, `CodeViewer`, `BacktestCalendar`, `OrderHistory`, `Settings`, and `Trade` components to use `bg-title-bg` consistently.
- **Fixed Width Dialogs:** Locked wizard dialog containers to `w-[720px] max-w-[95vw]` with `overflow-x-hidden` in [AlgoTrading.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/AlgoTrading.jsx) to prevent resizing/shifting across step tabs.
- **Removed descriptions:** Stripped CardDescription subheadings app-wide (Recent Activity, Strategy Leaderboard, Cache Tables, Backtest configuration, and chart subheadings).
- **Vite/Babel Syntax Fix:** Fixed mismatched closing div tags in `ChaosWizard.jsx` around step 2 / live preview containers. Verified production build compiles successfully on host and inside the client container.

**Files changed:**
- [index.css](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/index.css)
- [tailwind.config.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/tailwind.config.js)
- [Navbar.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/layout/Navbar.jsx)
- [card.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/ui/card.jsx)
- [dialog.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/ui/dialog.jsx)
- [SessionCard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/algo/SessionCard.jsx)
- [StrategyCard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/features/strategies/StrategyCard.jsx)
- [StrategyCreateDialog.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/features/strategies/StrategyCreateDialog.jsx)
- [CodeViewer.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/features/strategies/CodeViewer.jsx)
- [BacktestCalendar.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/features/backtest/BacktestCalendar.jsx)
- [OrderHistory.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/OrderHistory.jsx)
- [Settings.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/Settings.jsx)
- [Trade.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/Trade.jsx)
- [ChaosWizard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/algo/ChaosWizard.jsx)
- [NewSessionWizard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/algo/NewSessionWizard.jsx)

**Next session:**
- None. (Task complete).

---
## 2026-06-22 — Wizard Dialog Layout Width Fix COMPLETE

**Goal:** Fix layout shifting and resizing of "Chaos Mode" and "New Bot" wizard dialogs during step navigation and allocation toggles.

**Done this session:**
- **Fixed Width Dialogs:** Enforced a fixed width of `w-full md:w-[672px] md:max-w-2xl` on both `DialogContent` wrappers in [AlgoTrading.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/AlgoTrading.jsx).
- **Verified Build:** Built the client production build to confirm everything compiles correctly.

**Files changed:**
- [AlgoTrading.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/AlgoTrading.jsx)

**Next session:**
- None. (Task complete).

---
## 2026-06-22 — Configurable Chaos Mode Wizard COMPLETE

**Goal:** Turn Chaos Mode into a configurable launch wizard (matching the New-Bot NewSessionWizard pattern) to control active strategies, manual/auto symbol picks, capital/leverage defaults, and shared risk parameters.

**Done this session:**
- **Tiered symbols & Allocator:** Created `server/src/utils/chaosAllocator.js` (pure symbol allocator) and updated `server/src/constants/top_symbols.js` with 80 tiered symbols (high, mid, low volume).
- **Chaos Settings:** Added 5 configuration fields to the Settings database model, controller validation, and the frontend Settings UI page ("Chaos Setting (testnet)").
- **StartChaos Rework:** Updated `POST /api/v1/algo/chaos` route to accept and validate timeframe, custom strategies selection, manual symbol lists, and risk overrides.
- **ChaosWizard Component:** Implemented `client/src/components/algo/ChaosWizard.jsx` (4-step dialog wizard) with strategies select, auto/manual symbol picker with cap checks, live client-side allocation previews (counts & tiers), risk configs, and review before launch.
- **Wired Frontend:** Integrated `ChaosWizard` modal into the "Chaos Mode" button in `client/src/pages/AlgoTrading.jsx`.
- **Docs updated:** Updated `workspace/docs/state/CURRENT_STATE.md` and `workspace/docs/core/API_CONTRACTS.md`.

**Files changed:**
- [top_symbols.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/constants/top_symbols.js)
- [chaosAllocator.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/utils/chaosAllocator.js)
- [Settings.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/models/Settings.js)
- [settings.controller.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/controllers/settings.controller.js)
- [Settings.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/Settings.jsx)
- [algo.controller.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/controllers/algo.controller.js)
- [algo.routes.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/routes/algo.routes.js)
- [useAlgoSessions.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/hooks/useAlgoSessions.js)
- [ChaosWizard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/algo/ChaosWizard.jsx) (New)
- [AlgoTrading.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/AlgoTrading.jsx)
- [CURRENT_STATE.md](file:///c:/Users/harsh/Desktop/enma_trading_platform/workspace/docs/state/CURRENT_STATE.md)
- [API_CONTRACTS.md](file:///c:/Users/harsh/Desktop/enma_trading_platform/workspace/docs/core/API_CONTRACTS.md)

**Next session:**
- Perform manual validation and testing in the Docker dev stack.

---
## 2026-06-22 — UI restyle to UI_STYLE_GUIDE.md — Phase 1 (foundation + chrome) COMPLETE; pages STAGED

**Goal:** Migrate the whole client to the midnight-blue trading-terminal palette in
`workspace/docs/core/UI_STYLE_GUIDE.md`. Reference impl (AlgoTrading.jsx + SessionCard.jsx) was
already on-style — the guide was derived from them.

**Done this session:**
- **Foundation layer migrated** (cascades to every page): `components/ui/{card,button,badge,input,select,table,dialog,tabs,skeleton}.jsx`, `layout/{Navbar,PageWrapper}.jsx`, `ui/PageHeader.jsx`, `features/dashboard/StatCard.jsx`, `components/RiskParamsFields.jsx`. Swaps: `bg-gray-900/950`→`bg-[#0d1117]`/`bg-[#060a0f]`/`bg-[#0a0d13]`, `border-gray-800`→`border-slate-700/50`, `text-gray-500`→`text-slate-400`, `rounded`→`rounded-lg`/`rounded-xl`, emerald-500/15→emerald-400/10.
- **Fully restyled pages:** Dashboard, Strategies, Settings, OrderHistory (+ their feature components: RecentActivityTable, StrategyLeaderboard, CachedCandlesTable, StrategyCard, CodeViewer, StrategyCreateDialog).
- **Page chrome only:** Trade.jsx root bg → `bg-[#060a0f]`; Backtest.jsx already uses PageWrapper/PageHeader (chrome free).
- **New skill:** `.claude/commands/restyle-ui.md` (`/restyle-ui`) — reads the guide + cheat-sheet and restyles any file on request.
- **Docs:** `client/CLAUDE.md` Layout/Styling/Chart/StatCard sections rewritten to the new palette and pointed at the guide as single source of truth.
- Verified: `npm run build` passes clean (8.9s, only pre-existing chunk-size warning).

**Next session — restyle remaining heavy internals (use `/restyle-ui`):**
- `pages/Trade.jsx` (~79 bespoke panels — bg-gray-900 boxes, order form, orderbook, chart panel, position table)
- `pages/Backtest.jsx` (~30 — inner panels, TableHeader bg-gray-950, progress bar) + `features/backtest/{BacktestConfigForm,BacktestHistory,BacktestCalendar,BacktestMetricCard}.jsx`
- `components/algo/{NewSessionWizard,SymbolPicker,ParamsForm}.jsx`, `components/SymbolSearchBar.jsx`
- `components/charts/EquityCurve.jsx` — apply chart-axis tokens (fill #94a3b8, stroke #1e293b, baseline #4B5563, line #34d399/#f87171)
- NOTE: `bg-gray-700/50` in AlgoTrading.jsx/SessionCard.jsx is the guide's sanctioned "stopped" status color — NOT a violation, leave it.

**Open questions:** None. Approach (foundation-first, pages staged; CLAUDE.md updated) confirmed with user.

---
## 2026-06-21 — Chaos Mode feature (feature.md) — Phases 1 + 2 COMPLETE

**Done:**
- Phase 1 (Leverage clamp): `engine/utils/symbols.py` → `get_max_leverage()` + `clamp_leverage()` (signed fetch + offline map). Wired into live bot (`live_bot_manager.py`, logs reduction), manual trade (`routers/trade.py`, returns `effectiveLeverage`), backtest runner (offline `_MAX_LEVERAGE_OFFLINE_MAP`, silent). Golden master confirmed byte-equivalent before/after (GOLDEN-MASTER OK).
- Phase 2 (Chaos runner): `POST /api/v1/algo/chaos` added to `server/src/controllers/algo.controller.js` (fan-out over 5 strategies, hardcoded max-vol params + disjoint symbol sets). Route registered in `server/src/routes/algo.routes.js`. Console script `engine/scripts/chaos_runner.py` thin client of endpoint with poll table + `--stop`. PnlFixer verified absent; `strategy_seeder.py` comment added.

**Phase 3 also COMPLETE:** `useStartChaos()` mutation added to `client/src/hooks/useAlgoSessions.js`. "Chaos Mode" button (amber, Zap icon) + confirm dialog + error banner added to `client/src/pages/AlgoTrading.jsx`. All 3 phases of feature.md are done.

**Files changed:**
- `engine/utils/symbols.py` — `get_max_leverage`, `clamp_leverage`, offline map
- `engine/core/live_bot_manager.py` — clamp + log before set-leverage
- `engine/routers/trade.py` — clamp in POST /leverage, return effectiveLeverage
- `engine/services/backtest_runner.py` — offline clamp
- `server/src/controllers/algo.controller.js` — startChaos + CHAOS_LAUNCH_LIST
- `server/src/routes/algo.routes.js` — POST /chaos registered
- `engine/scripts/chaos_runner.py` — new console script
- `engine/services/strategy_seeder.py` — PnlFixer-absent comment
- `workspace/docs/state/CURRENT_STATE.md` — updated
- `feature_tracker.md` — created

**Open questions:** None. All resolved in feature.md.

---
Previous: Strategy parameter fixes applied (2026-06-21). All 5 seeded strategies updated with industry-standard defaults per StrategyResearch.md. Golden master snapshots were STALE after this change.

> **Resolved 2026-06-21:** the golden baseline was re-established and the five-strategy comparison passed (boundary suite 20/20) — see `workspace/docs/state/CURRENT_STATE.md` → "Verified Baselines". The "must re-baseline" action below is complete.

Changes made:
- MicroScalper: EMA 2/3→9/21, ATR 5→14, atr_multiplier 0.0→1.2 (gate enabled), sl 0.3→1.5, tp 0.5→2.0, MIN_WARMUP 10→25
- AdaptiveTrend: trend EMA 50→200, slope_lookback 1→5, entry EMA 3/10→21/55, ATR 5→14, atr_floor_mult 0.0→1.0, sl 0.5→2.0, trail 0.5→3.0, tp_r_mult 0.5→0.0 (pure trailing), MIN_WARMUP 55→210
- BestSupertrend: SMA 2/3→7/20, Supertrend pd 2→10, factor 1.0→3.0, risk model SignalExitRiskModel→AtrBracketRiskModel (adds hard SL), added sl_atr_mult=2.0 and atr_period=14 params
- MicroMacroRSIDivergence: rsi 2→14, micro_pivot 1→3, macro_pivot 2→5, confluence_window 200→20, ATR 5→14, sl 0.5→1.5, enable_rsi_level_filter 0→1, MIN_WARMUP 20→30
- MultiDivergence: piv_len 2→4, min_confluence 1→3, sl 0.5→1.5, tp 0.5→2.0, ATR 5→14, RSI/MFI/Stoch 2→14, ADX 5→14, MACD 2/5/2→12/26/9, Z-Score 5→20

Next: Re-run golden master to establish new baseline:
  docker compose exec engine python -m scripts.golden_master run --label baseline
Then run boundary tests:
  docker compose exec engine python -m pytest tests/test_boundaries.py -q