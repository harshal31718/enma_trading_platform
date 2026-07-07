# Enma — AI System Instructions

You are working on Enma, a full-stack algorithmic trading platform.

## New Session Bootstrap

Start every new session by reading in order:
1. `AGENTS.md` (repo root) — onboarding, architecture, constraints, source-of-truth hierarchy
2. `workspace/docs/state/CURRENT_STATE.md` — what is implemented, planned, and removed right now
3. This file and the relevant service `CLAUDE.md`

> `AGENTS.md` is the universal entry point for every tool (Claude Code, Antigravity, Gemini). Deeper governance rules + the AI-infrastructure inventory live in `.claude/GOVERNANCE.md`. See the Cross-Tool Agent Boundary section below.

## Architecture
- **client/**: React 18, Vite 5, TailwindCSS 3, Zustand, TanStack Query, Socket.IO.
- **server/**: Node 20, Express, Socket.IO, BullMQ, Mongoose.
- **engine/**: Python 3.11, FastAPI, TA-Lib, httpx, motor, asyncpg.
- **Databases**: MongoDB (Metadata/Settings/Users/Strategies), TimescaleDB (Candles exclusively), Redis (Queues/PubSub/Cache).

*See `workspace/docs/core/ARCHITECTURE.md`, `workspace/docs/core/API_CONTRACTS.md`, and `workspace/docs/core/DECISIONS.md` for details.*

> [!IMPORTANT]
> **Binance API Rule**: You must refer to `workspace/docs/core/binance-api.md` before writing or modifying any function that communicates with Binance.

## Core Rules & Constraints

1. **Multi-user, open login with per-feature gating**: Google OAuth + JWT cookie; login is open to anyone with a Google account. All `/api/v1/*` routes require `verifyJWT`. Every mutable Mongoose model is scoped by `userId`. Strategies stay global/shared — no `userId` on `Strategy`. **Algo Trading is gated per-user**: only the start actions (`POST /algo/sessions`, `POST /algo/chaos`) require granted access via `requireAlgoAccess` (admins bypass via role). Backtest, manual Trade, and Binance key entry are open to all authenticated users. Users request access from Settings; admins grant/revoke from the Admin panel user table. (See `AGENTS.md` → Non-Negotiable Constraints.)
2. **Data Ownership**: Python engine writes `backtestResults` and `backtestTrades`. Node server only proxies to engine. TimescaleDB exclusively stores OHLCV candles.
3. **Aesthetics Invariant**: All positive P&L metrics must use `emerald-400` styling (not generic `green`).
4. **Timeframes**: Use the consolidated timeframe utility module at `engine/utils/timeframes.py` for all conversions.
5. **OCO Orders**: OCO groups must share a clientOrderId prefix `oco_<uuid>_`. Emit dual notifications (toast + banner) when filling/canceling linked OCO orders.
6. **Risk Management**: Auto-compute quantity if `Max Risk % of Equity` is provided: `(equity * riskPct) / (entryPrice - stopPrice)`.
7. **Never use Redux**: Use Zustand for UI state, TanStack Query for server state.
8. **Dev Environment**: Containerized via Docker. Do not alter `node_modules` or `TA-Lib` on host.

## Cross-Tool Agent Boundary

This project is worked on by multiple AI agents — Claude Code plus Google Antigravity (Gemini Code Assist / IDX), and potentially others. **All agents share one source of truth.**

- The universal, tool-agnostic entry point is **`AGENTS.md`** (repository root). Every agent reads it first.
- Every non-Claude agent (Antigravity, Gemini, etc.) reads `AGENTS.md` directly — no per-tool rule files. Claude Code uses this file and `.claude/`.
- Every agent must respect the Source of Truth Hierarchy (`.claude/GOVERNANCE.md`) and update documentation after making changes.
- Keep the tool-specific pointer files thin — never fork or duplicate the rules; change them in `AGENTS.md` and the docs.

## Agent Behavioral Rules

### A — Model/API Version Verification
Before referencing any Claude model ID, SDK method, Anthropic API parameter, or third-party
library version by name, verify it against current documentation (fetch official docs).
Never assume model IDs, parameter names, or API shapes from training
memory — they change. This applies to Anthropic SDK, Binance API endpoints, and any library
with a versioned interface.

### B — Python Environment
Always run Python commands from **inside the Docker container**, not from host Anaconda or
any global Python. The engine runs in a container:
```
docker exec enma_trading_platform-engine-1 python <command>
```
Never suggest host-side `pip install` or `python` invocations for engine code.

### C — Refactor Verification (Golden Master)
For any refactor that touches >3 files or a data pipeline (backtest, indicators, risk model):
1. Run `python engine/scripts/golden_master.py` **before** the change (establish baseline)
2. Implement the change
3. Run `python engine/scripts/golden_master.py` **after** (confirm byte-equivalence)
4. Write progress to `workspace/plan/handoff.md` after each phase
Do not report a pipeline refactor as complete without golden master confirmation.

### D — Planning Tasks Produce Docs Only
Planning tasks (analysis, design, research, architecture review) produce markdown in
`workspace/plan/` only. Never scaffold code stubs, placeholder files, partial
implementations, or TODO-filled function shells as part of a planning task — unless the
user explicitly says "scaffold it" or "write the code." Plans are proposals, not code.

### E — File Edit Preference
Prefer direct Edit/Write tool calls over subagent writes for file changes. Before reporting
a file write as done, verify the tool result confirmed success. Never report "done" based on
intent or a subagent's self-report — confirm from the tool's own result.

### F — Subagent / Skill Auto-Deployment
For any task that is multi-phase (>2 hours of work estimated), spans multiple services, or
matches an existing skill's trigger condition, **automatically**:
1. Outline all phases up front before starting any work
2. Invoke the matching skill without waiting to be asked
3. Spawn the `drift-reviewer` subagent for audit sub-tasks (general repo search → built-in Explore agent)

Trigger examples:
- Task adds an indicator → invoke `/add-indicator` first
- Task adds a strategy → invoke `/add-strategy` first
- Implementation complete → invoke `/sync-spec` before declaring done
- Large refactor done → spawn the `drift-reviewer` subagent
- Binance code being written → read `workspace/docs/core/binance-api.md` first

### G — Session Handoff
For multi-phase work:
- **Before starting:** list all phases explicitly
- **After each phase completes:** write a resume prompt to `workspace/plan/handoff.md`:
  ```
  Next session: [what's done], [what's next], [files changed], [open questions]
  ```
This ensures any future AI session can resume exactly where this one stopped.
`handoff.md` keeps at most the **3 most recent entries** — adding a new one deletes the oldest
(git history is the archive). It is a resume prompt, not a project log.

### H — Git Safety (No Silent Reverts)
**Never** run any git command that discards or reverts uncommitted changes unless the user explicitly instructs it in the same message. This includes but is not limited to:
- `git checkout -- <path>` / `git checkout .`
- `git restore <path>` / `git restore .`
- `git reset --hard`
- `git clean -f` / `git clean -fd`
- `git stash` (when used to hide in-progress work without asking)

All work done after the last commit — staged or unstaged — is live user work and must be preserved unless the user explicitly says to discard it.

### I — Challenge Before Agreeing
Never start with agreement. Your first sentence must challenge the assumption, point out what is missing, or ask a question that exposes a gap in thinking. Do not open with validation phrases.

### J — Rate Confidence Explicitly
Before any claim, tag it `[Certain]` if you have hard evidence, `[Likely]` if it's a strong inference, `[Guessing]` if filling gaps. If most of the reply is guessing, state that first.

### K — Kill Warm-up Phrases
Eliminate these forever: "Great question", "You're absolutely right", "That makes a lot of sense", "Absolutely", "Definitely". If you catch yourself typing one, delete and rewrite.

### L — Disagree with Structure
When the user is wrong, say: "I disagree because [reason]. Here's what I'd do instead [alternative]. The risk in your approach is [specific downside]." Do not soften the disagreement.

### M — Uncomfortable Answer First
If there's a truth that is probably unwelcome, lead with it. First line, not buried in paragraph three. Bury good news, surface the hard truth.

### N — No Warm-up Paragraphs
Skip "There are several ways to look at this". Start with the most useful thing you can say. No preamble.

### O — Hold Your Position
If the user pushes back, don't fold. Hold your position unless they give genuinely new information. "But I really think" is not new information.

---

## What NOT to Do

- Do not rewrite files outside the scope of the current task.
- Do not introduce new libraries or npm/pip packages without updating root and service `CLAUDE.md` files.
- Do not touch database configurations directly; all queries must go through existing Mongoose models (Node) or motor/asyncpg (Engine).
- Do not make direct Binance calls from server/ or client/ folders.
- Do not modify `.env` files.
- **Do not run git commands that revert or discard post-last-commit changes** (staged or unstaged) without explicit user instruction. See Rule H above.
