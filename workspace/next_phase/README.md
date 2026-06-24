# Enma — Next Phase (Forward Implementation Plan)

**Created:** 2026-06-25
**Supersedes the "remaining sequence" in `workspace/plan/INDEX.md`.**

This directory is the **single source of truth for net-new work**. It was produced by:
1. Reading every active doc in `workspace/plan/`.
2. **Auditing the actual code** (not the docs) to find what is already built.
3. Cross-referencing the freqtrade + nautilus_trader gap matrix (now `REF-gap-matrix-freqtrade-nautilus.md` in this directory).
4. Grounding each design in the **real upstream source** (targeted fetches — see each spec's "Upstream reference").

> Hard constraint for this phase: **no edits outside `workspace/`.** These are specs, not code.

---

## The correction that reshaped this plan

`workspace/plan/INDEX.md` listed three "remaining" items (#3 Dashboard restructure, #4 Risk
Dashboard, #5 Monte Carlo). **A code audit on 2026-06-25 found all three already implemented
and wired** — the plan docs predate the work and were never reconciled. Details + evidence in
[`00-current-state-reconciliation.md`](00-current-state-reconciliation.md).

So the real forward work is the freqtrade/nautilus feature gaps, not the dashboards.

---

## Sequence (build in this order)

Ordering rule: **risk primitives first, validation tooling next, optimization last.** Each step
is independently shippable. Pipeline-touching steps gate on `golden_master.py`.

| Seq | Spec | Service | Effort | Gate | Depends on |
|-----|------|---------|--------|------|-----------|
| **V0** | [Verify the "done" trio (#3/#4/#5)](00-current-state-reconciliation.md) | all | S | Manual smoke + boundary | — |
| **S1** | [Max position per asset](S1-max-position-per-asset.md) | engine | S | Golden master | V0 |
| **S2** | [Informative / multi-timeframe contract](S2-informative-multi-timeframe.md) | engine | M | Golden master + boundary | V0 |
| **S3** | [Webhook notifications](S3-webhook-notifications.md) | server | S | Unit + manual | V0 (independent) |
| **S4** | [Data conversion CLI](S4-data-conversion-cli.md) | engine | S | Round-trip equality | V0 (independent) |
| **S5** | [Lookahead-bias analysis](S5-lookahead-analysis.md) | engine | M | Self-test on known-bad strat | S2 |
| **S6** | [Recursive-formula analysis](S6-recursive-analysis.md) | engine | M | Self-test on EMA vs SMA | S2 |
| **S7** | [Walk-forward analysis](S7-walk-forward-analysis.md) | engine | M | Sum-of-folds == full-range trades | S1 |
| **S8** | [Bayesian hyperopt (optuna)](S8-bayesian-hyperopt.md) | engine | M | Beats grid baseline ≤ N trials | S7 |

**Quick-win batch (N-1):** S1, S3, S4 — can ship in days, low blast radius.
**Analysis/optimization batch (N-2):** S5, S6, S7, S8 — needs a stable engine; S2 unlocks richer strategies.

Explicitly deferred (per `REF-gap-matrix-freqtrade-nautilus.md` §4 and the user's scope choice): multi-venue adapter,
FreqAI ML pipeline, tick data, order book backtesting, Telegram. Re-open only after S1–S8.

---

## How each spec is structured

Every `Sn-*.md` follows the same shape so they're executable without re-deriving context:

1. **Goal** — one line.
2. **Current state (audited)** — what exists in code today, with file:line evidence.
3. **Upstream reference** — how freqtrade/nautilus solves it, with the exact algorithm.
4. **Design** — the Enma-native approach (respects single-user, Binance-only, five-model pipeline).
5. **Files to create / modify** — concrete list.
6. **Verification gate** — how we prove it works.
7. **Sequencing & risks** — dependencies and what could break.

---

## Reference / backlog (in this directory — not sequenced specs)

These were moved here when `workspace/plan/` was dissolved (2026-06-25). They are context, not a
build queue. The build queue is V0 + S1–S8 above.

- `REF-gap-matrix-freqtrade-nautilus.md` — the full freqtrade/nautilus feature matrix S1–S8 derive from (incl. deferred multi-venue/ML items).
- `REF-future-paths.md` — long-horizon exploration backlog (Monte Carlo extensions, vol forecasting, regime detection, equities/ML forks).
- `REF-mcpt-research.md` — Monte Carlo **Permutation** Test research (distinct from the bootstrap Monte Carlo already built; not scheduled).
- `REF-optimization-ideas.md` — parking lot of codebase-level optimization ideas.

## Pointers

- Audit evidence + what's already done: `00-current-state-reconciliation.md`
- Original (now reconciled) dashboard/risk plans: **deleted** — recoverable from git history; their
  built implementations are the source of truth (see the reconciliation doc for file paths).
- Completed/historical plans: `workspace/archive/`
- Authoritative feature inventory: `workspace/docs/state/CURRENT_STATE.md`
- Session resume log: `workspace/plan/handoff.md` (kept there per root `CLAUDE.md` Rule G)
