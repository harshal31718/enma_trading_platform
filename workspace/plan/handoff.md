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
Previous: Strategy parameter fixes applied (2026-06-21). All 5 seeded strategies updated with industry-standard defaults per StrategyResearch.md. Golden master snapshots are now STALE — must re-baseline before any further pipeline refactors.

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