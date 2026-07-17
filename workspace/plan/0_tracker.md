# 0 — Plan Tracker

Live status board. One row per plan. Catalog + conventions live in [`0_plans.md`](0_plans.md);
the phase column maps to [`0_roadmap.md`](0_roadmap.md). The small, ship-any-time punch-list
that cuts across these plans lives in [`0_fixes-queue.md`](0_fixes-queue.md).

Statuses: `Draft` · `Ready` · `Blocked` · `Verify` · `Shipped` · `Merged→N` · `Split→N,M` ·
`Dropped` (defined in `0_plans.md`). **Restructured 2026-07-16:** active work first; completed
and merged plans in their own table below (detail lives in each plan file's "Shipped summary" —
this board no longer duplicates it).

## Active work (top-down = suggested order within each track)

| ID | Title | Remaining scope | Status | Priority | Depends on | Updated |
|----|-------|-----------------|--------|----------|------------|---------|
| 21 | Live algo industry-standard audit — **fixes** | 21.2–21.5, 21.7 (21.1 shipped code-side, pending container test run + live re-verification; 21.6 → Merged→22.1) | In progress (21.1 shipped 2026-07-17) | **P0** (21.2, = F7 follow-up) / P1–P3 | — | 2026-07-17 |
| 5  | Live-trading state integrity | 5.5 (Decimal money, golden-master sign-off), 5.6 (restart recovery / projection) | In progress | P0 | 21.1–21.2 inform 5.6 | 2026-07-16 |
| 22 | Industry-standard risk management (Session Risk Governor) | All (22.1–22.7) | Ready (forks #2/#3 decided) | P1 (22.1–22.3) / P2 (rest) | 21 (21.1–21.4) | 2026-07-16 |
| 9  | Backtest & optimizer correctness (quant core) | 9.7 (funding ledger), 9.8 (intrabar sim), 9.9 (stats portion), 9.10 (fill-model ladder), **9.11 (cost-gate resurrection, M-1/M-2/M-3 — Step A inert, Step B re-baselined)** | Ready | P1 | — | 2026-07-16 |
| 10 | Monte Carlo Optimiser & Strategy Lab | Phases 1b–4 (job plumbing, `labResults`, UI, optimizer w/ walk-forward + Optuna) | Ready | P1 | 9 (9.1/9.3, shipped) | 2026-07-16 |
| 13 | Informative / multi-timeframe contract (`self.htf()`) | All | Ready | P2 | — | 2026-07-16 |
| 17 | Recursive-formula / warmup-insufficiency analysis | All | Ready | P2 | 13 (sequence after) | 2026-07-16 |
| 6  | Engine decomposition & exchange abstraction | All | Blocked | P2 | 5 fully shipped; 21.3/21.4 should land first | 2026-07-16 |
| 7  | Server & client structure | All | Blocked | P2 | 2 (done), 5 | 2026-07-16 |
| 8  | Governance, correctness & cleanup | 8.2–8.6 (8.3/8.4 golden-master; 8.6 product decision; SYS-3 doc item carried from F6) | In progress | P3 | 3 (done), 5, 6 | 2026-07-16 |
| 23 | New strategy: high-risk/high-leverage breakout scalper ("MarginSurge") | All — backtest gates can start now; live gated on 21.1–21.4 | Draft | P2 | 21 (live phase), 22.1–22.2 (liq-buffer + governor, soft) | 2026-07-16 |
| 24 | BestSupertrend fixes (never trades at defaults) | S-1 sizing/affordability, S-2 live HTF off-by-one, S-3 fail-loud unsatisfiable configs, S-4 `order_type` collision, S-5 docs | Ready | P1 | — (live verify after 21.1–21.2); S-1/S-2 need a cheap BestSupertrend re-baseline | 2026-07-16 |

**Plus the fixes queue:** F7 (algo-fill detection — root causes now identified, fix = 21.1/21.2)
and F8 (Redis `requirepass`, wants a full-stack-restart window) — see `0_fixes-queue.md`.

## Completed / merged (reference only — detail in each plan file)

| ID | Title | Outcome | Date |
|----|-------|---------|------|
| 1  | Public access + admin-gated algo start | Shipped (`ddce1c1`/`efa8cd5`) | 2026-07-14 |
| 2  | Safety net & guardrails | Shipped — test harnesses, fail-closed encryption, correlation IDs, CI | 2026-07-15 |
| 3  | Service-to-service trust | Shipped — `/internal/*` auth, RCE path removed, tiered rate limits | 2026-07-15 |
| 4  | Credential & config topology | Mostly shipped — residual Redis `requirepass` tracked as **F8** | 2026-07-15 |
| 11 | Current-state reconciliation (V0) | Verified live (verify-only gate — complete) | 2026-07-15 |
| 12 | Max position per asset | Shipped — 1a pre-existing, 1b `max_open_positions` | 2026-07-15 |
| 14 | Webhook notifications | Shipped (fixes-queue F3) | 2026-07-16 |
| 15 | Data conversion CLI | Shipped (fixes-queue F4) | 2026-07-16 |
| 16 | Lookahead-bias analysis | Merged→9 (superseded by shipped 9.5 sentinel) | 2026-07-15 |
| 18 | Walk-forward analysis | Merged→10 (Phase 3 design input) | 2026-07-15 |
| 19 | Bayesian hyperopt (Optuna) | Merged→10 (Phase 3 design input) | 2026-07-15 |
| 20 | Binance precision/notional parity | Shipped — DCA scale-out stepSize floor + entry idempotency | 2026-07-15 |

Partially-shipped steps inside active plans (5.1–5.4, 8.1, 9.1–9.5 + QNT-15, 10 Phase 1a) are
recorded in those plans' own Shipped summaries — the Remaining-scope column above is the
authoritative "what's left".

---

## Execution order

Three tracks, workable in parallel:

1. **Live-correctness track (P0):** 21.1/21.2 (fill-path fixes, unblocks the F7 reproduction)
   → 21.3/21.4 (bracket cancel-on-close, naked-position re-arm) → 22.1–22.3 (Session Risk
   Governor hard checks) → 5.5/5.6 → 22.4–22.7 → then 6 → 7 unblock.
2. **Quant track:** 9.7–9.10 (each needs its own golden-master re-baseline + sign-off) and
   10 Phases 1b–4 — independent of the live track.
3. **Feature track:** 13 → 17 — independent of both.

Plan 8 trails everything (docs/cleanup only makes sense once 5/6 land).

**Session protocol:** pick the top unblocked item on your track, set it to a working status,
follow its Steps, meet its Acceptance criteria, update this row, write a `handoff.md` entry
(CLAUDE.md Rule G). Never mark `Shipped` without acceptance criteria met and (for
pipeline-touching steps) a golden-master check per Rule C.

## Notes (active plans only)

- **21** — Audit complete 2026-07-16 (`21_live-algo-industry-standard-audit.md`, findings
  A-1…A-14). **21.1 shipped 2026-07-17**: broken userTrades credentials (A-1), `_on_fill`
  AttributeError killing the event-driven fill path (A-2), LISTEN_KEY_EXPIRED killing the UDS
  task (A-3) — all three fixed with regression tests (`test_query_real_exit_from_user_trades.py`,
  `test_on_fill_client_id_extraction.py`, `test_uds_listen_key_expired_reconnect.py`). **Still
  outstanding before 21.1 is fully closed:** run the engine test suite inside the container (no
  Docker access from the session that made these edits) and re-run a small live session to confirm
  F7's ~60s staleness symptom is actually gone. 21.2 (ACCOUNT_UPDATE-driven reconcile) is next.
  21.6 merged into 22.1.
- **5** — 5.5 (Decimal) is the largest, riskiest remaining piece: needs a deliberate
  golden-master re-baseline with sign-off, never a same-day bundle. 5.6 (restart recovery)
  depends on the "LiveSession as pure projection" work 5.1 deliberately did not ship; factor
  Plan 21's A-8 (ACCOUNT_UPDATE-driven reconcile) into 5.6's design.
- **22** — Scope decisions taken 2026-07-16: portfolio layer yes (fork #3), rule-based only
  (fork #2), VaR/CVaR enforced (Zone 1 graduates from display-only). Found while grounding:
  `liq_buffer_pct` is decorative (no pipeline call site) and `max_portfolio_risk` is per-symbol
  despite its name. **Capital-control audit (user question, 2026-07-16):** risk-% per trade is
  genuinely parameter-controlled (3 clamp layers: `utils/risk.js` → Zone 2 cascade → engine
  F-014 floor) and per-bot/new-bot launch limits exist (`maxSymbolsPerBot`, `maxConcurrentBots`,
  chaos caps, `maxOpenPositions`) — but session `capital` itself is honor-system: presence-check
  only, no numeric bounds, never compared to the wallet, no cross-session reservation, and Chaos
  commits `capital × strategyCount` unchecked (findings B-11/B-12, fix = 22.1's capital
  integrity gate; Part F Q5 wants a reject-vs-warn decision). Do not start 22.1 before
  21.1–21.4. Part F open questions want user answers before 22.1 implementation.
- **9** — Remaining steps 9.7–9.10 change backtest outputs **by design** → per-step golden-master
  re-baseline with sign-off (Rule C). Who signs off is still an open question.
- **10** — MC core math is honest (Phase 1a shipped) but still behind the old synchronous
  endpoint; everything else (job queue, `labResults`, Strategy Lab UI, optimizer exposure)
  unstarted. Phase 3 absorbs plans 18/19 — build from their design notes, not their specs.
- **13/17** — Independent feature work; 17 sequences after 13 so it also sweeps multi-TF
  indicators. Gate any `htf()` adopter through the shipped 9.5 lookahead sentinel.
- **6/7** — Blocked on Plan 5 fully shipping. Plan 6 should treat Plan 22's `governor.py` /
  `portfolio_risk.py` as already-extracted modules and land after 21.3/21.4 so correctness
  fixes move with the code.
- **8** — 8.1 shipped (F6). Remaining: 8.2–8.6 + the SYS-3 named-volume documentation item
  carried from F6. 8.3/8.4 are golden-master-touching; 8.6 needs a product decision
  (multi-session same-account modelling) before code.
- **Standing open questions** (carried from earlier sessions): golden-master re-baseline
  sign-off ownership (9.7/9.8, 5.5); keep-or-delete `IcebergAlgorithm`; local dev sharing
  production's MongoDB Atlas cluster (structural fix still pending); event-log store choice
  (Mongo shipped, Timescale revisit only on volume).
