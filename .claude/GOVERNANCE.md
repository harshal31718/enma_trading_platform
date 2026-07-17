# ENMA — Governance & AI Infrastructure

The single `.claude/` root doc. Covers (1) documentation governance — accuracy, drift, lifecycle —
and (2) the AI infrastructure inventory (commands, agents, MCP, hooks, permissions).

> Onboarding / read-order / architecture / constraints live in **`AGENTS.md`** (repo root) — the
> universal entry point every agent reads first. This file is the rules + tooling reference.

Last updated: 2026-07-02 (workspace restructure: archive/ deleted, inventory reconciled to disk)

---

# Part 1 — Documentation Governance

## Source of Truth Hierarchy

| Priority | Source | Notes |
|----------|--------|-------|
| 1 | Source code | Always wins. Never argue with the code. |
| 2 | `workspace/docs/state/CURRENT_STATE.md` | Current feature state — most operationally critical |
| 3 | `workspace/docs/core/ARCHITECTURE.md` | System topology and service rules |
| 4 | `workspace/docs/core/DECISIONS.md` | Major architectural decisions and rationale |
| 5 | `workspace/docs/core/API_CONTRACTS.md` | API shapes — must always reflect implementation |
| 6 | `CLAUDE.md` + service `CLAUDE.md` | Agent rules and constraints |
| 7 | Chat history | Never authoritative — disposable |

**Conflict resolution:** If docs ≠ code → code wins. Update the docs immediately after.

**Live-trading state note (Plan 5 Step 5.1):** the append-only `executionEvents` Mongo collection
(`engine/services/event_log.py`, engine-written at every state-mutating site) is the fact record
for live-trading state and outranks any derived read — but `LiveSession`/engine memory are **not
yet** pure projections of that log (that's Step 5.6, unstarted); they remain the live read path
today. See `workspace/docs/state/CURRENT_STATE.md` and `workspace/plan/5_live-trading-state-integrity.md`.

---

## Documentation Ownership

| Document | Who Updates | When |
|----------|-------------|------|
| `workspace/docs/core/ARCHITECTURE.md` | Any agent | Service topology changes, new DB responsibilities |
| `workspace/docs/core/DECISIONS.md` | Any agent | Major architectural decision confirmed |
| `workspace/docs/core/API_CONTRACTS.md` | Any agent | Endpoint added, changed, or removed |
| `workspace/docs/core/binance-api.md` | Any agent | Binance environment or endpoint changes |
| `workspace/docs/state/CURRENT_STATE.md` | Any agent | Feature status changes (planned → done, removed, etc.) |
| `workspace/docs/state/DEPRECATED.md` | Any agent | System, file, or workflow removed |
| `CLAUDE.md` | User | Core platform rules or stack changes |
| `client/CLAUDE.md` / `server/CLAUDE.md` / `engine/CLAUDE.md` | Claude Code | Service-specific structure or rules change |
| `AGENTS.md` | User | Universal entry point / onboarding / cross-tool rules |
| `.claude/GOVERNANCE.md` (this file) | User | Governance rules, command/MCP/agent inventory |
| `.claude/commands/*.md`, `.claude/agents/*.md` | User | Skill / subagent behavior changes |
| `.mcp.json` | User | MCP server configuration changes |
| `workspace/docs/features/<name>/SPEC.md` | Any agent | Feature-level behavior changes |

> **Hard rule:** Claude Code must **never** write to any `.claude/` file, `CLAUDE.md`, or `AGENTS.md` without explicit user direction. These are AI infrastructure, not application docs.

---

## Mandatory Update Rules

Enforced by the completion gate in `/sync-spec` (and every scaffolding command). No task is done until all applicable rules are satisfied.

### After every code change:
- New API endpoint added → **update `workspace/docs/core/API_CONTRACTS.md`**
- Architectural decision made → **append to `workspace/docs/core/DECISIONS.md`**
- Feature ships → **mark DONE in `workspace/docs/state/CURRENT_STATE.md`**
- System or feature removed → **add entry to `workspace/docs/state/DEPRECATED.md`**
- New package installed → **add to service `CLAUDE.md` stack section**

### After every planning session:
- A system is retired → **update `workspace/docs/state/DEPRECATED.md` immediately**
- Feature status changes → **update `workspace/docs/state/CURRENT_STATE.md`**

### After every workflow change (user only):
- New/changed/removed slash command or agent → **update the inventory in Part 2 of this file**
- Onboarding sequence changes → **update `AGENTS.md`**
- Governance rules change → **update this file**
- MCP server added/removed → **update `.mcp.json` and the MCP table in Part 2**

### Never:
- Leave a decision only in chat history
- Reference a file in docs that doesn't exist in the repo
- Update documentation without verifying against the source of truth hierarchy
- Report a task as complete without running `/sync-spec`
- Run git commands that discard or revert uncommitted changes (`git checkout --`, `git restore`, `git reset --hard`, `git clean`, `git stash` to hide work) without explicit user instruction in the same message — all post-last-commit work is live user work and must be preserved (see Rule H in `CLAUDE.md`)

---

## Documentation Sync Workflow

```
Implementation complete
        ↓
Run /sync-spec   (API_CONTRACTS · ARCHITECTURE · DECISIONS · CURRENT_STATE · DEPRECATED · service CLAUDE.md)
        ↓
Spawn drift-reviewer agent → zero boundary/contract violations
        ↓
Task is complete
```

If `/sync-spec` is skipped, the task is not complete.

---

## Deprecation Process

When a system, file, workflow, or feature is removed:

1. Add an entry to `workspace/docs/state/DEPRECATED.md` — what, why, approximate when, what replaced it
2. Remove all references to it from all active documentation
3. Do not leave redirect stubs — clean removal only

---

## Drift Detection

Spawn the `drift-reviewer` agent after large features or refactors. It audits:
- **Stack drift** — unauthorized packages in use
- **Structure drift** — folder structure doesn't match service `CLAUDE.md`
- **API drift** — routes/responses don't match `workspace/docs/core/API_CONTRACTS.md`
- **Boundary drift** — financial logic in wrong layer, or wrong service calling another directly
- **Convention drift** — naming, symbol formats (`BTC-USDT` client/server, `BTCUSDT` engine), P&L colors, component structure
- **Doc drift** — any doc references a file listed in `workspace/docs/state/DEPRECATED.md`, or a referenced file doesn't exist

---

## Knowledge Layer Map

| Layer | Location | Changes |
|-------|----------|---------|
| Permanent (architecture, decisions, APIs) | `workspace/docs/core/` | Rarely |
| Current state (implemented, planned, removed) | `workspace/docs/state/` | Frequently |
| Onboarding + cross-tool entry | `AGENTS.md` (repo root) | Rarely |
| Governance + AI infrastructure | `.claude/GOVERNANCE.md` (this file) | Rarely |
| Feature memory | `workspace/docs/features/<name>/` | Per feature (when threshold met) |
| Agent rules | `CLAUDE.md`, `*/CLAUDE.md` | Rarely |
| Skills and commands | `.claude/commands/` | As skills evolve |
| Subagents | `.claude/agents/` | As agents evolve |
| Ops runbooks (deployment) | `workspace/docs/ops/` | Per deploy learning |
| Session resume log | `workspace/plan/handoff.md` | Every multi-phase session (≤3 entries) |
| Historical / superseded docs | Git history only | Shipped plans are deleted, not archived — no archive folder exists |

---

## Feature Documentation Threshold

A feature earns its own `workspace/docs/features/<name>/` directory when it meets **two or more** of:

- Has a multi-step data flow spanning more than one service
- Has non-obvious behavioral invariants not captured by CLAUDE.md rules
- Has been a source of implementation bugs or confusion in the past
- Has more than 5 distinct configuration parameters or edge cases

For features below the threshold, `CURRENT_STATE.md` + the relevant service `CLAUDE.md` are sufficient.
See `workspace/docs/features/backtest-pipeline/` for the reference implementation.

---

## Context Budget Guidelines

Load only what the task needs — don't load all docs preemptively.

| Task | Load |
|------|------|
| Any task | `AGENTS.md` + `CURRENT_STATE.md` + `CLAUDE.md` |
| Frontend work | + `client/CLAUDE.md` |
| Backend work | + `server/CLAUDE.md` |
| Engine/backtest work | + `engine/CLAUDE.md` |
| API changes | + `workspace/docs/core/API_CONTRACTS.md` |
| Binance work | + `workspace/docs/core/binance-api.md` |
| Architecture decision | + `workspace/docs/core/DECISIONS.md` |
| Feature-specific deep work | + `workspace/docs/features/<name>/SPEC.md` if it exists |

---

# Part 2 — AI Infrastructure Inventory

Canonical list of every command, agent, MCP, and automation layer. Update this when any of them change.

## Commands (`.claude/commands/`)

Invocable as `/command-name` in Claude Code or via the Skill tool — same Markdown file serves both.

| Command | Type | Purpose |
|---------|------|---------|
| `/sync-spec` | Workflow gate | Post-implementation doc-sync checklist + completion gate (required before declaring done) |
| `/add-strategy` | Scaffolding | Scaffold a new strategy in the engine + register in the seeder |
| `/add-indicator` | Scaffolding | Add a new TA indicator to **both** adapters (talib + pandas-ta) |
| `/security-review` | Operational | Scan for secrets, missing `userId` scoping / cross-user leakage, layer-boundary violations, key handling |
| `/verify` | Operational | Bring the Docker stack up + confirm a change works (health checks + observed behavior) |
| `/check-boundaries` | Boundary Check | Verify architectural boundaries are respected (no financial logic in wrong layer) |
| `/golden-check` | Golden Check | Run golden master tests to verify refactors don't change behavior |

**Dependencies:** all scaffolding commands call `/sync-spec` on completion; `/sync-spec`'s gate spawns the `drift-reviewer` agent. All commands assume the caller has read `AGENTS.md` + `CURRENT_STATE.md`.

## Subagents (`.claude/agents/`)

Run in an isolated context window — spawn for focused work instead of loading everything into the main session.

| Subagent | Tools | Edits files? | Purpose |
|----------|-------|--------------|---------|
| `drift-reviewer` | Read, Grep, Glob, Bash | No (reports only) | Read-only audit of code vs spec across the 6 drift vectors |

> Doc-sync is handled inline by `/sync-spec` (the former `doc-syncer` agent was merged into it). General "where/how" repo search is handled by the built-in Explore / general-purpose agents (the former `spec-explorer` agent was removed).

## MCP

Defined in **`.mcp.json`** at the repo root (the standard Claude Code project-MCP location).

| MCP | Scope | Purpose | Status |
|-----|-------|---------|--------|
| Filesystem | `enma_trading_platform/` only | Read/write project files | **Disabled** in `settings.local.json` (`disabledMcpjsonServers`) — Claude Code's native tools cover this |
| GitHub | Repository | PR / issue management, CI status | **Disabled** in `settings.local.json`; requires `GITHUB_PERSONAL_ACCESS_TOKEN` if re-enabled |

**Rules:**
- Database MCPs (MongoDB, TimescaleDB, Redis) are **not configured** — query data through the running app.
- **Never commit a literal secret.** Tokens go through env vars (`${GITHUB_PERSONAL_ACCESS_TOKEN}`) — never inline a PAT into `.mcp.json` or any tracked file.
- When adding an MCP: update `.mcp.json` and the table above.

## Hooks

**None configured.** Neither `settings.json` nor `settings.local.json` has a `hooks` key. All automation is manual — invoked via slash commands or the Skill tool.

## Permissions (`settings.local.json`)

- `.claude/settings.local.json` (local only, the sole settings file): a Bash/PowerShell command allowlist (git, curl/nslookup deploy checks) + `disabledMcpjsonServers` (filesystem, github — both off).

The settings file references no command or agent filename — renames/deletions there don't break it.

## Future AI Infrastructure (not implemented — do not cite as current)

Priority order: (1) pre-commit `/sync-spec` reminder hook; (2) read-only TimescaleDB MCP (candle inventory); (3) read-only MongoDB MCP (result inspection); then everything else once those prove value.
