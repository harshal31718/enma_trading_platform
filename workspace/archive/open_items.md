# Open Items — Planning Decisions Resolved

Sourced from: `workspace/issues_and_solutions/open_items.md` (merged into `plan/` 2026-06-24) and updated following user commits on 2026-06-24.

---

## Approved and Applied (Metadata & Config Files)

The following items from the previous audit have been successfully resolved and committed by the user:

| # | File | Action Taken | Status |
|---|------|--------------|--------|
| 1 | `.claude/settings.json` | Review GitHub PAT rotation (local-only, git-ignored) | User Action Done / Pending Local Rotation |
| 2 | `.claude/GOVERNANCE.md` | Updated Part 2 Commands table to list all 10 commands; added workflows; fixed permissions | **Applied (2026-06-24)** |
| 3 | `engine/CLAUDE.md` | Fixed leaderboard sort + MicroScalper `import talib` claim | **Applied (2026-06-24)** |
| 4 | `client/CLAUDE.md` | Swept JWT/auth references; fixed leaderboard sort; reconciled TopBar/Navbar | **Applied (2026-06-24)** |
| 5 | `server/CLAUDE.md` | Removed JWT middleware claims; updated top symbols count | **Applied (2026-06-24)** |
| 6 | `AGENTS.md` | Fixed git-visibility claims and command count | **Applied (2026-06-24)** |

---

## Follow-Up passes & Checks (Scheduled)

| Area | What to Check | Why |
|------|---------------|-----|
| `DECISIONS.md` | Verify against refactor history | Completed during audit |
| `UI_STYLE_GUIDE.md` | Verify `emerald-400`/`red-400` P&L invariant in client | Completed during audit |
| Indicator "Currently Used By" column | Cross-reference against 5 strategy files | Completed and updated |
| Strategy doc params (BestSupertrend etc.) | Confirm their PARAMS table fixes were correct | Completed during validation |

---

## Refactor Priority

1. **Strategy Performance Refactor** — High priority; next planned implementation step to resolve O(N²) indicator recomputation.
2. **Risk Model Improvements** — Additive, improves P&L, no breaking changes.
