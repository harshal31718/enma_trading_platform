# 0 — Plan Tracker

Live status board. One row per plan. Catalog + conventions live in [`0_plans.md`](0_plans.md);
the phase column maps to [`0_roadmap.md`](0_roadmap.md) (Phases 0–8).

Statuses: `Draft` · `Ready` · `Blocked` · `Verify` · `Shipped` · `Merged→N` · `Split→N,M` · `Dropped`
(defined in `0_plans.md`).

| ID | Title | Status | Priority | Phase | Depends on | Related | Updated |
|----|-------|--------|----------|-------|------------|---------|---------|
| 1  | Public access + admin-gated algo/testnet-start | Shipped | — | — | — | — | 2026-07-14 |
| 2  | Safety net & guardrails | Shipped | P0 | 1–2 | — | 3,4,5 | 2026-07-15 |
| 3  | Service-to-service trust | Shipped | P0 | 1–2 | 2 | 4,8 | 2026-07-15 |
| 4  | Credential & config topology | Ready | P1 | 1 | 2,3 | 8 | 2026-07-14 |
| 5  | Live-trading state integrity | Ready | P0 | 3 | 2,3 | 6 | 2026-07-14 |
| 6  | Engine decomposition & exchange abstraction | Ready | P2 | 4, 6.1 | 5 | 7 | 2026-07-14 |
| 7  | Server & client structure | Ready | P2 | 5 | 2,5 | 6 | 2026-07-14 |
| 8  | Governance, correctness & cleanup | Ready | P3 | 6 | 3,5,6 | all | 2026-07-14 |
| 9  | Backtest & optimizer correctness (quant core) | Ready (9.1–9.3 Shipped) | P0 (9.1–9.3 done) / P1 (rest) | 0 + 7 | — (9.1–9.3); 2 (9.5+) | 5,6,8 | 2026-07-15 |
| 10 | Monte Carlo Optimiser & Strategy Lab | Ready | P1 | 8 | 9 (9.1, 9.3) | 2,7 | 2026-07-14 |

---

## Execution order

Plans 2–8 are the remediation of the audit in [`audit_1_system-design.md`](audit_1_system-design.md), sequenced by
**dependency, not severity**. Work them in numeric order; a later plan may run in parallel with
an earlier one only where the `Depends on` column allows (e.g. Plan 4 config work and Plan 5
state work touch different files). Rationale for the ordering is in each plan's "Why this is
first / Why now" section, and summarized: verification scaffolding (2) → close the two worst
security holes (3) → move secrets to per-user settings (4) → fix live-trading state integrity
(5) → restructure the engine that implements it (6) → restructure server/client (7) →
reconcile docs and close trailing correctness gaps (8).

The quant track (9, 10) runs **in parallel** with the hardening track — Phase 0 (9.1–9.3)
should start immediately; see `0_roadmap.md` for the two-track sequencing and per-phase gates.

**Session protocol:** pick the lowest-numbered plan not `Shipped` on your track (hardening:
2→8; quant: 9→10), set it to a working status, follow its Steps in order, meet its Acceptance
criteria, then update this row and write a resume note to `handoff.md` (CLAUDE.md Rule G).
Never mark `Shipped` without the phase Acceptance criteria and (for pipeline-touching steps)
a golden-master check per Rule C.

## Notes

- **1** — Shipped via commits `ddce1c1` / `efa8cd5` (open login, per-user `requireAlgoAccess`,
  admin user table, Settings request flow). Kept for reference.
- **2** — Shipped 2026-07-15. Server/client test harnesses (39 + 11 tests), fail-closed
  encryption (required an unplanned credential migration — see plan file for the shared-
  production-database discovery), correlation IDs + pino logging, honest engine `/health`, CI
  (`.github/workflows/ci.yml` + `docker-compose.ci.yml` + `.env.ci`). Full detail + deviations
  in `2_safety-net-and-guardrails.md`'s "Shipped summary". **Flagged follow-up before Plan 4:**
  local dev shares production's MongoDB Atlas cluster — decide whether to give local dev its
  own database.
- **3** — Shipped 2026-07-15. Closed the RCE strategy-code path (removed, confirmed dead code
  client-side) and authenticated `/internal/*` (distinct shared secret, constant-time compare
  both directions), tiered Redis-backed rate limits. Full detail in
  `3_service-to-service-trust.md`'s "Shipped summary" — includes a self-inflicted crash-loop
  incident during the step, root-caused and fixed before moving on.
- **4** — Implements the ".env → per-user Settings" directive for personal credentials + scopes
  container env + rotatable infra secrets.
- **5** — Highest-value correctness work: exchange as source of truth for live trading state,
  replacing the current three-way-divergent (exchange / engine memory / Mongo) reconciliation
  heuristics. Do not promote to mainnet before this is `Shipped`.
- **6** — Structural cleanup of the live engine: `LiveBotManager` stops being a 2,000-line god
  class; live/backtest/mainnet vary behind a real exchange abstraction instead of `is_live`
  flags. Comes after 5 so the correctness model is settled before the code moves.
- **7** — Structural cleanup of Node/React: controllers stop being 1,000-line god functions,
  long engine work becomes a job not an HTTP hang, page components stop being 1,700-line
  monsters. Depends on 2 (tests must exist first) and 5 (render the new state model).
- **8** — Trailing correctness fixes (ENG-8/14/15/18, SEC-8 remainder/10) + doc reconciliation
  to the shipped architecture. Last because it only makes sense once 3/5/6 have landed.
- **9** — Quant-core correctness (see `audit_2_quant-core.md`). Steps 9.1–9.3 (QNT-1 multi-symbol
  exit-check, QNT-2 exec-algo close/flip erasure, QNT-17 run-config persistence for leverage
  sensitivity) **Shipped 2026-07-15** — see `handoff.md`. Steps 9.4–9.10 remain `Ready`; several
  change backtest outputs by design and need a golden-master re-baseline with sign-off (Rule C)
  before landing.
- **10** — Job-based Monte Carlo + Optimizer Strategy Lab. Hard-depends on 9.1/9.3, both now
  shipped — unblocked.