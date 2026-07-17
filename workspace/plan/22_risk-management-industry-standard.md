# 22 — Industry-Standard Risk Management for Algo Trading (consolidated + refined)

**Status:** Ready (scope decisions taken 2026-07-16, implementation unstarted)
**Created:** 2026-07-16 · **Priority:** P1 (22.1–22.3), P2 (22.4–22.7)
**Refines and consolidates:** `ref_gap-matrix-freqtrade-nautilus.md` §1.6 (Risk Management rows),
`ref_future-paths.md` Track D + strategic forks #2/#3, `12_max-position-per-asset.md` (shipped —
this plan is its continuation), Plan 21 step 21.6 (A-10 — **folds into 22.1, don't do it twice**),
`workspace/docs/features/risk-dashboard/SPEC.md` (Zone 2 cascade becomes the config surface).

**Scope decisions taken by the user 2026-07-16** (resolves ref_future-paths forks — update that
file when this ships):
- **Fork #3 (portfolio abstraction): YES** — include a portfolio-level allocation + risk layer.
- **Fork #2 (classical vs ML): rule-based only** — no GARCH/regime-ML in this plan;
  vol-forecasting stays in the exploration backlog. (Realized-vol *rules* are in scope; fitted
  models are not.)
- **VaR/CVaR enforcement: YES** — Risk Dashboard Zone 1 metrics graduate from display-only to
  enforced limits in live algo sessions.

---

## Part A — What already exists (build on this, don't duplicate it)

| Layer | Exists today | File |
|---|---|---|
| Per-trade stop/bracket | ATR bracket, chandelier trail, breakeven move, ATR-percentile veto, signal-exit variant | `core/models/risk.py` |
| Position sizing | `size_by_risk` (risk-% of equity / stop distance), notional sizing, `max_qty()` leverage cap | `core/strategy.py` |
| Per-symbol caps | `max_exposure_notional` (Plan 12 1a), leverage clamp vs `leverageBracket`, F-014 hard floors (`risk_pct ≤ 0.20`, `max_session_dd ≤ 0.90`, leverage ≤ 125) | `live_bot_manager.py`, `utils/symbols.py` |
| Session caps | `max_open_positions` (Plan 12 1b), manual `trading_state` kill-switch (`active`/`reducing`/`halted`) | `live_bot_manager.py` |
| Protections | `CooldownPeriod`, `StoplossGuard` (freqtrade-style, per-session) | `core/models/protections.py` |
| Config cascade | Zone 2 `globalHardLimits → strategyOverrides → symbolOverrides` resolver, applied at live/chaos/backtest launch | `risk-dashboard/SPEC.md`, server resolver |
| Portfolio analytics (display) | Live VaR/CVaR (95/99), correlation heatmap, net exposure, margin gauge; MC bootstrap; leverage-sensitivity | `routers/risk.py`, `services/monte_carlo.py` |
| Drawdown breaker | `can_trade()` per strategy instance (per-symbol slice) | `core/models/risk.py` |
| Launch limits (per bot / new bots) | `limits.testnet.maxSymbolsPerBot` (default 15, max 30) and `maxConcurrentBots` (default 10, max 20) enforced server-side on **both** normal-session and Chaos start; Chaos additionally capped by `chaosMaxTotalSymbols` + `chaosMaxManualSymbols`; optional per-session `maxOpenPositions` | `algo.controller.js`, `Settings.js` |
| Risk-% per trade (parameter chain) | Wizard/API `riskPct` → server clamp (`utils/risk.js` mapping, min 0.0001) → Zone 2 cascading override resolver (`resolveStrategyRiskParams`, clamped to global hard limits — tested: an 0.5 override clamps to ≤ the configured max) → engine F-014 defensive floor `min(risk_pct, 0.20)` → `size_by_risk()` sizing. **This chain is genuinely parameter-controlled with three clamp layers — audited 2026-07-16, sound.** | `utils/risk.js`, `live_bot_manager.py`, `strategy.py` |

## Part B — Gaps vs industry standard (the refinement)

Findings from this pass, `[Certain]` unless noted:

- **B-1 · `liq_buffer_pct` is decorative.** `respects_liq_buffer()` is defined and smoke-tested
  (`scripts/_phase_smoke.py`) but **never called from the entry pipeline** — no call site in
  `pipeline.py`, `portfolio.py`, `kernel.py`, or the adapters. The Exchange-Settings
  "liquidation buffer" knob users can configure does nothing. Either wire it into the Risk→PCM
  path (veto/resize when the stop sits inside the buffer) or remove the setting; a decorative
  risk control is worse than none.
- **B-2 · `max_portfolio_risk` is misnamed — it's per-symbol.** `DefaultPortfolioModel` checks
  *this one position's* risk against *this symbol's equity slice*. Nothing computes cross-symbol
  aggregate open risk. True portfolio risk budget (sum of open risk-to-stop across symbols ≤ X%
  of session equity) is missing — the actual industry meaning of the term.
- **B-3 · No automatic session-level kill-switch** (= Plan 21 A-10). `max_session_dd` gates only
  per-symbol slices; `trading_state` is only tripped manually. No aggregate-equity watcher.
- **B-4 · No daily/period loss limit.** Standard prop-desk control (freqtrade `MaxDrawdown`
  protection + `max_daily_loss` conventions): halt entries for the rest of the UTC day (or a
  configured window) when realized session loss crosses a limit. Absent.
- **B-5 · Protections stack is 2 of freqtrade's 4.** Missing: `MaxDrawdown` (global lock on
  rolling-window drawdown) and `LowProfitPairs` (lock pairs that keep losing). Both fit the
  existing `IProtection` ABC directly.
- **B-6 · No margin-utilization ceiling.** Zone 1 *displays* locked-margin vs free balance;
  nothing stops a session from committing 100% of wallet as initial margin. Standard: cap total
  margin utilization (e.g. 60%) and block/resize entries beyond it.
- **B-7 · VaR/CVaR and correlation are display-only** (user decision: enforce). No pre-trade
  check consumes them; a session can stack 15 highly-correlated longs and the dashboard will
  beautifully visualize the concentration it did nothing to prevent.
- **B-8 · Capital allocation is equal-split only.** `DefaultPortfolioModel.allocate()` divides
  capital equally across symbols (live **and** backtest — shared code, golden-master-sensitive).
  No inverse-volatility / risk-parity weighting; Chaos round-robins symbols with no risk input.
- **B-9 · Risk-per-trade integrity leaks** (= Plan 21 A-11): minNotional bump-up can inflate
  realized risk to 1.3× `risk_pct`, unlogged. Also no per-entry risk snapshot is persisted, so
  post-hoc "what risk did the bot actually take?" analysis relies on reconstruction.
- **B-11 · Session `capital` is an honor-system number — never validated against the wallet.**
  `[Certain]` (audited 2026-07-16 on the user's direct question). `startSession` checks only
  *presence* (`!capital` → 400); there is **no numeric-bounds validation** (a non-numeric string
  crashes the engine's `float()` at session start; a negative value flows through) and **no
  comparison against the real Binance available balance** — the only "balance" reference in
  `algo.controller.js` is the equity-curve math. The engine never queries the account at
  `start_session` either: `strategy.balance = capital/n` is fiction the sizing math then trusts.
  The entry-time notional guard (`notional ≤ balance×leverage×1.05`) checks against this
  *configured* capital, not the wallet — so a bot configured with 10,000 on a 1,000 wallet sizes
  orders 10× too large and discovers it via Binance margin-rejection errors, not via risk
  control.
- **B-12 · No cross-session capital reservation — concurrent bots can commit multiples of the
  wallet.** `[Certain]`. `maxConcurrentBots` caps the *count* (10) but nothing sums committed
  capital across running sessions: 10 bots × 1,000 each = 10,000 "allocated" against whatever
  the wallet actually holds. **Chaos multiplies this**: each selected strategy gets its own full
  `capital` (`riskBody.capital ?? defaultCapital` *per strategy*), so a 15-strategy Chaos run
  commits 15× the entered capital with zero aggregate check. Overlaps Plan 8.6's
  multi-session-same-account product decision — B-12 is the engineering half (a reservation
  ledger) regardless of which way 8.6 decides.
- **B-10 · [Likely] Backtest/live risk-model state divergence** — audit_2 QNT-9:
  `AtrBracketRiskModel._atr_history` accumulates per-run in backtest vs per-session-lifetime in
  live, so the percentile veto behaves differently. Tracked in Plan 9's remit; noted here because
  it undermines "backtest-validated risk settings" claims. Not re-planned here.

## Part C — Target architecture: the Session Risk Governor

One new engine component, `engine/core/models/governor.py` — `SessionRiskGovernor`, owned by the
session (not per-symbol), evaluated at two points:

1. **Pre-trade** (inside `LiveAdapter.execute_entry`, after the existing A-002/A-001/A-003
   gates): every check below can veto or resize the entry.
2. **Periodic** (on each `_push_stats` tick, which already aggregates per-symbol state): breach
   of a *standing* limit auto-transitions `trading_state` → `reducing` (default) or `halted`
   (configurable), emits a Socket.IO banner + webhook (`risk_breach` event — extend Plan 14's
   event list).

Checks, each individually enable/disable-able via the Zone 2 cascade (all thresholds resolve
through the existing `symbolOverride > strategyOverride > globalHardLimits > default` chain):

| Check | Trigger point | Default | Gap |
|---|---|---|---|
| Aggregate session drawdown | periodic + pre-trade | on, `max_session_dd` (existing knob, now session-scoped) | B-3 |
| Daily realized loss limit | periodic + pre-trade | off (`maxDailyLossPct`) | B-4 |
| Portfolio open-risk budget | pre-trade | on, `maxPortfolioOpenRisk` = 6% (inherits the misnamed knob's default, now computed correctly across symbols) | B-2 |
| Margin utilization ceiling | pre-trade | on, `maxMarginUtilization` = 0.8 | B-6 |
| VaR budget | pre-trade + periodic | off (`varLimitPct`, 95% 1-day VaR ≤ X% of equity) | B-7 |
| Correlation-adjusted concentration | pre-trade | off (`correlationCap`: block a new entry when its 30-day ρ vs any open position > 0.8 **and** combined notional of the cluster > Y% of equity) | B-7 |
| Liquidation buffer | pre-trade | on, existing `liq_buffer_pct` (finally wired) | B-1 |
| Capital integrity gate | **session start** (server + engine) | on | B-11, B-12 |

Design constraints:
- **Engine-side, session-scoped, testnet-data-driven.** VaR/correlation math already exists in
  `routers/risk.py` — extract the computation into a shared service
  (`services/portfolio_risk.py`) consumed by both the dashboard route and the governor, so the
  numbers the user sees are the numbers being enforced. Cache per session (recompute at most
  every N candles / 60s) — do NOT add per-entry REST calls (respect Plan 21 A-9's weight budget).
- **Fail-open vs fail-closed is explicit:** if the governor cannot compute a metric (no data,
  stale cache), configurable per check — default: hard checks (drawdown, margin, open-risk)
  fail-closed (block entry), statistical checks (VaR, correlation) fail-open with a warning log.
- **The governor never places orders.** It vetoes entries and flips `trading_state`; position
  reduction under `reducing` remains the existing behavior (exits allowed, entries blocked).
  Auto-flattening (`halted` + force-close) is a per-user opt-in, not a default.

## Part D — Steps

All live-path work is golden-master-inert **except 22.6** (allocation touches
`backtest_runner.py`'s shared `allocate()` — must be config-gated, default = equal split,
byte-identical). Each step independently shippable, tests per the stubbed-Binance pattern.

### 22.1 — Session Risk Governor core (aggregate drawdown, daily loss, margin ceiling) + capital integrity gate · P1 · M

**Status: shipped code-side 2026-07-17** — pending container test run + live re-verification
(same pending-verification pattern as Plan 21's steps). All pieces below are implemented:
`engine/core/models/governor.py` (`SessionRiskGovernor`/`GovernorVerdict`, 18/18 unit tests
passing standalone, no numpy dependency); `server/src/utils/capitalGate.js` (pure functions,
manually verified — Jest suite written but not run, no `node_modules` in the dev sandbox);
`algo.controller.js`'s `startSession`/`startChaos` capital-gate wiring + new `handleEngineStats`
`risk_breach` branch; `live_bot_manager.py`'s `start_session` (governor instantiation, reusing
`risk_params.max_session_dd` + new `risk_params.governor` sub-object), `execute_entry` pre-trade
gate, `_push_stats` periodic check, `_apply_governor_breach`, `_compute_session_equity_and_margin`,
and all four `record_realized_pnl` feed sites (F-018 emergency exit, `execute_exit`,
`_close_position_on_stop`, `_reconcile_exchange_state` Case 2); `Settings.js`'s webhook `events`
enum now includes `risk_breach` (opt-in by default alongside `exit_fill`/`liquidation`/
`session_error`). Golden master **not** triggered (live-adapter/session-orchestration only, zero
backtest-path overlap). Six policy decisions this step depended on are recorded in
`DECISIONS.md` #23.

Governor skeleton + the three hard checks + auto `trading_state` transition + banner/webhook.
**Absorbs Plan 21 step 21.6** — mark it `Merged→22.1` in plan 21 when this ships.

**Capital integrity gate (B-11/B-12), start-time, both layers:**
- *Server* (`startSession` + `startChaos`): validate `capital` is a finite number > 0 within
  configurable bounds; fetch the account's available balance (the `/trade/account` path already
  exists) and reject — or warn-and-confirm, see Part F Q5 — when
  `requestedCapital + Σ capital of this user's running sessions > availableBalance`. For Chaos,
  the requested amount is `capital × strategyCount` (the per-strategy multiplication in B-12
  must be summed, not sampled).
- *Engine* (`start_session`): defensive re-check — query wallet balance once at start; if
  configured capital exceeds it, clamp `strategy.balance` slices to the real available amount
  (log + notify the delta). The engine check is the backstop; the server check is the UX.

Acceptance: a session breaching aggregate `max_session_dd` auto-sets `reducing` within one stats
tick, with a visible SessionCard state change and a `risk_breach` webhook; entries blocked while
`reducing`; unit tests for each check's veto and the fail-closed path. Capital gate: non-numeric/
negative/zero capital → 400 with a field error (never an engine crash); a request that would
over-commit the wallet across running sessions (incl. the Chaos multiplier) is rejected/warned
per the Q5 decision; engine clamps and logs when the server check was bypassed.

### 22.2 — Correct portfolio open-risk budget + wire `liq_buffer_pct` · P1 · S–M
Compute true cross-symbol open risk (Σ |entry−stop|·qty over open positions / session equity) in
the governor pre-trade check; deprecate the per-symbol misuse in `DefaultPortfolioModel` (keep
the field name for config compat, route it to the governor). Wire `respects_liq_buffer()` into
the pre-trade path (veto + log when the stop sits inside the liquidation buffer).
Acceptance: an entry pushing aggregate open risk past the budget is vetoed with a log naming the
contributing symbols; a stop inside the liq buffer vetoes with the computed liq price in the log.

### 22.3 — Protections parity + risk-integrity events · P1 · S–M
Add `MaxDrawdown` and `LowProfitPairs` protections (freqtrade semantics) to
`core/models/protections.py`, config via the existing `risk_params.protections` block; wire the
protections stack into **Chaos** sessions (currently live-only wiring — verify and close).
Risk snapshot on every entry: append a `risk_check` event to `executionEvents` (Plan 5.1 log)
recording resolved limits, computed values, and any resize (incl. B-9's minNotional inflation
factor — plus a warning log when realized risk > 1.1× intended).
Acceptance: protections lock/unlock visible in session log; every entry has a queryable risk
snapshot; inflation ≥ 1.1× emits a warning.

### 22.4 — Live VaR/CVaR enforcement · P2 · M
Extract Zone 1 math into `services/portfolio_risk.py` (shared dashboard + governor); add
`varLimitPct` (+ optional `cvarLimitPct`) to Zone 2 schema/validation/UI; governor consumes the
cached metric pre-trade and periodically. Breach → configurable `reducing` + webhook.
Acceptance: dashboard value and governor value provably identical (same function, one test);
breach demonstrably blocks a new entry in a stubbed session; 10s/60s caching bounds REST weight.

### 22.5 — Correlation-aware concentration cap · P2 · M
Reuse the rolling-correlation computation (same shared service); pre-trade check per Part C.
Cluster definition: transitive closure over pairwise ρ > threshold among open + candidate
symbols. Config: `correlationCap: { rho: 0.8, maxClusterExposurePct: 0.4 }` in Zone 2.
Acceptance: with two open BTC-correlated positions at the cluster cap, a third correlated entry
is vetoed (test with canned return series); uncorrelated entry passes.

### 22.6 — Portfolio allocation layer (fork #3) · P2 · M — **golden-master-gated**
`InverseVolatilityPortfolio` variant of `PortfolioModel.allocate()` (weights ∝ 1/realized-vol
over a configurable lookback, from warmup candles; pure rule-based per fork #2). Config-gated:
`allocation: "equal" | "inverse_vol"` on session start (wizard dropdown + Chaos settings);
**default `equal` — backtest and existing sessions byte-identical**. Chaos auto-allocation may
optionally consume the same weights for capital (not symbol counts) in a second pass.
PyPortfolioOpt/Black-Litterman adoption is explicitly **out of scope** — revisit as its own plan
if inverse-vol proves insufficient (keeps the Adopt decision reversible).
Acceptance: golden master unchanged with `equal`; `inverse_vol` weights sum to 1, respect a
per-symbol floor/cap, and are logged at session start; backtest supports the same flag for
apples-to-apples validation.

### 22.7 — Platform surface: Zone 2 fields, SessionCard risk state, docs · P2 · S–M
Zone 2 UI + server validation for all new fields (`maxDailyLossPct`, `maxMarginUtilization`,
`varLimitPct`, `correlationCap`, `allocation`, governor fail-mode toggles); SessionCard gains a
governor state badge (OK / breach-name / reducing / halted) fed from `_push_stats`; webhook
event docs (Plan 14 file); update `risk-dashboard/SPEC.md` ("display-only" invariant changes!),
`algo-trading/SPEC.md`, `CURRENT_STATE.md`, DECISIONS.md (fork resolutions), `engine/CLAUDE.md`
(new files), `ref_future-paths.md` (mark forks #2/#3 resolved, Track A/D rows updated).

## Part E — Sequencing & dependencies

```
21.1/21.2 (fill-path fixes) ──► 22.1 ──► 22.2 ──► 22.3
                                    └──► 22.4 ──► 22.5
                                              └──► 22.6 ──► 22.7 (docs land with each step; UI batch at end)
```

- **Do Plan 21 steps 21.1–21.4 first.** A risk governor on top of a fill path that misses closes
  for 60s and leaves stale brackets armed enforces limits against wrong state. Correct state
  first, then govern it.
- 22.1 supersedes 21.6 (same scope, better home). 22.4/22.5 depend on 22.1's governor skeleton.
- Independent of Plan 5.5 (Decimal) and 5.6 (restart recovery); the governor reads the same
  session state either way. Plan 6's decomposition should treat `governor.py` +
  `portfolio_risk.py` as already-extracted modules (it makes Plan 6 easier, not harder).
- Backtest parity note: the governor is live-only by design in this plan (backtest has its own
  per-symbol checks). A backtest-side governor for validation parity is a candidate follow-up —
  record as an open question, don't scope-creep it in.

## Part F — Open questions — **1, 2, 3, 5 decided 2026-07-17 (see `DECISIONS.md` #23)**

1. ~~Auto-flatten on `halted`~~ — **Decided: add it, opt-in default off.**
2. ~~Daily-loss window anchor~~ — **Decided: UTC midnight.**
3. ~~Chaos governor defaults~~ — **Decided: same defaults as normal sessions, surfaced prominently
   in the wizard.**
4. VaR method for enforcement: current Zone 1 historical-simulation VaR is fine for v1; variance
   scaling / EWMA refinements only if breach behavior proves too twitchy in practice. **Not asked
   — no decision needed to start 22.1; ships as-is, revisit later if needed.**
5. ~~Capital over-commit (B-11/B-12)~~ — **Decided: hard reject on non-numeric/negative/zero
   always; over-commit vs wallet is warn-with-explicit-confirm on testnet, hard reject the day
   mainnet is ever considered.** Sub-question still open (implementation detail, not policy): does
   the reservation ledger count a stopped-but-unconfirmed session's capital (see Plan 21 A-4/
   stop-path issues) as still committed? — resolve during 22.1's build.

**22.1–22.3 are now unblocked** — all policy decisions needed to start implementation are recorded
in `DECISIONS.md` #23.
