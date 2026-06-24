# Plan: Applied Doc Fixes (Items 1-18)

Originally from `workspace/issues_and_solutions/solutions/doc_fixes_applied.md` (merged into `plan/` 2026-06-24). All items 1-18 are now fully applied in the repository as of 2026-06-24.

Maps to analysis: `issues/documentation_drift.md`

---

| # | File | Fix | Severity |
|---|------|-----|----------|
| 1 | `core/MODELS.md` | Rewrote §1 diagram + code to remove `is_open` guard; correct call sequence to `forecast→assess→estimate→construct→route`; renamed methods `frame→assess`, `size→construct`, `plan→route`; reconciled model class names | 🔴 High |
| 2 | `core/ARCHITECTURE.md` | Scoped "defined once" claim to **authenticated/signed** base URLs; acknowledged public klines/leverageBracket URLs are hardcoded in 4 engine files per `binance-api.md §2` | 🟡 Medium |
| 3 | `core/API_CONTRACTS.md` | Changed `LiveSession.mode` from `"testnet"|"mainnet"` → `"paper"|"live"` | 🔴 High |
| 4 | `features/algo-trading/SPEC.md` | Replaced `should_long()/should_short()` with `forecast()`/`evaluate()` pipeline; added Chaos endpoints; reconciled Socket.IO events | 🔴 High |
| 5 | `features/auth-settings/SPEC.md` | Removed phantom auth tables (register/login/JWT), dead file refs (`auth.routes.js`, `auth.middleware.js`), deprecated scaffolding mentions | 🔴 High |
| 6 | `features/live-trading/SPEC.md` | Fixed testnet URL `testnet.binancefuture.com` → `demo-fapi.binance.com` | 🔴 High |
| 7 | `strategies/*.md` (all 6) | MicroScalper: params corrected (EMA 3→9/9→21, atr_mult 0.5→1.2, sl 1.0→1.5, tp 1.5→2.0, MIN_WARMUP 28→25, EMA(3/9)→EMA(9/21)). AdaptiveTrend: atr_floor 0.8→1.0, breakeven 1.0→0.0, max_leverage 3→20, MIN_WARMUP 215→210. BestSupertrend/MicroMacroRSI/MultiDivergence: reconciled. INDEX: fixed MicroScalper row | 🔴 High |
| 8 | `state/CURRENT_STATE.md` | Fixed leaderboard sort "win rate" → "net profit"; corrected BestSupertrend risk model | 🟡 Medium |
| 9 | `state/DEPRECATED.md` | Updated `BOOTSTRAP.md` refs → `AGENTS.md`; marked renamed-commands table as historical | 🟡 Medium |
| 10 | `plan/handoff.md` | Added resolution confirming golden-master baseline re-established | 🟢 Low |
| 11 | `skills/README.md` | Removed inline command count (point to GOVERNANCE Part 2 instead) | 🟢 Low |
| 12 | `core/DECISIONS.md` | Fixed testnet base URL (surfaced during verification) | 🟡 Medium |
| 13-18 | Metadata Files | Applied changes to `.claude/GOVERNANCE.md`, `engine/CLAUDE.md`, `client/CLAUDE.md`, `server/CLAUDE.md`, and `AGENTS.md` (see `plans/doc_fixes_pending.md` for individual details) | 🔴 High / 🟡 Medium |
