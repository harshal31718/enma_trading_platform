# Open Items — Planning Decisions Needed

Sourced from: `workspace/issues_and_solutions/open_items.md` (merged into `plan/` 2026-06-24).

---

## Awaiting Your Approval (User-Owned Files)

| # | File | Action Needed | Risk If Deferred |
|---|------|---------------|------------------|
| 1 | `.claude/settings.json` | Rotate literal GitHub PAT; replace with `${GITHUB_PERSONAL_ACCESS_TOKEN}` | Plaintext PAT on local disk (file is git-ignored — not a repo breach) |
| 2 | `.claude/GOVERNANCE.md` | Update Part 2 Commands table (10 commands); add Workflows section; fix Permissions section | Stale docs mislead agents about available commands |
| 3 | `engine/CLAUDE.md` | Fix leaderboard sort + MicroScalper `import talib` claim | Agents reading this will parrot wrong claims |
| 4 | `client/CLAUDE.md` | Sweep JWT/auth refs; fix leaderboard sort; reconcile TopBar vs Navbar | Same — wrong claims propagate |
| 5 | `server/CLAUDE.md` | Remove phantom JWT middleware claim; update top_symbols count | Same |
| 6 | `AGENTS.md` | Fix git-visibility claim + command count | Every agent reads this first — wrong info on day one |

## Follow-Up Passes Not Yet Scheduled

| Area | What to Check | Why |
|------|---------------|-----|
| `DECISIONS.md` | Verify against refactor history | Not deep-checked in audit |
| `UI_STYLE_GUIDE.md` | Verify `emerald-400`/`red-400` P&L invariant in client | Not deep-checked in audit |
| Indicator "Currently Used By" column | Cross-reference against 5 strategy files | Low risk, silently rots |
| 3 remaining strategy doc params (BestSupertrend etc.) | Confirm their PARAMS table fixes were correct | Were applied but initial verification was deferred |

## Refactor Priority

1. **Doc fixes (items 2-6)** — quick, low risk, fixes agent onboarding
2. **Strategy perf refactor** — ~12 hours of coding, yields measurable speedup
3. **Risk model improvements** — additive, no breaking changes, improves P&L

---

## Historical Context (From Merged Sources)

This section preserved from the original `issues_and_solutions/open_items.md` for reference.

### Renames Completed Prior to Merge
| Old Name | New Name | Scope |
|----------|----------|-------|
| `add-endpoint.md` | `create-api-endpoint.md` | File rename in `.claude/commands/` |
| `restyle-ui.md` | `ui-restyle.md` | File rename in `.claude/commands/` |
| `/add-endpoint` | `/create-api-endpoint` | GOVERNANCE.md Part 2 reference |
| `/restyle-ui` | `/ui-restyle` | GOVERNANCE.md Part 2 reference |

### Deleted After Merge
- `workspace/issues_and_solutions/` → merged into `plan/` (this directory)

### Related Files That Were NOT Merged (Still in Place)
- `workspace/plan/handoff.md` — session resume log; referenced by `AGENTS.md` Session Handoff section
- `workspace/plan/future_paths.md` — long-horizon roadmap
