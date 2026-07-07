# AGENTS.md — Universal Agent Rules for Enma

**This is the cross-tool entry point. Every AI agent that touches this repository — Claude Code, Google Antigravity, Gemini Code Assist / CLI, Cursor, Aider, or any other — MUST read this file first and follow the rules in it.**

Enma is a **multi-user** (open login; Algo Trading gated per-user by admin approval), full-stack algorithmic trading platform: write Python strategies, backtest against Binance futures data, run live algo bots, and manually trade futures — self-hosted, fully containerized via Docker.

---

## Read Order (every session, every agent)

All agents follow the same onboarding path. Read in order, then the files your task needs:

1. **This file** (`AGENTS.md`) — onboarding, architecture, constraints, universal rules
2. `workspace/docs/state/CURRENT_STATE.md` — what is implemented, planned, and removed *right now*
3. `CLAUDE.md` (root) + the relevant service `CLAUDE.md` (`client/`, `server/`, `engine/`)
4. `.claude/GOVERNANCE.md` — source-of-truth hierarchy, documentation rules, AI infrastructure inventory

> **Note on visibility:** `.claude/` and `.mcp.json` are git-ignored (local-only). **`CLAUDE.md`, the service `CLAUDE.md` files, `AGENTS.md`, and `workspace/` (docs, specs, plans) are tracked in git** as shared project memory — `workspace/README.md` is the map of that directory and its lifecycle rules. This `AGENTS.md` is intentionally **self-contained for the non-negotiable rules** so any agent stays safe even before reading the deeper docs.

---

## Architecture (30 seconds)

| Layer | Stack | Role |
|-------|-------|------|
| `client/` | React 18, Vite 5, Tailwind 3, Zustand, TanStack Query, Socket.IO | Trading UI |
| `server/` | Node 20, Express, Socket.IO, BullMQ, Mongoose | API gateway + job queue |
| `engine/` | Python 3.11, FastAPI, TA-Lib, httpx, asyncpg, motor | Computation, backtesting, live execution |
| MongoDB | strategies, backtestResults, backtestTrades, liveSessions, Settings | Metadata |
| TimescaleDB | `candles` hypertable (OHLCV only) | Time-series |
| Redis | BullMQ queues, pub/sub, cache | Queue + messaging |

Flow: client ↔ server (REST + Socket.IO) ↔ engine (HTTP). Client connects directly to Binance WebSocket for public market data only.

---

## Non-Negotiable Constraints (apply to every agent, every change)

| Rule | Detail |
|------|--------|
| **Multi-user, open login + per-feature gating** | Google OAuth + JWT cookie; **login is open to anyone**. All `/api/v1/*` routes require `verifyJWT`. Data is scoped per user via `userId` on all mutable Mongoose models (BacktestResult, BacktestTrade, LiveSession, Settings, TradeOrder, TradeExecution, TradeTransaction, TradeRecord). Strategies stay global/shared — no `userId` on `Strategy`. **Algo Trading is gated per-user** via `requireAlgoAccess` on the start actions (`POST /algo/sessions`, `POST /algo/chaos`); admins bypass via role. Backtest, manual Trade, and Binance key entry are open to all authenticated users. Access is requested from Settings and granted/revoked by admins from the Admin panel user table (`User.algoAccess.status`: `none`\|`requested`\|`granted`). |
| **Layer boundaries** | Financial / indicator / order logic lives in `engine/` only. `server/` is a gateway + job queue. `client/` is UI. |
| **Binance isolation** | Only `engine/` calls Binance. Never from `server/` or `client/`. Read `workspace/docs/core/binance-api.md` before any Binance work. |
| **Engine is sole writer** | `backtestResults` + `backtestTrades` are written only by the engine. Server updates `status`/`error` only. |
| **TimescaleDB isolation** | Candles only, engine only. Server never connects to TimescaleDB. |
| **Testnet only** | All live orders go to Binance Testnet. Mainnet is not implemented. |
| **No Redux** | Zustand for UI state, TanStack Query for server state. |
| **P&L colors** | `emerald-400` (profit) / `red-400` (loss). Never generic `green`. |
| **No ccxt** | Engine uses `httpx` + native HMAC-signed REST. ccxt is a rejected approach. |
| **Don't touch** | `.env` files, `node_modules`, host `TA-Lib`, DB configs. All deps run in Docker. |

---

## Source of Truth & Documentation Duty (all agents)

- **Code always wins over docs.** If docs ≠ code, fix the docs.
- After any change, update the affected docs (`workspace/docs/core/`, `workspace/docs/state/CURRENT_STATE.md`, `workspace/docs/state/DEPRECATED.md`) per `.claude/GOVERNANCE.md`.
- Never leave a decision only in chat history.
- Never reference a file that doesn't exist (check `workspace/docs/state/DEPRECATED.md`).
- `.claude/` files are AI-infrastructure, owned by the user — do not edit them without explicit direction.

---

## Required Reads Per Task Type

Load only what the task needs — don't preemptively load everything:

| Task | Required reads |
|------|---------------|
| Any task | `AGENTS.md` (this file) + `workspace/docs/state/CURRENT_STATE.md` + `CLAUDE.md` |
| Frontend work | + `client/CLAUDE.md` |
| Backend work | + `server/CLAUDE.md` |
| Engine / backtest | + `engine/CLAUDE.md` |
| API changes | + `workspace/docs/core/API_CONTRACTS.md` |
| Binance work | + `workspace/docs/core/binance-api.md` |
| Architecture decision | + `workspace/docs/core/DECISIONS.md` |
| Adding an indicator | + `workspace/docs/indicators/INDEX.md` (check for duplicates first) |
| Adding a strategy | + `workspace/docs/strategies/INDEX.md` + `workspace/docs/indicators/INDEX.md` |
| Feature-specific deep work | + `workspace/docs/features/<name>/SPEC.md` if it exists |

---

## Skills / Commands

Skills live in `.claude/commands/` and are invocable as `/command-name` in Claude Code or
via the Skill tool. All files are plain Markdown — every tool can read them directly.

**Canonical list:** `.claude/GOVERNANCE.md` → Part 2 (AI Infrastructure Inventory) is the single
source of truth for the full skill set and their status — don't duplicate it here.
`workspace/skills/README.md` is a thin discovery pointer.

**Auto-deployment rule:** For tasks matching a skill's trigger, invoke it automatically without
waiting to be asked — adding an indicator → `/add-indicator`; adding a strategy → `/add-strategy`;
implementation complete → `/sync-spec`. After a large refactor, spawn the `drift-reviewer` agent.
The non-negotiable gate: **`/sync-spec` after every code change** (its completion gate also spawns
`drift-reviewer` to confirm zero drift).

---

## Subagents

One project subagent lives in `.claude/agents/`, run in an isolated context window — spawn it for
a focused audit rather than loading everything into the main session.

| Subagent | Use for |
|----------|---------|
| `drift-reviewer` | Read-only audit of code vs spec across the 6 drift vectors. Reports only — never edits. |

> Doc-sync is inline via `/sync-spec`; general "where/how" search uses the built-in Explore agent.

---

## Session Handoff

For multi-phase work: **list all phases up front**, then write a resume prompt to
`workspace/plan/handoff.md` after each completed phase. Format:
```
Next session: [what's done, what's next, which files changed, open questions]
```
This lets any AI session resume exactly where the previous one stopped. The file keeps at most
the **3 most recent entries** — adding a new one deletes the oldest (git history is the archive).

---

## Entry Files

**`AGENTS.md` (this file) is the single, tool-agnostic entry point for every non-Claude agent** — Google Antigravity, Gemini, Cursor, Aider, and anything else. They read this file and follow the read order above.

Claude Code additionally uses `CLAUDE.md` + `.claude/` (its native config), which mirror these same rules.

> If a specific tool doesn't auto-discover `AGENTS.md`, point it here in that tool's settings — do **not** fork the rules into a separate tool-specific file.
