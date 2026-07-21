# ENMA — Current State

**Authority:** This is the single source of truth for what ENMA currently does.
Read this before starting any work. If this conflicts with chat history, this document wins.

Last updated: 2026-07-19 (**Plan 10 SHIPPED IN FULL — PBO (Probability of Backtest Overfitting,
CSCV) closes the plan out.** New `engine/services/pbo.py`: `run_lab_pbo()` runs ONE full-date-range
optimization pass (reusing `optimizer.run_optimization`/`run_bayesian_optimization` directly, no
walk-forward fold splitting — a genuinely different procedure, per the plan's own scoping notes)
to get N candidates, each already backtested over the whole range with trades persisted to
`backtestTrades`; `compute_pbo()` then partitions the date range into `nBlocks` (even, default 8,
capped 12) contiguous CSCV blocks and scores every `C(nBlocks, nBlocks/2)` train/test combination
by slicing each candidate's ALREADY-fetched trades in memory (numpy) — zero extra backtests beyond
the initial N. Small but real engine fix alongside it: `optimizer.py`'s scored-trial dicts now
carry their own `jobId` (previously lost once `_finalize_optimization` re-sorted by loss), closing
the gap that made reusing a trial's persisted trades impossible. New Node surface: `POST/GET
/api/v1/lab/pbo[/:labId]`, `pboQueue`/`pbo.worker.js`, `buildPBOConfig()` (own validator — no
mode/nFolds/trainRatio, since PBO isn't a walk-forward variant). New "Overfitting (PBO)" tab on
`/lab`: `PBOWizard.jsx` (mirrors the Optimizer wizard's paramGrid/riskLeverageGrid/method shape
plus an `nBlocks` control), `PBOVerdictCard.jsx` (severity-colored %, <20% low / 20-50% elevated /
≥50% high — a judgment call documented in the component, not from a specific citation),
`PBOCandidatesTable.jsx`. Verified with real Docker access: engine pytest 567/567 (16 new PBO
tests, including two hand-derived exact-value scenarios — a perfectly anti-correlated IS/OOS
construction asserting `pbo == 1.0` exactly, and a strictly-ordered construction asserting
`pbo == 0.0` exactly, not just directional checks), server jest 181/181 (12 new `buildPBOConfig`
cases), client `vite build` clean, `vitest` 11/11, live-verified end-to-end against the real `/lab`
PBO tab in a real browser session (a genuine walk-forward-free run completed through the full
BullMQ→engine→Mongo pipeline, `PBOVerdictCard`/`PBOCandidatesTable` rendered a real 0.0% PBO result
with zero console errors). One real bug caught and fixed during design, before any code was
written: the CSCV rank convention (rank 1 = worst OOS performer, ascending) matters for the sign of
the logit statistic PBO's definition (`P(logit<=0)`) depends on — an initial descending-rank draft
would have silently inverted the whole statistic (a candidate performing BEST out-of-sample would
have counted as "overfit"); caught while hand-deriving the two exact test scenarios, fixed before
being trusted. Plan 10 is now fully shipped — no remaining scoped-but-unbuilt items.)
Earlier: 2026-07-19 (**Plan 10 Phase 4a + 4b shipped** — MC-scored trial selection
(`config.mcScoring`, opt-in) OOS-evaluates a fold's top-K eligible trials and ranks them by Monte
Carlo p5 outcome instead of raw loss, surfacing a robust pick that can differ from the point-metric
winner; risk_pct/leverage search (`config.riskLeverageGrid`, opt-in) extends the same fold loop to
search sizing/leverage alongside strategy params. Both are default-off, zero behavior change for
every existing run. See the "Strategy Lab" section below for the full shape. Two sessions worked
this concurrently (one built the engine+client end-to-end via a sandbox with limited real-execution
access; a second, working the same repo in parallel, did the actual Docker-based verification):
engine container pytest **551/551**, server container jest **169/169**, client `vite build` clean,
client `vitest` smoke 11/11. Golden master flagged real drift across 3 seeded strategies
(`MicroScalper`/`MultiDivergence`/`MicroMacroRSIDivergence`) against the prior `after_dsr` baseline
— investigated, NOT a code regression: two independent golden-master re-runs against the current
code+environment are byte-identical to each other, and the TimescaleDB `candles` table for
BTCUSDT/1h currently has a real gap (only 1,440 of the ~8,760 candles needed for the golden
harness's fixed 2024-01-01→2025-01-01 window are cached) — a data-availability difference between
when the `after_dsr` baseline was captured and now, not a Phase 4 code change (Phase 4a/4b touch
only optimizer/walk-forward plumbing, never `backtest_runner.py`/strategies/indicators). Live-
verified end-to-end in a real logged-in browser session against the actual `/lab` Optimizer wizard:
MC-scoring toggle + top-K input render and wire into the cost estimate correctly, a real walk-
forward job completes through the full BullMQ→engine→Mongo pipeline, and the MC-scored-picks panel
renders both the "robust pick differs" path and the honest "insufficient OOS trades, no fabricated
percentile" guard path with zero console errors. **PBO remains the only unshipped Plan 10 item.**)
Earlier: 2026-07-19 (**Plan 10 Phase 3e shipped** — Deflated Sharpe Ratio (DSR) is now
computed per walk-forward fold, the statistic Plan 10's §2.2 "honesty layer" deferred across four
prior sessions specifically for lack of a numerically-verified normal-CDF/inverse-CDF primitive.
New `engine/services/stats.py`: `norm_cdf` (exact, `math.erf`), `norm_ppf` (Acklam's rational
approximation + one Halley refinement step, no scipy dependency), `deflated_sharpe_ratio()`/
`expected_max_sharpe()` (Bailey & López de Prado 2014) — verified two ways in `test_stats.py`:
round-trip (`norm_cdf(norm_ppf(p)) == p` to ~1e-9 across both Acklam branches) and against
published reference quantiles (Φ⁻¹(0.975)≈1.959964, Φ⁻¹(0.995)≈2.575829). Trade-level (not the
paper's per-period formulation): the per-trial Sharpe-like statistic is `sqn / sqrt(totalTrades)`
(SQN is already trade-level, `sqrt(N)*mean(pnl)/std(pnl)`, so no new per-trial metric was needed),
skew/kurtosis are two new additive `metrics.py` statistics (`SkewnessStat`/`KurtosisStat`,
golden-master-verified — every pre-existing metric byte-identical before/after, only the two new
keys appeared in the diff). `walk_forward.py` attaches `fold.dsr = {dsr, expectedMaxSharpe,
nTrials, insufficientData}` per fold; `0.5 + insufficientData:true` (never a fabricated confident
number) when there's too little data. `FoldResultsTable.jsx` gained a DSR column. **PBO remains
explicitly deferred** — canonical PBO (CSCV) needs every trial's OOS performance across multiple
resample combinations; this architecture only OOS-evaluates each fold's winner (Phase 3d's own
documented reason), so faking PBO from data that doesn't support it was rejected in favor of
disclosing the gap, same stance every other Plan 10 session has taken on unverifiable statistics.

**Real, unrelated pre-existing bug found and fixed via live testing:** `optimizer.py`'s
`_build_param_grid` used to materialize the FULL cartesian product (`list(itertools.product(...))`)
before applying the `max_combinations` cap — a strategy with several wide-range params (e.g.
AdaptiveTrend's own Optimizer-wizard default grid, ~12 checked params) has a total combo count in
the hundreds of trillions, and building that list hung/OOM'd the entire single-process engine
container. Reproduced live (checking AdaptiveTrend's default param set in the real `/lab`
Optimizer wizard and clicking "Run" froze the container — confirmed via `docker stats` showing
near-zero CPU, i.e. stuck allocating, not computing), root-caused, and fixed: when the grid exceeds
`max_combinations`, indices are now sampled via `random.sample` on a lazy `range` object (Python
special-cases this, no materialization) and each one decoded directly to its combo
(`_decode_combo_index`, mixed-radix decomposition matching `itertools.product`'s own ordering,
verified against real `itertools.product` output for exactness) — the full product is only ever
materialized when it's already small enough to be safe. New `test_param_grid.py`, including the
exact real-world AdaptiveTrend param grid that used to freeze the container (now completes in
~4s). Engine 538/538, server jest 156/156, client `vite build` clean; both fixes live-verified
end-to-end via the real `/lab` Optimizer wizard in a real browser session (DSR values 57–69%
observed on real cached BTCUSDT data; the AdaptiveTrend grid-freeze repro now completes cleanly).
See `workspace/plan/10_monte-carlo-strategy-lab.md` Phase 3e section for full detail.)
Earlier: 2026-07-19 (**Plan 10 Phase 3b shipped** — Optuna TPE Bayesian search is now a
selectable alternative to grid search for the walk-forward optimizer's per-fold train step.
`engine/services/optimizer.py` gained `run_bayesian_optimization()` (ask/tell async loop over
optuna, seeded `TPESampler`) + a `_suggest_params()` adapter reusing the existing `param_grid`
JSON spec unchanged for both grid and Bayesian (Plan 19's own design). `walk_forward.py`'s fold
loop dispatches on `config.method` (`"grid"` default / `"bayesian"`), one TPE study per fold with
a deterministic-but-distinct seed (`base_seed + foldIndex`). `POST /optimize/run` and
`POST /lab/optimizations` both gained `method`/`nTrials`/`seed`. `WalkForwardWizard.jsx` gained a
Grid/Bayesian search-method toggle + trials-per-fold input. **Real, pre-existing bug found and
fixed in passing:** `/optimize/run`'s raw JSON response (and `walk_forward.py`'s per-fold
`best`/`trials`) crashed with `ValueError: Out of range float values are not JSON compliant`
whenever any combo errored (`loss=inf`) — this affected grid search too, just never exercised
because Bayesian's live-browser test (this session) was the first time a real strategy validation
error surfaced through this exact path. Fixed at the source: `optimizer.py`'s shared
`_finalize_optimization()` tail now sanitizes non-finite loss to `null` for every caller. Verified
with real Docker access: engine suite 488/488 (+16 new tests), server jest 156/156 (+8), client
`vite build` clean, plus live end-to-end runs against real cached BTCUSDT candles — both a direct
`POST /optimize/run` (MicroScalper, one combo genuinely errored, correctly sanitized) and a full
`/lab` Optimizer-tab browser session (AdaptiveTrend, Bayesian method, both folds legitimately
skipped — no eligible combo in 5 trials over a large param space — rendered correctly with no
console errors). DSR/PBO overfitting stats remain deferred (still need a numerically-verified
CDF primitive). See `workspace/plan/10_monte-carlo-strategy-lab.md` Phase 3b section for detail.)
Earlier: 2026-07-19 (**Plan 10 Phases 2/3a/3c shipped, Phase 3d fully shipped (persistence +
trials-table UI)** — Strategy Lab is now a real `/lab` page with two tabs: Robustness (MC, Phase 2)
and Optimizer (walk-forward, Phase 3c UI over Phase 3a job plumbing). Each walk-forward fold now
returns every grid-search trial, not just the winner, and `TrialsExplorer.jsx` renders it as a
sortable trials table + 2-param loss heatmap. This session had real Docker access AND a logged-in
browser session, so it verified by actually clicking the Optimizer wizard end-to-end — which found
and fixed two real bugs a curl-only test wouldn't have caught: `WalkForwardWizard.jsx` never sent
`exchange` in its submit payload (every real submission 400'd), and persisting every trial exposed
error-combo `loss=inf` values that crashed `json.dumps()` at the FastAPI response layer (500).
Engine 472/472, server jest 148/148, client `vite build` clean. See the "Strategy Lab" section
below and `workspace/plan/10_monte-carlo-strategy-lab.md` for full detail.)
Earlier: 2026-07-19 (**Plan 10 Phase 1 shipped** — job-based Monte Carlo robustness runs,
mirroring the existing BullMQ backtest pattern: new `labResults` collection, `simulationQueue`/
`simulation.worker.js`, engine `routers/simulate.py` (`POST /simulate/monte-carlo`), Node
`lab.controller.js`/`lab.routes.js` at `/api/v1/lab`. Fixes the SRV-5 synchronous-compute-behind-a-
`GET` defect that 2026-07-15's MC-engine-core rewrite (Phase 1a) didn't address. Real end-to-end
smoke test against a live 38-trade backtest: 5,000 runs in ~1.0s. Engine 458/458, server jest
129/129.)
Earlier: 2026-07-19 (**F7 LIVE-VERIFIED & resolved on the diagnostic side, fixes committed as
`bedd8dc`** — container pytest 444/444; live testnet chaos confirmed the fill-staleness symptom is
fixed (~0.5s via A-8, not ~60s) and root-caused the SL/TP-placement 400 as `-2021 Order would
immediately trigger` (PERCENT_PRICE hypothesis disproven). Two new bugs surfaced live: (a) FIXED —
a server governor-config coercion (`risk.js` `Number(null)===0`) that armed correlation/VaR/CVaR/
margin caps at 0 on blank fields and blocked ALL live entries, +5 jest tests → 116/116; (b) FIXED —
`-4015` emergency-close `clientOrderId`>36 chars, systemic across ~6 placement sites, resolved with
a central `_make_client_id()` ≤35-char builder (engine pytest 450/450). See the Known Technical
Debt entries below + `handoff.md` 2026-07-19. Plan 22/24 got incidental live
re-verification (governor "Reducing" badge, StoplossGuard cooldown, correlation cap, clean stop).
Earlier: 2026-07-17 (**Plan 9 — ALL STEPS SHIPPED (9.1–9.11)**, container-verified 415/415
pytest. Same session, in order: 9.11-B decided (cost gate stays opt-in), 9.9's QNT-14 leg-vs-
round-trip trade-statistics separation (new opt-in `aggregate_legs_to_round_trips()`), 9.10's
opt-in fill-model ladder (`LadderedTransactionCostModel` — volatility-scaled slippage +
√-impact), 9.8's opt-in intrabar (1m detail) SL/TP-ordering resolution
(`ExecutionKernel.intrabar_detail`), and 9.7's historical funding ledger (new TimescaleDB
`funding_rates` hypertable + `funding_importer.py`/`funding_manager.py`, real Binance funding
events replace the flat-rate fallback when opted in — manually verified against real mainnet
data). **Every mechanism ships opt-in/default-off** — golden master re-confirmed byte-identical
after each step, zero behavior change for any existing backtest unless a caller explicitly opts
in. Three sub-items deliberately deferred: liquidation fee (QNT-4, contradicts a documented
`engine/CLAUDE.md` contract — needs a `DECISIONS.md` product call, not a mechanical fix),
warmup-insufficiency fail-loud (QNT-16, needs Plan 8 coordination per 9.10's own text), and
`"inf"`-string metric persistence (QNT-13's other half — audited, genuinely dormant, zero
client/server consumption found). See `9_backtest-and-optimizer-correctness.md` for full detail
on each step.
Earlier: 2026-07-17 Plan 9 Step 9.11-B decided: PCM edge-vs-cost gate stays opt-in/off by
default — user's explicit call, no code change, zero re-baseline risk. Plan 9 Step 9.9's
fail-loud metric registry shipped same day: `StatisticRegistry.compute_all()`
(`engine/services/metrics.py`) now logs any stat computation failure with the stat name +
exception instead of silently returning `"0.00"` indistinguishable from a legitimately-zero
metric — fallback value unchanged, golden master byte-identical (no seeded strategy's stats
currently throw). Container suite 377/377 passed (up from 374). 9.9's other three sub-items
(`"inf"`-string persistence — audited, currently dormant, zero client consumption found; QNT-14
leg-vs-round-trip trade-statistics separation; block-bootstrap Monte Carlo, absorbed by Plan 10)
remain open.
Earlier: 2026-07-17 Plan 17 — recursive-formula / warmup-insufficiency analysis tool
shipped: `engine/scripts/recursive.py` sweeps each seeded strategy's `prepare()`-computed
indicators across warmup sizes [200, 400, 500, 1000, 2000] and reports pct-drift vs. a full-history
baseline at a fixed anchor candle — the operationally important question is whether live's rolling
500-candle re-prepare window (workstream #1, P7) is long enough for every strategy's recursive
indicators (EMA/RSI/SuperTrend) to have converged. **Result: no column drifts beyond 0.01% at
w=500 for any of the 5 seeded strategies** — including AdaptiveTrend's `_trend_ema_seq`
(EMA(200) trend filter), which shows real -2.56% drift at w=200 but has already converged to
-0.0007% by w=500. Live's 500-candle warmup is sufficient for every seeded strategy today; no
`live_bot_manager.py` warmup-length change needed. New `engine/tests/test_recursive.py` (10 cases)
self-tests the tool itself (EMA(50) drifts >1% at w=60, converges <0.01% by w=250, ~0% by w=500;
SMA(50) is exactly stable at any w>=50 — the plan's own verification gate). Container suite:
374/374 passed (up from 364).
Earlier: 2026-07-17 Plan 13 — informative/multi-timeframe contract shipped:
`BaseStrategy.informative_timeframes` + `self.htf(tf)`, an as-of aligned, lookahead-safe
higher-timeframe OHLCV array (freqtrade `merge_informative_pair` ffill+shift pattern), wired into
both `backtest_runner.py` and `live_bot_manager.py`. Default `[]` is a no-op — no seeded strategy
adopts it yet (primitive only). Golden master byte-identical; container suite 364/364.
Earlier: 2026-07-17 Plan 9 Step 9.11-A — the PCM edge-vs-cost veto (`min_edge_mult`) rewired to
the object it actually reads (`portfolio_model`, not `cost_model`), formula fixed to quote-vs-quote
(scaled by the same `qty_est` the Cost Model uses, not a bare per-unit price distance), and
`Signal.magnitude` wired in as the edge term. Both injection sites now default to `0.0` (was
`0.05`, a no-op since the old value never reached the gate). Golden master byte-identical;
container suite 358/358. Gate remains opt-in/inert by default — activating it at 0.05 is a
separate Step B product decision, not yet made.
Earlier: 2026-07-17 (Plan 24 — ALL STEPS S-1–S-5 SHIPPED: BestSupertrend's "never trades at
default settings" bug fixed — `size_by_notional()` now sizes down to the true affordable notional
instead of the runner rejecting every entry (S-1); live HTF supertrend was one bar more stale than
backtest, fixed (S-2); structurally unsatisfiable tf/timeframe combos now fail loud instead of
silently zero-trading forever (S-3); the colliding `order_type` param renamed to
`direction_filter` (S-4); docs updated (S-5). Container suite 353/353 passed; golden master
re-baselined for S-1 (only BestSupertrend diverges — same trade count/win-loss structure, other 4
strategies byte-identical). Pending live Testnet re-verification only.
Earlier: 2026-07-17 Plan 22 — ALL STEPS 22.1–22.7 SHIPPED. Session Risk Governor, capital
integrity gate, portfolio open-risk/liq-buffer, protections parity, live VaR/CVaR enforcement, the
correlation-aware concentration cap, the inverse-volatility portfolio allocation layer, and the
Zone 2 UI/schema batch — all shipped and verified (`docker exec ... pytest /app/tests/` —
330/330 passed; `docker exec ... npx jest` — 88/88 passed; 22.6 additionally golden-master-verified
byte-identical for the default `equal` allocation; 22.7 additionally live-verified in-browser via
Claude in Chrome against the running dev stack), pending live Testnet re-verification only — see
Algo Trading section. **22.7 found and fixed a real bug spanning back to 22.1**: the governor
config cascade in `live_bot_manager.py`'s `start_session` was reading `risk_params` at the wrong
dict level (Node sends `{symbol: {...}, "default": {...}}`, not a flat dict) — every Zone-2-
configured governor knob had silently never reached the governor since 22.1 shipped. Fixed and
covered by a new test driving the real payload shape.
Earlier: 2026-07-16 Known Technical Debt update confirmed the algo/conditional-order
`ORDER_TRADE_UPDATE` gap live and logged two new open bugs from a live Chaos run — see below.
Earlier relocation: content moved into feature SPEC docs and DECISIONS.md; see
`workspace/plan/current_state_relocation.md` for the relocation plan and
`workspace/docs/features/*/SPEC.md` for the moved detail)

---

## Implemented Features

### Auth & Access Control (Auth Branch — active)
- **Google OAuth 2.0** via Passport.js (`passport-google-oauth20`), sessionless. Flow: `/api/v1/auth/google` → Google → `/api/v1/auth/google/callback` → JWT cookie set → redirect to `/`.
- **JWT in `httpOnly` cookie** (`enma_jwt`, `sameSite: lax`, 7-day expiry). Verified by `verifyJWT` middleware globally applied at `app.use('/api/v1', verifyJWT)` (auth routes excluded).
- **Open login** — anyone with a Google account can sign in. There is **no email whitelist** (removed 2026-07-07; the former `PlatformConfig` singleton + `/admin/allowed-emails` CRUD are deleted). Admin email (`ADMIN_EMAIL`) is auto-promoted to `role: 'admin'` on first login.
- **Per-user Algo Trading gate** — `User.algoAccess.status` (`none`|`requested`|`granted`, default `none`; absent field reads as `none`). The `requireAlgoAccess` middleware gates only the start actions (`POST /algo/sessions`, `POST /algo/chaos`); admins bypass via role. Everything else (Backtest, manual Trade, Binance key entry, viewing the Algo page + wizards, listing/stopping sessions) is open to any authenticated user. `verifyJWT` reloads the user each request, so grants/revokes take effect immediately without re-login.
- **User model**: `User.js` with `googleId`, `email`, `name`, `avatar`, `role` (`user`|`admin`), `isActive`, `lastLoginAt`, and `algoAccess` (`status`, `requestedAt`, `decidedAt`, `decidedBy`).
- **Request flow**: users request access from the **Settings → Algo Trading Access** card (`POST /api/v1/algo/access-request`, idempotent `none`→`requested`). The AlgoTrading page shows a status banner (request CTA when `none`, pending notice when `requested`) and disables the New Bot / Chaos Mode buttons until granted.
- **Admin panel**: single sortable **user table** (`GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/:id/algo-access` with `{ status: 'granted'|'none' }`) — admin-only via `requireAdmin`. Shows all users with name/email/role/status/joined, a category filter (All/Allowed/Requested/No access), and Grant/Revoke actions (admin rows are not editable). Client: `/admin` route, visible only to admin users in the Navbar.
- **Per-user Settings**: `Settings` model scoped by `userId` (string). Each user's exchange settings, risk defaults, chaos settings, and encrypted Binance keys are stored per-user. `_getOrCreate(userId)` upserts on first access.
- **Socket.IO rooms**: All `io.emit()` replaced with `io.to('user:' + userId).emit()`. Clients join their room on auth via `verifyJWT` in the Socket.IO auth handler.
- **Client auth**: `useAuth()` hook (TanStack Query, `GET /api/v1/auth/me`, 5-min stale, 401 returns null silently). `ProtectedLayout` in `App.jsx` — spinner while loading, redirect to `/login` if not authenticated, then renders Navbar+Outlet. Navbar shows Google avatar, user name, Admin link (admin only), and logout button.
- **Axios/Socket**: Both have `withCredentials: true` to send the `httpOnly` cookie cross-origin.

### Settings & Credentials
- Binance API key storage: AES-256 encrypted per-user, stored in MongoDB `Settings` collection
- Key entry in Settings page (`POST /api/v1/trade/settings/keys`), status indicator shows if keys are saved
- Key verification against Binance Testnet on save
- **Exchange Settings**: Centralized configuration for trading fees, backtest defaults, bot defaults, simulation parameters (slippage, funding), and **risk-model defaults** (risk % per trade, reward:risk ratio, max session drawdown, liquidation buffer). All values stored as variables — no hardcoded numbers. Accessible via GET/PUT `/api/v1/settings/exchange`. Forms pre-fill from saved defaults.

### Strategy Management
List, create, clone, and view (read-only) strategies; 6 strategies seeded on startup, each bound
to a specific Risk/Portfolio model pair. **In-app code editing was removed 2026-07-15** (Plan 3
Step 3.2, SEC-2 — closed the any-user strategy-code RCE path outright). **Detail moved 2026-07-02
to** `workspace/docs/features/strategy-management/SPEC.md` (Built-in Strategies table, updated
2026-07-15 for the edit-path removal) — this bullet is a pointer, not a description.
**MarginSurge (Plan 23, added 2026-07-21)** is the 6th seeded strategy — architecturally correct
(boundary-clean, lookahead-clean) but its **validation FAILED**: negative expectancy on every
tested symbol/timeframe, grid-search parameters catastrophically overfit out-of-sample. Seeded
for backtest/reference use only; not recommended for live sessions regardless of Plan 21's own
gating. See `workspace/docs/strategies/MarginSurge.md` for the full report.

### Backtesting
Full strategy simulation against historical OHLCV, unified five-model pipeline (shared with live
trading), isolated-margin futures realism, multi-symbol shared-wallet mode, TWAP/VWAP/Iceberg
execution slicing, and a tabbed report UI with Performance Calendar and Buy & Hold benchmark overlay.
**Detail moved 2026-07-02 to** `workspace/docs/features/backtest-pipeline/SPEC.md` (Data Flow,
Execution & Risk Mechanics, Report UI sections) — this bullet is a pointer, not a description.

### Dashboard
- **Live price strip** (`TickerStrip`): BTC/ETH majors + open-position symbols (capped 8), from the browser-direct Binance public WS (no server load)
- **Account overview** (`AccountOverview`): testnet + **mainnet** wallet/available balances side by side, testnet unrealized PnL, margin balance + open-position count. Mainnet is **read-only** (`GET /api/v1/trade/balances`, F-021 2026-07-02); trading stays testnet-pinned
- Condensed backtest KPI strip (`BacktestKpiStrip`): total runs, best strategy, avg win rate, profit factor, Sharpe, Sortino, max drawdown, expectancy
- Strategy leaderboard (per-strategy averaged metrics, sorted by net profit)
- Recent Live Runs + Recent Backtests panels (last 5 each, deep-link to results)
- Cached candles table (TimescaleDB inventory) — demoted into a collapsible section (default closed)
- **See** `workspace/docs/features/dashboard/SPEC.md` for the full redesign spec.

### Strategy Lab (Plan 10 — `/lab` page, three tabs: Robustness (MC) + Optimizer + Overfitting (PBO))
Job-based Monte Carlo robustness runs over a completed backtest's trades: `POST
/api/v1/lab/simulations {sourceJobId, mode, runs, blockLen, ruinThresholdPct, seed}` enqueues a
BullMQ job (same pattern as backtest), the engine's vectorized block/iid bootstrap
(`services/monte_carlo.run_lab_simulation`) writes percentile equity bands + drawdown-exceedance
curve + ruin probability to the `labResults` collection, `GET /api/v1/lab/simulations/:simId`
reads it back. `configHash` short-circuits identical resubmissions. The existing synchronous
`SimulationResults.jsx` / `leverage_sensitivity.py` MC path is untouched (still what the Risk
Dashboard shows today).

Walk-forward optimization (Phase 3a/3b/3c/3d/3e shipped): `POST /api/v1/lab/optimizations
{strategyId, exchange, symbol, timeframe, startDate, endDate, paramGrid, mode, nFolds,
trainRatio, method, nTrials, seed, ...}` enqueues a BullMQ job; the engine
(`services/walk_forward.py`) splits the date range into candle-count folds, optimizes each fold's
train window via `services/optimizer.run_optimization` (grid, default) or
`run_bayesian_optimization` (`method: "bayesian"`, Phase 3b — Optuna TPE, `nTrials` per fold,
per-fold deterministic seed), evaluates the winner OOS, and reports a per-fold IS-vs-OOS Sharpe
degradation ratio plus a trade-level Deflated Sharpe Ratio (`fold.dsr`, Phase 3e —
`services/stats.deflated_sharpe_ratio`) plus a trade-level stitched-OOS aggregate. Each fold's
`trials` array (Phase 3d) carries every combo scored on that fold's train window, not just the
winner — rendered as a sortable trials table + 2-param loss heatmap by `TrialsExplorer.jsx`
(`FoldResultsTable.jsx` is one row per fold, now with a DSR column — the per-trial trials view is
the separate, already-shipped `TrialsExplorer.jsx`). `WalkForwardWizard.jsx` has a Grid/Bayesian
search-method toggle.

**Phase 4a — MC-scored trial selection (opt-in, shipped 2026-07-19):** `config.mcScoring`
(default `False`, zero behavior change otherwise) OOS-evaluates a fold's top-`mcTopK` (default 3,
capped at 10) min-trades-*eligible* trials instead of only the raw-loss winner, and ranks them by
Monte Carlo p5 profit outcome (`services.monte_carlo.compute_mc_stats`, a new Mongo-free pure
extraction of `run_lab_simulation`'s bootstrap core) rather than the point-estimate loss —
`fold.mcScoring.robustPick` can differ from `fold.mcScoring.rawPick`, surfacing the fragility gap
a point metric hides. A candidate with fewer than `MIN_MC_OOS_TRADES`=10 OOS trades is marked
`insufficientData: true` rather than given a fabricated percentile. `WalkForwardWizard.jsx` has
the toggle + top-K input; `RobustPickPanel.jsx` (new) renders the per-fold picks table inside
`TrialsExplorer.jsx`.

**Phase 4b — risk_pct/leverage search (opt-in, shipped 2026-07-19):** `config.riskLeverageGrid`
(default `None`) cartesian-multiplies a separate `risk_pct`/`leverage` grid against the strategy's
own `paramGrid` (`optimizer._build_combined_grid`, namespaced apart from `alpha_params` since
`run_backtest_simulation` validates alpha params strictly against the strategy's `PARAMS` schema).
Each fold's winning trial's own searched risk_pct/leverage — not the job's flat default — is what
that fold's OOS evaluation (and Phase 4a's MC-scored candidates) actually use
(`walk_forward._override_bt_common`). `WalkForwardWizard.jsx` has a "Search risk_pct / leverage
too" toggle; a robust pick's risk_pct/leverage carries through a "Copy robust pick → Backtest"
deep link into `NewBacktestWizard.jsx`'s prefill. The Backtest report page also gained a compact
MC summary strip (`MCSummaryStrip.jsx`, `Backtest.jsx`) — the §4.4 "everywhere else" auto-enqueue
piece deferred since Phase 2.

**PBO (Probability of Backtest Overfitting, CSCV) — shipped 2026-07-19, closes Plan 10 out.**
Deliberately NOT a walk-forward extension — `POST /api/v1/lab/pbo {strategyId, exchange, symbol,
timeframe, startDate, endDate, paramGrid, method, nBlocks, ...}` runs `services/pbo.run_lab_pbo()`,
which calls `optimizer.run_optimization`/`run_bayesian_optimization` DIRECTLY over the full
requested date range (no fold splitting) to get N candidates, each already backtested once with
trades persisted to `backtestTrades`; then `compute_pbo()` partitions the range into `nBlocks`
(even, default 8, capped 12) contiguous blocks and scores every `C(nBlocks, nBlocks/2)` train/test
combination by slicing each candidate's already-fetched trades in memory — zero extra backtests.
Reports `results.pbo` (0-1, the fraction of evaluated splits where the in-sample-best candidate's
OOS performance fell at/below the median — 50%+ means no better than chance) with an
`insufficientData` guard when too few splits have enough OOS trades to score. New "Overfitting
(PBO)" tab: `PBOWizard.jsx`, `PBOVerdictCard.jsx` (severity-colored: <20% low, 20-50% elevated,
≥50% high), `PBOCandidatesTable.jsx`. See `workspace/plan/10_monte-carlo-strategy-lab.md` for the
full design rationale (resolves both open questions its own scoping notes flagged) and verification
detail. **Plan 10 is now fully shipped — no remaining scoped-but-unbuilt items.**

### Risk Intelligence Dashboard
Centralized `/risk-dashboard` page: Zone 1 real-time portfolio VaR/CVaR + correlation heatmap, Zone 2
hierarchical risk-limit overrides (global → strategy → symbol) that cascade into live/chaos/backtest
launches, Zone 3 leverage-scenario + Monte Carlo historical simulation. **New SPEC written 2026-07-02
at** `workspace/docs/features/risk-dashboard/SPEC.md` — this bullet is a pointer, not a description.

### Candle Management
- Auto-fetches OHLCV from Binance production REST API (`fapi.binance.com`) using httpx
- Stores in TimescaleDB `candles` hypertable (1,000-candle batches, 200ms inter-batch delay)
- Idempotent: `INSERT ... ON CONFLICT DO NOTHING`
- Candles are permanent — never deleted, reused across all future backtests for same symbol/timeframe
- `ensure_candles_available()` in `candle_manager.py` is the single entry point — never bypassed

### Live Trading — Trade Page
- Account info: balances, wallet balance, margin balance, unrealized PnL
- Open positions with unrealized PnL, leverage, margin type
- Open orders list
- Order placement: market, limit, with optional TP/SL
- Cancel single order, cancel all orders
- Close position (market, reduceOnly)
- Set leverage per symbol
- Set margin type (ISOLATED only)
- Live klines chart (lightweight-charts, initialized from server-proxied `/api/v1/trade/klines`, updated via Binance WS)
- Live orderbook (depth20@100ms stream, with fallback key handling for `asks`/`a`, `bids`/`b`)
- Live recent trades stream
- Order history, execution history, transaction history (all paginated)
- Symbol lock system: a symbol locked by a bot cannot be manually traded; a manually-locked symbol blocks bot entry
- All orders target Binance Testnet
- **Real-time account/order state via WebSocket** (`useTradeStream()`, 2026-07-02): a per-user Binance User Data Stream pushes order/account changes instead of relying on high-frequency REST polling — see `workspace/docs/features/live-trading/SPEC.md` and `DECISIONS.md` #20.

### Algo Trading (Bot Sessions)
Live multi-symbol bot sessions against Binance Testnet, candle-driven execution through the same
five-model pipeline as backtest, self-healing exchange-state reconciliation, OUO SL/TP safety nets,
a dynamic pairlist pipeline, per-symbol leverage clamping, and Chaos Mode multi-strategy stress runs.
**Detail moved 2026-07-02 to** `workspace/docs/features/algo-trading/SPEC.md` (Data Flow, Exchange
State Reconciliation, SL/TP & OCO Safety, Dynamic Pairlist & Symbol Management, Chaos Mode,
Resilience & Stats sections) — this bullet is a pointer, not a description.

**2026-07-15 additions (Plan 5 + Plan 12 + Plan 20 — not yet folded into the SPEC doc above):**
- **Execution event log**: append-only `executionEvents` Mongo collection
  (`engine/services/event_log.py`), engine-written at every position-mutating point (entry, DCA
  add, exit, close-failed, reconcile-adjustment), seq-ordered per `(session, symbol)`. Node's
  `handleEngineStats` rejects a stale/out-of-order seq for the same symbol. Additive — the live
  session's in-memory state and `LiveSession` document remain the actual read path.
  **2026-07-18 (Plan 5 Step 5.6, scoped):** `services/event_log.fetch_events()` +
  `core/live_bot_manager._seed_pnl_from_event_log()` can replay a session's own event log to
  recover realized PnL from trades that closed before a restart (currently-open positions already
  self-heal via the existing exchange-reconcile Case 1). Wired behind an opt-in `resume: bool`
  on the session-start request, and `server/src/services/reconciliation.js` now has a matching
  `RESUME_SESSIONS_ON_RESTART` env toggle (default `false`/unset) that calls it for orphaned
  `running`/`starting` sessions instead of the default stop+flatten sweep. Default is
  unchanged/off — whether to flip that default per-deployment is left as the user's own call, not
  made here. See `workspace/plan/5_live-trading-state-integrity.md`.
- **2026-07-18 (Plan 5 Step 5.5, ENG-11, scoped):** money math at every RUNNING-TOTAL
  accumulation point (`strategy.balance`, `available_capital`, cumulative fees/funding, live
  `session["pnl"]`, Node's cross-trade-record `computeSymbolStats` aggregation) now goes through
  Decimal (`engine/core/money.py`'s `add_money()`; Mongo's `$toDecimal`/Decimal128 instead of
  `$toDouble`) instead of raw float `+=`/`$sum` — stops the classic compounding-float-noise drift
  across many additions. Deliberately NOT a full float→Decimal conversion of every price/qty
  touch point (`Position.pnl`/`.margin`, candle prices, `liquidation_price` stay float — one-shot
  computations, no accumulation-drift problem to fix, and converting them would ripple Decimal
  into the hot candle-replay loop for a real performance cost with no accounting benefit). See
  `workspace/plan/5_live-trading-state-integrity.md`'s 5.5 section for the full scope rationale.
- **Real fills, not fabricated closes**: every close/entry-booking site now reads the actual
  Binance fill (`avgPrice`) instead of a pre-trade price estimate; a failed close order leaves
  the position open instead of fabricating a close. Entry orders gained idempotency (client
  order ID + re-query-before-retry on a raised exception).
- **Per-symbol locking**: an `asyncio.Lock` per `(session, symbol)` serializes the candle-loop
  and user-data-stream fill callback, closing a double-close/double-count race.
- **Session-level max open positions**: optional `maxOpenPositions` on session start caps
  concurrent open symbols in live/chaos sessions (freqtrade `max_open_trades` equivalent); unset
  = unlimited (default, unchanged behavior).
- **DCA scale-out precision**: partial-reduce quantities are now floored to the symbol's Binance
  `stepSize` before submission (previously unclamped — a live rejection risk once any strategy
  implements `adjust_trade_position()`, none do yet).

**2026-07-17 addition (Plan 22 Step 22.1 — Session Risk Governor, shipped code-side):**
- **Session Risk Governor** (`engine/core/models/governor.py`): a new session-scoped (not
  per-symbol) risk component, `session["risk_governor"]`, mirroring `ProtectionManager`'s
  interface pattern. Evaluated pre-trade in `execute_entry` (after A-001/A-002/A-003, can veto an
  entry) and periodically in `_push_stats` (can auto-transition `trading_state` to `reducing` or
  `halted`, edge-triggered). Three fail-closed hard checks: aggregate session drawdown
  (`max_session_dd`, default 0.20 — supersedes the old per-symbol-slice-only drawdown, Plan 21
  finding A-10), daily realized loss limit (`max_daily_loss_pct`, off by default, UTC-midnight
  anchor), and margin utilization ceiling (`max_margin_utilization`, default 0.8, pre-trade only).
  Config resolves via `risk_params.max_session_dd` (existing knob) plus a new
  `risk_params.governor` sub-object for the governor-only keys. `auto_flatten_on_halt` is opt-in,
  default off (`DECISIONS.md` #23) — force-closes every open position via the existing
  `_close_position_on_stop` when a `halted` transition fires and the flag is set.
- **Capital integrity gate** (B-11/B-12): two layers. Server-side (`startSession`/`startChaos` in
  `algo.controller.js`, via new `server/src/utils/capitalGate.js`) hard-rejects non-numeric/
  zero/negative capital always, and warns+requires `confirmOverCommit` when
  `requestedCapital + Σ running sessions' capital > available testnet balance` (Chaos multiplies
  by strategy count). Engine-side (`start_session` in `live_bot_manager.py`, via
  `_fetch_available_balance`) is a best-effort defensive backstop — clamps and logs if the server
  check was bypassed, never blocks on a failed balance fetch.
- **`risk_breach` webhook event**: new `Settings.webhook.events` enum value (opt-in by default).
  `handleEngineStats` persists the new `tradingState`, emits `algo:session:update` +
  `algo:session:log`, and dispatches the webhook.
- **Portfolio open-risk budget + liquidation buffer (22.2, shipped 2026-07-17)**:
  `SessionRiskGovernor.check_portfolio_risk()` — the TRUE cross-symbol Σ `|entry−stop|×qty` /
  equity, vetoing past `max_portfolio_risk` (default 0.06, same field name the pre-existing
  per-symbol `DefaultPortfolioModel` check used — kept for config compat, superseded for live
  sessions specifically). `respects_liq_buffer()` (previously decorative, zero call sites) is now
  wired into `execute_entry` too, vetoing with the computed liquidation price in the log.
- **Protections parity + risk-integrity events (22.3, shipped 2026-07-17)**: new
  `MaxDrawdownProtection`/`LowProfitPairsProtection` (`core/models/protections.py`, opt-in,
  freqtrade-inspired). Fixed a real gap while wiring them: `record_trade_close` previously only
  fired from `execute_exit` — the F-018 emergency-exit path, `_close_position_on_stop`, and
  `_reconcile_exchange_state`'s Case 2 never fed the protections stack, meaning `StoplossGuard`
  was blind to most exchange-side stoploss closes (the path A-13 made dominant). All four close
  paths now feed it. Chaos sessions confirmed already covered (same `start_session` path as
  regular live — no separate Chaos plumbing exists). New per-entry `risk_check` event
  (`executionEvents`) records resolved limits + computed sizing + the minNotional inflation
  factor; a session-visible warning fires when that factor exceeds 1.1×.
- **Live VaR/CVaR enforcement (22.4, shipped 2026-07-17)**: new `engine/services/
  portfolio_risk.py` — the single shared computation both the Zone 1 dashboard
  (`routers/risk.py`, now a thin formatter) and the live governor use (`compute_var_cvar`,
  wrapping the pre-existing `utils/risk_math.calculate_portfolio_var`), with 10s account-fetch /
  60s price-history caching. Account-wide by design (not session-scoped) — Binance's real
  margin/liquidation risk is account-wide, shared across every session on one key (Chaos runs
  dozens per key); scoping to one session's positions would diverge from the dashboard's number.
  `SessionRiskGovernor.check_var()` adds `var_limit_pct`/`cvar_limit_pct` (both default `None` =
  off, fully opt-in unlike the other governor checks' "0 disables" convention), evaluated
  pre-trade (`execute_entry`, after 22.2's checks) and periodically (`_push_stats`, alongside
  `check_periodic`) — fails open on a fetch/compute exception (external network call, same
  precedent as 22.2's liq-buffer check), routes a breach through the existing `risk_breach`
  webhook (no new webhook plumbing). Zone 2 schema/UI for `varLimitPct`/`cvarLimitPct`
  deliberately deferred to 22.7 (batched with the plan's other new-field UI work, per 22.7's own
  scope) — engine-side config keys are live now via `risk_params.governor.var_limit_pct`.
- **Correlation-aware concentration cap (22.5, shipped 2026-07-17)**: new
  `SessionRiskGovernor.check_correlation_concentration()` — pre-trade only, off by default
  (`risk_params.governor.correlation_cap.rho`, `None` = off). Transitive-closure clustering over
  pairwise |correlation| > `rho` among open positions + the candidate entry; vetoes when the
  cluster's combined notional exceeds `max_cluster_exposure_pct` (default 0.4) of equity. New
  `services/portfolio_risk.fetch_correlation_matrix()` reuses the existing 60s close-price cache.
  Fails open on a TimescaleDB fetch/compute exception.
- **Portfolio allocation layer (22.6, shipped 2026-07-17, golden-master-gated)**: new
  `InverseVolatilityPortfolio`/`compute_realized_volatility()` (`core/models/portfolio.py`) —
  weights ∝ 1/realized-vol with an iterative floor/cap clamp, config-gated via
  `risk_params["allocation"] == "inverse_vol"` (default `"equal"`, byte-identical to pre-22.6 —
  confirmed via `scripts/golden_master.py`, 5/5 seeded strategies unchanged). Wired into both
  `backtest_runner.py` (recomputes `capital_splits` after candles load) and
  `live_bot_manager.py`'s `start_session` (fetches recent close prices via the shared
  `portfolio_risk.py` cache; falls back to equal split on any failure).
- **Zone 2 platform surface (22.7, shipped 2026-07-17)**: `Settings.js`'s `globalHardLimits`
  gained the Session Risk Governor knobs (`maxDailyLossPct`, `maxMarginUtilization`, `varLimitPct`,
  `cvarLimitPct`, `correlationCap`, `allocation`, `breachAction`, `autoFlattenOnHalt`), a new
  "Session Risk Governor" form section in the Risk Dashboard, an allocation dropdown in the New Bot
  wizard (multi-symbol only), and a governor-state badge on `SessionCard.jsx` (Reducing/Halted,
  fed live via the `algo:session:update` socket event). **Plan 22 is now fully shipped
  (22.1–22.7)** — only live Testnet re-verification remains across the whole plan.

### Order History (Trade Recorder)
- Engine writes every completed round-trip trade to MongoDB `tradeRecords` collection via `engine/services/trade_recorder.py → record_trade()` (best-effort, never blocks the position-close path). Called by both `live_bot_manager` close paths (normal close + session stop).
- Server reads via `GET /api/v1/order-history` (Mongoose `TradeRecord` model). Supports filters: `symbol`, `source` (bot|manual), `side`, `executedBy`; paginated (default 50, max 200); sorted by exitTime DESC.
- Client: `client/src/pages/OrderHistory.jsx` — paginated trade log table with source/side badges. Hook: `client/src/hooks/useOrderHistory.js`.
- Data ownership: engine writes exclusively (`tradeRecords`); server reads only.

### Technical Indicators (engine/indicators/) — pluggable backend
- **Implemented:** `ema`, `sma`, `rsi`, `atr`, `donchian`, `macd`, `bollinger_bands`, `adx`, `stochastic`, `mfi`, `obv`, `pivot_high`, `pivot_low` (the last two are library-agnostic swing-pivot detectors — TradingView `ta.pivothigh`/`pivotlow` — usable on any candle column; the shared `_compute_pivots` primitive also detects pivots on arbitrary indicator series)
- All indicators: `sequential=False` (default, returns latest float / tuple of floats), `sequential=True` (full NaN-padded array / tuple of arrays)
- **Pluggable provider architecture** (DECISIONS.md #12): strategies call the convenience functions (`import engine.indicators as ta`); calls route through a swappable `IndicatorProvider`. **TA-Lib** is the default backend; **pandas-ta** is a pure-Python fallback (optional dependency, lazily imported). Switch the whole engine with `ENMA_INDICATOR_LIBRARY=talib|pandas_ta`; if the chosen backend fails to load, the engine auto-falls-back (`ENMA_INDICATOR_FALLBACK`, default on). No strategy changes needed to swap libraries.
- **SMA robustness** (`talib_adapter.py`): `sma()` now wraps the TA-Lib call in try/except; if `period > data_length` (or any other error), returns `np.full(shape, np.nan)` for sequential mode or `np.nan` for scalar mode — avoids crashes during warmup.
- Files: `base.py` (interface + convenience fns), `config.py` (backend selection), `adapters/talib_adapter.py`, `adapters/pandas_ta_adapter.py`

### Risk Model & Strategy Execution Refinements
`AtrBracketRiskModel` supports optional trailing stop / breakeven move / ATR-percentile veto (all
default-off); a portfolio exposure cap (`max_portfolio_risk=0.06`) is active by default.
**Correction 2026-07-16:** the cost gate (`min_edge_mult=0.05`) previously described here as
"active by default" has in fact **never fired** — the value is injected onto `cost_model` but the
gate reads `portfolio_model.min_edge_mult` (default 0.0). The gate is dead code today, and its
edge-vs-cost formula is also dimensionally inconsistent. See
`workspace/plan/21_live-algo-industry-standard-audit.md` findings M-1/M-2 (fix routed to Plan 9
step 9.11, golden-master-gated). Strategies precompute indicators once in
`prepare()` (both backtest and the rolling live window), leaving `before()` as a pure index lookup —
replaces the former O(N²) per-candle recompute. **Rationale + verification detail moved 2026-07-02 to**
`workspace/docs/core/DECISIONS.md` #18–19 — this bullet is a pointer, not a description.

### Parameters, Optimization & Strategy Mechanisms
Typed self-validating strategy parameters (reject, don't clamp, out-of-range overrides), a grid-search
parameter optimizer, and shared backtest/live position-adjustment (DCA) + entry/exit tagging through
the unified `ExecutionKernel`. **Detail moved 2026-07-02 to**
`workspace/docs/features/backtest-pipeline/SPEC.md` (Execution & Risk Mechanics, Optimization
sections) — this bullet is a pointer, not a description.

### UI / Navigation
- 6 nav pages + OrderHistory (at `/order-history`, not in navbar): Dashboard, Strategies, Backtest, Live Trading (Trade), Algo Trading, Settings
- Horizontal top navbar — no sidebar
- Active nav state: `text-emerald-400`, `bg-emerald-500/10`, `border-b-2 border-emerald-500`
- Dark theme throughout (`bg-gray-950` base)
- All financial P&L: `emerald-400` (profit) / `red-400` (loss)

### UI Polish & Hardening (Phase 2, 2026-06-2x)
Toast notifications (`react-hot-toast`) across Settings/Strategy/Backtest/Algo actions; ARIA/a11y
sweep (labels, roles, `aria-pressed`/`aria-busy`/`aria-expanded`); background-polling status dots;
client-side table sorting (`useTableSort` + `<SortableHeader>`); `<EmptyState>` replacing placeholder
text across Trade/Backtest/Strategies/Admin. Condensed 2026-07-02 — component-level detail lives in
git history, not here.

### UI Polish & Responsiveness (Phase 3, 2026-06-2x)
`SessionCard.jsx` equity fetch moved to TanStack Query; TP/SL and Leverage overlays converted to
Radix `<Dialog>`; lazy-loaded heavy sub-components; shared `<Badge>`/`<Card>`/`<Button>` design-system
sweep across `StrategyCard.jsx`/`AdminPanel.jsx`/`Settings.jsx`; responsive tab-bar layout on
`Trade.jsx` below `1024px`; responsive grid columns on backtest/wizard forms. Condensed 2026-07-02 —
component-level detail lives in git history, not here.

---

## Verified Baselines

Golden-master and regression verification runs for major refactors — condensed 2026-07-02, full
detail (commands, per-phase byte-equivalence, issue-by-issue fix list) moved to
`workspace/docs/core/DECISIONS.md` → "Verification Appendix" as historical record.

- **Narang Black-Box Refactor** (2026-06-21): golden comparison passed for all 5 seeded strategies; boundary suite 20/20.
- **Strategy Performance Refactor** (`prepare()`/`before()` split, 2026-06-24): all 6 phases gated on golden-master byte-equivalence; boundary suite 20/20; one latent pandas-2.x epoch-conversion bug found and fixed (BestSupertrend HTF bucket mapping).
- **Standardise Implementation Audit** (2026-06-25): 13 issues found and fixed across exec-algo slicing, pairlist filters, metric definitions, and reconciliation; engine unit suite 81/81; single-symbol backtests confirmed byte-identical post-fix.

---

## Planned / Not Yet Implemented

| Feature | Notes |
|---------|-------|
| **Mainnet trading** | Deliberately not implemented. Mainnet is **read-only balance display** only (Dashboard `AccountOverview`, 2026-07-02); `X-Binance-Mode` is pinned to testnet on all trade routes. Enabling real-money order routing is out of scope. See DECISIONS.md §9. |
| **Multi-exchange support** | Binance only. |

---

## Known Technical Debt

- **FIXED 2026-07-19 (found in live testnet chaos) — emergency-close `clientOrderId` exceeded
  Binance's 36-char limit (`-4015`).** The F-018 emergency-close order id
  `enma_{session_id[:8]}_{symbol}_{uuid4_hex8()}_emrg` was 37 chars for a 9-char symbol (e.g.
  KAITOUSDC), so the emergency MARKET close FAILED with `-4015 Client order id length should be less
  than 36 chars` on every symbol ≥8 chars (mitigated, not catastrophic, by the A-7 re-arm next
  candle). Was systemic: the base `enma_{session_id[:8]}_{symbol}_{uuid4_hex8()}` scheme also risked
  36 for ~13-char symbols. **Fixed** with a central `_make_client_id(session_id, symbol, suffix="")`
  (`live_bot_manager.py`) that budgets ≤35 chars, keeping as much of the cosmetic symbol segment as
  fits (nothing parses the symbol back out — only `.startswith("enma_"/"tpsl_"/"oco_")` matters);
  applied to all 6 `enma_…` sites. `engine/tests/test_make_client_id.py` (6 cases incl. the exact
  regression); engine pytest 450/450. Change is in the working tree (uncommitted) pending commit.
- **FIXED 2026-07-19 (found in live testnet chaos) — blank Session-Risk-Governor fields silently
  armed circuit breakers at 0, blocking ALL live entries.** `server/src/utils/risk.js` used
  `isFinite(Number(hardLimits.correlationCap?.rho))` etc.; the client sends `null` for a blank "off"
  field, and `Number(null)===0` (also `Number('')===0`) slipped past `isFinite`, arming
  `correlation_cap` at `rho=0` ("cluster everything") and `var_limit_pct`/`cvar_limit_pct`/
  `max_margin_utilization` at 0 (the engine treats 0 as a real limit; only `None`/`""` = off). Live
  effect: 28 correlation-governor entry vetoes / 0 clean entries at 50x. **Fixed** with an `_optNum`
  guard (null/undefined/'' → omit; explicit 0 still honored); +5 regression tests; server jest
  116/116. Live-confirmed: post-fix chaos = 0 correlation blocks, entries flow. Change is in the
  working tree (uncommitted) pending review/commit.

- **Fixed 2026-07-17 (Plan 24, S-1 through S-4) — BestSupertrend silently never traded at its own
  default settings.** Root cause: `size_by_notional()` (`core/strategy.py`) sized to exactly
  `equity * position_size_pct` capped only by leverage-based `max_qty()` — at the strategy's
  default `position_size_pct=1.0` and the platform's default `leverage=1`, this always sat exactly
  on the equity boundary, so adverse slippage + the taker fee alone pushed `req_margin + fee` just
  over `free_balance`, rejecting **every single entry** with only a debug-level log line
  (`"Entry rejected: margin + fee exceeds free capital"`) users never saw. Fixed: `size_by_notional()`
  now sizes DOWN to the true affordable notional instead of letting the runner reject the entry
  outright (S-1); `position_size_pct` default lowered 1.0→0.9 (belt and braces). Also fixed while
  auditing the same strategy: live's HTF supertrend read one bar more stale than backtest (`tsl[-2]`
  vs the correct `tsl[-1]` — S-2); structurally unsatisfiable `tf`/timeframe combos (e.g.
  `tf="weekly"` on a short date range) now fail loud with a session-visible error instead of
  silently zero-trading forever (S-3, new `required_base_candles_for_htf()` in
  `utils/timeframes.py`); the `order_type` param was renamed to `direction_filter` after it was
  found to collide with and silently override `OrderPlan.order_type` (S-4). Golden master
  re-baselined for S-1 (only BestSupertrend diverges — same 61 trades/win-loss structure as
  before, PnL scaled by the smaller position size; the other 4 seeded strategies are byte-identical
  since `size_by_notional` has no other caller). Container suite 353/353 passed. **Not yet
  confirmed against a real live Testnet session** — see `24_bestsupertrend-fixes.md`.
- **Live bot PnL on exchange_sync exits — partially fixed 2026-07-17 (Plan 21.1, A-1)**: when Binance closes a position via SL/TP and the engine detects it via reconciliation, `_query_real_exit_from_user_trades()` calls `GET /fapi/v1/userTrades` to reconstruct the real exit price/PnL from Binance's own trade history. This call previously omitted its required `api_key`/`api_secret` arguments — a `TypeError` on every invocation, swallowed by the surrounding `except Exception`, always returning `None` — so every `exchange_sync` close silently fell back to the candle/SL-TP estimate. **The credentials are now passed** (see `21_live-algo-industry-standard-audit.md` A-1); regression tests added in `engine/tests/test_query_real_exit_from_user_trades.py`. Not yet confirmed against a real live session's Binance trade history — do that before closing 21.1 fully.
- **Live bot entry fee not tracked**: `session["pnl"]` only deducts the exit fee per trade. Entry fees paid to Binance are not subtracted locally, so session PnL overstates profits by one taker fee per round-trip. Acceptable approximation for now.
- **Resolved 2026-07-02 (see DECISIONS.md #20)**: the Trade page's `open-orders`/`positions`/`account` REST polling (previously 30s/3s/10s, dominated by an un-symbol-filtered `open-orders` call costing 480 weight/min on a budget shared across all users via the server's single outbound IP) is now backed by a per-user Binance User Data Stream (`engine/services/manual_trade_stream.py`) with REST reduced to a 90s/30s/60s safety net.
- **CONFIRMED 2026-07-16 (fixes-queue F7, live Chaos run against Binance Testnet) — algo/conditional
  order fills are NOT reliably caught by the real-time WS path.** BSBUSDT and ESPORTSUSDT both
  closed via their conditional SL/TP within single-digit seconds of opening (per Binance's own
  Order History), but Enma's session UI kept showing both as open for ~50-55 more seconds until
  the next 1m candle-close drove the per-loop REST reconciliation poll, which is what actually
  caught and closed them — not the user-data-stream fill callback (F-020). **This means every
  live/chaos session currently carries up to ~60s where the UI and the strategy's own in-memory
  position state say a symbol is open when Binance has already closed it.** **Root cause isolated
  and code-fixed 2026-07-17 (Plan 21.1, A-2):** `_on_fill`'s client-id lookup read a non-existent
  `clientOrderId` key and fell back to the numeric `orderId` (an int), so `.startswith("tpsl_")`
  raised `AttributeError` on every genuinely-delivered FILLED/PARTIALLY_FILLED frame — caught by
  the outer per-callback try/except, which meant `_reconcile_exchange_state()` at the end of
  `_on_fill` never ran. The event-driven fill path was dead code even when Binance emitted the
  event; every close silently waited for the next candle-close REST poll instead. Fixed by reading
  the real `"c"` field (str-coerced) via the new `_extract_fill_client_id()` helper, and by
  wrapping the OUO peer-cancel block in its own try/except so the reconcile call can no longer be
  skipped by a failure earlier in the callback. **A second, independent backstop shipped the same
  day (Plan 21.2, A-8):** a per-symbol `_on_account_update` callback now reconciles immediately on
  any OPEN<->FLAT disagreement between Binance's `ACCOUNT_UPDATE` position delta and the local
  view — this path is event-type-agnostic (Binance emits `ACCOUNT_UPDATE` for every position
  change, including algo-order fills, regardless of `ORDER_TRADE_UPDATE` semantics), so it closes
  the staleness window even if A-2's `ORDER_TRADE_UPDATE` fix turns out to have gaps. **LIVE-VERIFIED
  FIXED 2026-07-19** against a real testnet chaos run: a conditional SL fill on KAITOUSDC (50x) was
  reflected in local state in **~0.5s** (fill 08:11:02.177 → `_on_account_update` fired immediately
  → "reconciled — exchange has no position, closing local state" 08:11:02.677), versus the original
  ~60s. Container pytest 444/444 (F7's 3 `test_entry_unconfirmed_fill.py` cases pass). **The F7
  staleness symptom is resolved.** Detail + full timeline:
  `workspace/docs/features/algo-trading/SPEC.md`'s "Open issues found in a live Chaos run" section,
  `21_live-algo-industry-standard-audit.md` (A-2, A-8), and `workspace/plan/handoff.md` (2026-07-19).
- **ROOT-CAUSED 2026-07-19 (live testnet chaos) — SL/TP placement `400 Bad Request` = `-2021 Order
  would immediately trigger`.** The `_binance_error_detail()` logging (added earlier, now
  container- and live-verified) captured the real body: at high leverage the SL/TP trigger price
  sits within immediate-trigger range of the mark price (~0.03% at 50x), so Binance rejects it.
  **The prior `PERCENT_PRICE` / stale-tick-size hypotheses are DISPROVEN — do not pursue them.**
  This is expected exchange behavior at extreme leverage + tight stops, and **self-heals**: the
  Plan 21.4 A-7 naked-position re-arm re-places the stop on the next candle (once price has moved
  off the trigger), verified live (KAITOUSDC: SL-400 at entry → re-armed successfully next candle
  → SL later triggered normally). Not a code bug on its own; the residual real bug found alongside
  it is the `-4015` emergency-close client-id overflow (below).
- **Fixed 2026-07-17 (Plan 21.3/21.4, A-4/A-5/A-6/A-7/M-4/M-5)** — bracket/SL integrity gaps found
  by the `21_live-algo-industry-standard-audit.md` audit, all code-side shipped, pending container
  `pytest` run + live re-verification: (1) resting SL/TP algo orders are now cancelled on every
  close path (`execute_exit`, `_close_position_on_stop`, the emergency-exit path, and reconcile
  Case 2) via `_cancel_symbol_algo_orders()` — previously only the OUO peer-cancel covered the
  in-band close case, leaving orphaned conditional orders on the other three paths (A-4/A-5); (2)
  the F-018 emergency-exit path (entry filled, SL placement failed) now retries the market close up
  to 3x with backoff and books the real fill price instead of fabricating `exit_price = fill_price`,
  and records nothing on total failure rather than falsely marking a still-open, still-naked
  position as closed (A-6); (3) reconcile now detects a position with no live exchange stop and
  re-arms it, force-closing after 3 consecutive failures instead of running naked indefinitely
  (A-7); (4) a tightened trailing/breakeven stop (`DefaultExecution.route()` Path 5) is now pushed
  to the exchange via cancel+replace instead of staying local-only for the position's entire life
  (M-4); (5) an entry whose SL lands on the wrong side of the fill price is now rejected outright
  instead of silently entering naked on that leg (M-5).
- **Partially fixed 2026-07-17 (Plan 21.5, A-9 + A-15)** — `send_signed_request`
  (`engine/services/binance_testnet.py`) had no awareness of Binance's shared 2400-weight/min
  budget and no 429/418 handling. Now tracks `X-MBX-USED-WEIGHT-1M` per base_url and defers
  non-order-critical calls once at/above a 1800 (75%) soft limit while the reading is fresh; on an
  actual 429/418 it honors `Retry-After` and pauses non-order-critical calls until it expires.
  `/fapi/v1/order`/`/fapi/v1/algoOrder` are exempt from both guards. **Not shipped:** batching
  `positionRisk`/`openAlgoOrders` into one call per session per candle wave instead of
  N-per-symbol — needs a larger concurrency restructure of `_run_symbol_loop`, deferred. **Found
  and fixed while shipping this (A-15, High):** `_reconcile_exchange_state`'s Case 2 was
  fabricating a real position close whenever the `positionRisk` query merely *failed* (network
  blip, timeout, missing credentials, or now a deliberate A-9 backpressure defer) — it read the
  failure's `0.0` default the same as a confirmed-flat exchange. A `position_query_ok` flag now
  gates Case 2 so an unconfirmed query leaves local state untouched, retrying next candle, instead
  of falsely closing a position that may still be open. Tests:
  `engine/tests/test_binance_backpressure.py` (18 cases — actually run with real pytest this
  session against a fake httpx client, not just syntax-checked, since this module has no
  TA-Lib/numpy dependency chain).
- **Fixed 2026-07-17 (Plan 21.7, A-11 + A-14)** — both logging-only additions, no golden master
  needed: `clamp_and_round_qty` (`engine/utils/symbols.py`) now warns when its minNotional
  bump-up actually inflates a trade's quantity (and therefore realized risk) beyond target,
  logging the effective multiplier; `execute_entry` now measures and logs slippage between the
  closed-candle `ref_price` and the real fill on every entry, escalating to a warning + session
  notification at/above a 1% threshold. Neither changes any returned value or trading decision.
  A-12 (mainnet/testnet data-provenance splice) and A-13 (engine-side wick-check vs armed exchange
  brackets) remain open — both need a product decision recorded in `DECISIONS.md`, not code.
- **OPEN 2026-07-16 — a position (`FXSUSDT SHORT`) stayed shown as open after a full session stop**,
  same live run. **Investigated by code read 2026-07-18** (no Docker access that session — see
  `0_fixes-queue.md` F7's 2026-07-18 entry): `stop_session()`'s close loop and
  `_close_position_on_stop()` are correct by inspection (force-close every session symbol against
  live `positionRisk`, regardless of local state). **One real gap found and fixed**: `execute_entry()`
  treated Binance's `"0.00000000"` avgPrice string as a truthy real fill, which could silently open a
  local position never confirmed against a real Binance fill — the one order-placement site that
  hadn't been brought under the ENG-2 "never fall back to an estimate silently" contract already
  applied to every close path. Now re-queries by clientOrderId and rejects the entry (no local
  position opened) if still unconfirmed. New tests: `engine/tests/test_entry_unconfirmed_fill.py`
  (3 cases). **Not yet confirmed as the actual FXSUSDT cause** — needs a live Testnet reproduction
  or the original session's retained logs; this is a defensible hardening fix for a real code gap,
  not a verified match. Container pytest run and live re-verification both still pending (blocked on
  Docker access).

---

## Current Constraints

| Constraint | Detail |
|-----------|--------|
| Binance Testnet rate limits | Weight-based (2400/min), shared across ALL users via the server's single outbound IP. Trade page mitigates this via a WebSocket User Data Stream (F-020 pattern reused), not high-frequency REST polling — see `ARCHITECTURE.md` rule 5. |
| Multi-user, open login + algo gate | Google OAuth + JWT cookie; login open to all. `userId` scopes all mutable models (see Auth section above). Strategies stay global — no `userId` on `Strategy`. Algo Trading start actions gated per-user via `requireAlgoAccess`. |
| TA-Lib | Compiled inside Docker container — never install on host |
| No paper trading simulation | "Paper trading" = Binance Testnet; no internal order simulation |
| TimescaleDB isolation | Server never connects to TimescaleDB; all candle data comes via engine HTTP |
