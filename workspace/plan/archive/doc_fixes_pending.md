# Plan: Resolved Doc Fixes (Items 13-18)

Originally from `workspace/issues_and_solutions/solutions/doc_fixes_pending.md` (merged into `plan/` 2026-06-24). These changes have been successfully approved and applied in the repository.

Maps to analysis: `issues/documentation_drift.md`

---

| # | File(s) | Fix | Severity | Status |
|---|---------|-----|----------|--------|
| 13 | `.claude/settings.json` | Rotate GitHub PAT; replace literal with `${GITHUB_PERSONAL_ACCESS_TOKEN}` env interpolation. **Correction:** file is git-ignored (not in git history) — defense-in-depth only, not a breach | 🔴 High (reduced) | User Action Done |
| 14 | `.claude/GOVERNANCE.md` | Update Part 2 Commands table: list all 10 commands (add `restyle-ui`, `check-boundaries`, `golden-check`, `depth-review`); add Workflows subsection for `enma-comprehensive-review.js`; fix Permissions section (`settings.json` committed → git-ignored); refresh `settings.local.json` description (allowlist has sprawled to ~60 entries) | 🟡 Medium | Applied (2026-06-24) |
| 15 | `engine/CLAUDE.md` | Fix leaderboard sort "averageWinRate" → "averageNetProfit"; remove MicroScalper `import talib` claim (removed in BUG-05) | 🔴 High | Applied (2026-06-24) |
| 16 | `client/CLAUDE.md` | Drop "JWT interceptor" from axios.js description; remove `useAuthStore.js` from store/ tree; fix leaderboard sort "Avg Win Rate" → net profit; reconcile TopBar.jsx/Navbar.jsx mention | 🔴 High | Applied (2026-06-24) |
| 17 | `server/CLAUDE.md` | Remove "JWT auth middleware on all /api/v1/ routes" (contradicts own line 198); update top_symbols 70 → ~80 tiered | 🔴 High | Applied (2026-06-24) |
| 18 | `AGENTS.md` | Fix git-visibility claim: `.claude/` + `.mcp.json` are git-ignored; `CLAUDE.md` + service CLAUDE.md + AGENTS.md + workspace/ are **tracked**. Fix "6 commands" → 10 | 🔴 High | Applied (2026-06-24) |

---

## Follow-Up Checks Completed / Scheduled

- **DECISIONS.md + UI_STYLE_GUIDE.md** — Verified and synchronized.
- **3 strategy docs** — BestSupertrend.md, MicroMacroRSIDivergence.md, and MultiDivergence.md param tables verified against strategy implementations.
- **Indicator "Currently Used By" column** — Verified.
