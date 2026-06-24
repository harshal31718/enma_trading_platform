# Plan — Redirect

**`workspace/plan/` was dissolved on 2026-06-25.** Its contents were sorted into:

- **Active forward work →** [`workspace/next_phase/`](../next_phase/README.md)
  Sequenced specs S1–S8 (freqtrade/nautilus gaps) + `REF-*` backlog/reference docs
  (gap matrix, future paths, MCPT research, optimization ideas).
- **Completed / historical →** [`workspace/archive/`](../archive/)
  Done workstreams, shipped plans, the old planning snapshots (`STATUS.md`, `open_items.md`),
  and the seq #1–#5 design docs.
- **Deleted** (content reconciled into `next_phase/00-current-state-reconciliation.md`):
  `dashboardPage_restructure.md`, `RISK_DASHBOARD_PLAN.MD` — recoverable from git history.

## Why these two files remain here

`handoff.md` stays in `workspace/plan/` because root `CLAUDE.md` **Rule G** hardcodes
`workspace/plan/handoff.md` as the session resume-log path. This `INDEX.md` is the redirect you're
reading. Nothing else lives here.

**Start here for current work:** [`workspace/next_phase/README.md`](../next_phase/README.md).
