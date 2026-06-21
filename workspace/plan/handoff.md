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