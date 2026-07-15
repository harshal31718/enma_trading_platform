# Merge Context — `workspace/next_phase/` → `workspace/plan/` (2026-07-15)

**Who did this:** a separate Claude Code session, working only in `workspace/next_phase/`, while
another session was concurrently using `workspace/plan/` (0–10) as a fixed base. Per instruction,
**no existing `workspace/plan/` file was edited in content** except for the small pointer-fix edits
listed below — this was a file-move operation, not a re-plan.

## What happened

`workspace/next_phase/` was a second, parallel spec directory (created 2026-06-25 when the old
`workspace/plan/INDEX.md` was deleted). Having two active spec directories was confusing, so
`next_phase/` was folded into `plan/`, continuing the existing `N_kebab-name.md` numbering
(`plan/` already ran 1–10). `next_phase/` no longer exists.

## Rename map

| Old path (`workspace/next_phase/`) | New path (`workspace/plan/`) |
|---|---|
| `00-current-state-reconciliation.md` | `11_current-state-reconciliation.md` |
| `S1-max-position-per-asset.md` | `12_max-position-per-asset.md` |
| `S2-informative-multi-timeframe.md` | `13_informative-multi-timeframe.md` |
| `S3-webhook-notifications.md` | `14_webhook-notifications.md` |
| `S4-data-conversion-cli.md` | `15_data-conversion-cli.md` |
| `S5-lookahead-analysis.md` | `16_lookahead-analysis.md` |
| `S6-recursive-analysis.md` | `17_recursive-analysis.md` |
| `S7-walk-forward-analysis.md` | `18_walk-forward-analysis.md` |
| `S8-bayesian-hyperopt.md` | `19_bayesian-hyperopt.md` |
| `REF-gap-matrix-freqtrade-nautilus.md` | `ref_gap-matrix-freqtrade-nautilus.md` |
| `REF-future-paths.md` | `ref_future-paths.md` |
| `REF-mcpt-research.md` | `ref_mcpt-research.md` |
| `REF-optimization-ideas.md` | `ref_optimization-ideas.md` |
| `README.md` | folded into this file (`mergeContext.md`) |

All moves used `git mv`, so file history is preserved — `git log --follow` on any new path
resolves back through the old `next_phase/` name.

**Note on internal shorthand:** the spec bodies still refer to each other as `S1`–`S8` and `V0`
(e.g. "depends on S2", "run after V0") — that shorthand was left as-is inside the prose. It was
not rewritten to `12`–`19` sentence-by-sentence; this was a file move, not a content edit. Use the
rename map above to translate `S1`→`12`, `S2`→`13`, … `S8`→`19`, and `V0`→`11` when following an
internal reference.

**What was updated (mechanical, not re-plan):** filename references that would otherwise 404 —
inside `ref_gap-matrix-freqtrade-nautilus.md`, `ref_future-paths.md`, `ref_optimization-ideas.md`,
`11_current-state-reconciliation.md`, `14_webhook-notifications.md`, `15_data-conversion-cli.md`,
plus the map/pointer lines in `workspace/README.md`, `workspace/docs/state/DEPRECATED.md`,
`workspace/docs/core/API_CONTRACTS.md`, and `workspace/docs/features/backtest-pipeline/SPEC.md`.
No `workspace/plan/0_*.md`–`10_*.md` file content was touched.

## Build sequence (unchanged from `next_phase/README.md`, just renumbered)

Ordering rule: **risk primitives first, validation tooling next, optimization last.**

| Spec | Service | Depends on |
|---|---|---|
| `11_current-state-reconciliation.md` (V0 — verify #3/#4/#5 already built) | all | — |
| `12_max-position-per-asset.md` (S1) | engine | 11 |
| `13_informative-multi-timeframe.md` (S2) | engine | 11/12 |
| `14_webhook-notifications.md` (S3) | server | 11 (independent) |
| `15_data-conversion-cli.md` (S4) | engine | 11 (independent) |
| `16_lookahead-analysis.md` (S5) | engine | 13 |
| `17_recursive-analysis.md` (S6) | engine | 13 |
| `18_walk-forward-analysis.md` (S7) | engine | 12 |
| `19_bayesian-hyperopt.md` (S8) | engine | 18 |

Reference/backlog (not sequenced): `ref_gap-matrix-freqtrade-nautilus.md`,
`ref_future-paths.md`, `ref_mcpt-research.md`, `ref_optimization-ideas.md`.

## Open question for the other session

None — this was purely additive (new files 11–19 + `ref_*` + this file). `plan/0_*.md`–`10_*.md`
are untouched in content. Worth a glance from whoever owns `0_roadmap.md`/`0_tracker.md`: they
don't yet mention 11–19, since those indices weren't touched per instruction.
