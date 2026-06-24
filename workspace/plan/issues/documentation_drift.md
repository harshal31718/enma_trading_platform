# Analysis: Documentation Drift — 10 Nodes Reviewed

Originally from `workspace/issues_and_solutions/issues/documentation_drift.md` (merged into `plan/` 2026-06-24).

---

## Cross-Cutting Themes

| Theme | Wrong Claim | Truth (Code) | Files Affected |
|-------|-------------|--------------|----------------|
| **Pipeline refactor** | `should_long`/`should_short`/`update_position` + `frame/size/plan` | Unconditional `forecast()→assess→estimate→construct→route` | MODELS.md, algo-trading SPEC, MicroScalper.md, engine CLAUDE.md (already correct) |
| **Phantom JWT/auth** | JWT interceptor / auth middleware / auth routes exist | Auth fully removed 2026-06-22 | auth-settings SPEC, client/CLAUDE.md, server/CLAUDE.md |
| **Leaderboard sort** | "sorted by win rate" | `dashboard.py:71` sorts by **averageNetProfit** | CURRENT_STATE.md, engine/CLAUDE.md, client/CLAUDE.md |
| **Command count** | "6 commands" | 10 commands in `.claude/commands/` | GOVERNANCE Part 2, AGENTS.md |
| **LiveSession.mode** | `"testnet"\|"mainnet"` | Model enum `"paper"\|"live"` | API_CONTRACTS.md |

---

## Per-Node Findings

| Node | Status | Key Drift |
|------|--------|-----------|
| `.claude/` | 1 security finding, 2 stale, 1 missing | Commands table incomplete (6 listed → 10 actual); permissions description stale; `.claude/workflows/` undocumented; PAT in settings.json (git-ignored, not committed per correction) |
| `workspace/docs/core/` | MODELS.md major drift + ARCHITECTURE base-URL claim false | MODELS.md pipeline diagram wrong (still shows old `is_open` guard); method names wrong (`frame→assess`, `size→construct`, `plan→route`); ordering wrong (portfolio before cost). ARCHITECTURE claims "base URLs defined once" — false for public klines URLs |
| `workspace/docs/features/` | Algo SPEC stale hooks + missing chaos; auth SPEC self-contradiction; live-trading wrong testnet URL | Algo SPEC shows old `should_long()/should_short()` hooks; missing chaos endpoints; auth SPEC claims auth is implemented while also saying there's no auth layer; testnet URL is `testnet.binancefuture.com` not `demo-fapi.binance.com` |
| `workspace/docs/indicators/` | **CLEAN** | INDEX matches all 13 signatures + inline split. Per-indicator bodies + "Used By" column not line-checked |
| `workspace/docs/strategies/` | **Systemic param-default drift** | MicroScalper: 5/6 defaults wrong + EMA(3/9) headline wrong; AdaptiveTrend: 4 values drift; 3 remaining strategy docs unverified but likely also drifted |
| `workspace/docs/state/` | Leaderboard-sort wrong; DEPRECATED dead references | CURRENT_STATE `sorted by win rate` should be `sorted by net profit`; DEPRECATED points to removed `BOOTSTRAP.md`; renamed-commands table shows commands that no longer exist |
| `workspace/plan/` | handoff.md accurate; golden-master status conflict | handoff.md param table is root-cause evidence for strategy param drift. Golden master says "STALE" but CURRENT_STATE says baseline was refreshed |
| `CLAUDE.md files` (user-owned) | Phantom JWT in 2 files; leaderboard-sort wrong in 2; MicroScalper `import talib` claim false | client CLAUDE.md still mentions JWT interceptor and deleted `useAuthStore.js`; server CLAUDE.md says "JWT auth middleware on all routes"; engine CLAUDE.md says MicroScalper directly imports talib (removed in BUG-05); top_symbols count 70→80 |
| `AGENTS.md` (user-owned) | Git-visibility claim wrong; command count stale | Line 18 says `CLAUDE.md` files are git-ignored — they're actually **tracked**. Line 89 says "6 commands" — actual is 10 |

---

## Severity Distribution

- 🔴 **High** (wrong/misleading fact an agent or user would act on): MODELS.md pipeline, strategy params, auth-spec self-contradiction, testnet URL, phantom JWT
- 🟡 **Medium** (stale detail, internal contradiction): ARCHITECTURE base-URL claim, CURRENT_STATE sort, DEPRECATED dead refs, top_symbols count
- 🟢 **Low** (count/cosmetic/scoping): Command count, git-visibility claim, golden-master status
- 🔒 **User-owned files** (CLAUDE.md, AGENTS.md, .claude/*) — items not auto-edited

---

## Plan

See `plans/doc_fixes_applied.md` for fixes already applied (items 1-12) and `plans/doc_fixes_pending.md` for remaining items awaiting user approval (13-18).
