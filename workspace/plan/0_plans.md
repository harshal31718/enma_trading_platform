# 0 — Plans Index

Master catalog for everything we intend to build in Enma. This folder is a **planning
workspace only** — nothing here is implemented by writing it here. Implementation happens
in a separate session against a chosen plan.

Companion file: [`0_tracker.md`](0_tracker.md) — the live status board (one row per plan).

---

## How this folder works

One flat folder, four file families (the former `refinements/` subfolder was dissolved into
these on 2026-07-14 — mapping below):

- **`0_*.md`** — meta: **`0_plans.md`** (this file — the catalog: what each plan is, one
  paragraph each, plus how plans relate), **`0_tracker.md`** (the board: ID, status, priority,
  dependencies, phase), **`0_roadmap.md`** (the phased execution blueprint: Phases 0–8 over
  the plans, with per-step objective/implementation/verification).
- **`N_<slug>.md`** — one plan per file. Numbered by creation order, not priority.
  Priority lives in the tracker, so a plan can be reprioritised without renaming the file.
- **`audit_*.md`** — evidence: issue catalogs with IDs, severities, confidence tags. Plans
  cite these; they are never edited to match a plan (fix the plan instead).
- **`research_*.md`** — reference: descriptive baseline + external research that informed the
  plans. Read-mostly.

### Plan file naming

`N_<kebab-slug>.md` — e.g. `1_public-access-admin-gating.md`. The number is a stable ID; it
never changes once assigned (even if the plan is deprecated). Slugs may be refined.

### Reference shelf (audits & research)

| File | Was (pre-2026-07-14) | Contents |
|------|----------------------|----------|
| [`audit_1_system-design.md`](audit_1_system-design.md) | `issues.md` | System/SOLID/security audit — SEC-1..10, ENG-1..18, SRV-1..5, CLI-1..3, SYS-1..7. Feeds plans 2–8. |
| [`audit_2_quant-core.md`](audit_2_quant-core.md) | `refinements/05_algotrading_deep_dive.md` | Quant-core audit — QNT-1..17 + methods research. Feeds plans 9–10. |
| [`research_1_project-outline.md`](research_1_project-outline.md) | `refinements/01_project_outline.md` | Descriptive architecture baseline (what exists, mapped). |
| [`research_2_market-survey.md`](research_2_market-survey.md) | `refinements/02_market_research.md` | How NautilusTrader/Hummingbot/Freqtrade + industry build each component. |
| [`research_3_gap-analysis.md`](research_3_gap-analysis.md) | `refinements/03_better_options.md` | Gap analysis + evaluated options (incl. the §0 multi-tenant reframing decision). |
| [`0_roadmap.md`](0_roadmap.md) | `refinements/04_improvement_roadmap.md` | Phased blueprint, rewritten to cover plans 1–10 (Phases 0–8). |

Shorthand references inside these docs (e.g. "02 §10") refer to the old series numbers per
this mapping. The number inside the prefix (`audit_1_`, `research_2_`, …) is **reading order
within that shelf**, not implementation order — implementation order lives only in
`0_tracker.md`/`0_roadmap.md`.

### Plan lifecycle / statuses

| Status | Meaning |
|--------|---------|
| `Draft` | Rough idea captured, not yet fleshed out. |
| `Ready` | Scoped enough to hand to an implementation session. |
| `Blocked` | Waiting on a dependency or a decision. |
| `Shipped` | Implemented and merged. Kept for reference. |
| `Verify` | Believed implemented but not confirmed against the running stack. |
| `Merged→N` | Folded into plan N; this file is a stub pointer. |
| `Split→N,M` | Broke into plans N and M; this file is a stub pointer. |
| `Dropped` | Decided against. Kept so we don't re-propose it. |

### My standing job in this folder

Arrange, rearrange, merge, and split plans as they accumulate. Concretely:
- Keep `0_tracker.md` in sync whenever a plan is added, restatused, merged, or split.
- When two plans overlap, merge them (winner keeps its number; loser becomes a `Merged→N` stub).
- When one plan grows two independent halves, split it (`Split→N,M` stub + two new files).
- Surface conflicts and ordering (dependencies) rather than letting plans drift.

---

## Catalog

### 1 — Public access + admin-gated algo/testnet-start
[`1_public-access-admin-gating.md`](1_public-access-admin-gating.md) · **Shipped**

Open login to anyone with a Google account. Everyone can view the Algo Trading page, Chaos
Mode, and the new-bots UI, enter testnet API keys, and place manual Trade orders. Only the
**start** actions (start a testnet algo session / Chaos) are gated to admin-granted users;
non-granted users hit an "invited users only / request admin access" message.

> Shipped via commits `ddce1c1` / `efa8cd5` (open login + per-user `requireAlgoAccess` +
> admin user table + Settings request flow). Kept for reference.

---

## Remediation program (plans 2–8)

Plans 2–8 are the remediation of the audit captured in [`audit_1_system-design.md`](audit_1_system-design.md). They are one
program, ordered by **dependency, not severity**, and meant to be implemented by separate
sessions in numeric order. Each plan file is self-contained (context, why-now, numbered steps
with per-step acceptance checks, phase acceptance criteria, open questions, handoff template).
The live board is [`0_tracker.md`](0_tracker.md).

### 2 — Safety net & guardrails
[`2_safety-net-and-guardrails.md`](2_safety-net-and-guardrails.md) · **Ready** · P0

Behaviour-neutral scaffolding every later plan needs: server + client test harnesses (there
are none today), fail-closed & versioned encryption (SEC-3), correlation IDs + structured
redacted logging (SYS-6), a CI gate that runs tests + golden-master (SYS-5), and a `/health`
that stops lying when a DB is down (ENG-13). Nothing else should start before this lands.

### 3 — Service-to-service trust
[`3_service-to-service-trust.md`](3_service-to-service-trust.md) · **Ready** · P0

Flips the inverted trust topology (SYS-1). Authenticates the `/internal/*` order routes
(SEC-1), closes the strategy-code RCE path (SEC-2 — carries a product decision), moves secrets
off custom headers (SEC-6), adds real tiered rate limiting (SEC-5), constant-time compares.

### 4 — Credential & config topology
[`4_credential-and-config-topology.md`](4_credential-and-config-topology.md) · **Ready** · P1

Implements the ".env → per-user Settings" directive: removes personal Binance credentials from
env/files (SEC-9), stops injecting the shared `.env` into every container incl. the client
(SEC-4), makes infra secrets rotatable, pins images and authenticates Redis (SEC-7).

### 5 — Live-trading state integrity
[`5_live-trading-state-integrity.md`](5_live-trading-state-integrity.md) · **Ready** · P0

The deepest fix. Makes the exchange the single source of truth via an append-only event log
(SYS-2, SRV-3), books real fills instead of fabricated exit prices (ENG-2), adds order
idempotency (ENG-10), serializes per-symbol state to kill the reconcile/candle race (ENG-3),
and moves money math to Decimal (ENG-11). Mainnet must stay gated until this is Shipped.

### 6 — Engine decomposition & exchange abstraction
[`6_engine-decomposition-and-exchange-abstraction.md`](6_engine-decomposition-and-exchange-abstraction.md) · **Ready** · P2

Breaks up the 2,000-line `LiveBotManager` god class (ENG-1), introduces a real testnet/mainnet
`Exchange` abstraction to replace scattered `mode="testnet"` literals (ENG-4), a typed
strategy↔engine contract (ENG-6), fixes the leaky adapter (ENG-5), a reliable ordered Node
transport (ENG-16), and proper packaging without symlink/`sys.path` hacks (ENG-12). Behaviour-
preserving — golden-master is the contract.

### 7 — Server & client structure
[`7_server-an