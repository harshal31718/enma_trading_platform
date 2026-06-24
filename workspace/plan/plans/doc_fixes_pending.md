# Plan: Pending Doc Fixes (Items 13-18 — Awaiting User Approval)

Originally from `workspace/issues_and_solutions/solutions/doc_fixes_pending.md` (merged into `plan/` 2026-06-24). These files are **user-owned** per GOVERNANCE.md — Claude must not edit without per-file direction.

Maps to analysis: `issues/documentation_drift.md`

---

| # | File(s) | Fix | Severity | Status |
|---|---------|-----|----------|--------|
| 13 | `.claude/settings.json` | Rotate GitHub PAT; replace literal with `${GITHUB_PERSONAL_ACCESS_TOKEN}` env interpolation. **Correction:** file is git-ignored (not in git history) — defense-in-depth only, not a breach | 🔴 High (reduced) | Awaiting user approval |
| 14 | `.claude/GOVERNANCE.md` | Update Part 2 Commands table: list all 10 commands (add `restyle-ui`, `check-boundaries`, `golden-check`, `depth-review`); add Workflows subsection for `enma-comprehensive-review.js`; fix Permissions section (`settings.json` committed → git-ignored); refresh `settings.local.json` description (allowlist has sprawled to ~60 entries) | 🟡 Medium | Partially done (renames applied) |
| 15 | `engine/CLAUDE.md` | Fix leaderboard sort "averageWinRate" → "averageNetProfit"; remove MicroScalper `import talib` claim (removed in BUG-05) | 🔴 High | Awaiting user approval |
| 16 | `client/CLAUDE.md` | Drop "JWT interceptor" from axios.js description; remove `useAuthStore.js` from store/ tree; fix leaderboard sort "Avg Win Rate" → net profit; reconcile TopBar.jsx/Navbar.jsx mention | 🔴 High | Awaiting user approval |
| 17 | `server/CLAUDE.md` | Remove "JWT auth middleware on all /api/v1/ routes" (contradicts own line 198); update top_symbols 70 → ~80 tiered | 🔴 High | Awaiting user approval |
| 18 | `AGENTS.md` | Fix git-visibility claim: `.claude/` + `.mcp.json` are git-ignored; `CLAUDE.md` + service CLAUDE.md + AGENTS.md + workspace/ are **tracked**. Fix "6 commands" → 10 | 🔴 High | Awaiting user approval |

---

## Follow-Up Checks Not Yet Done

- **DECISIONS.md + UI_STYLE_GUIDE.md** — not deep cross-checked in the audit pass. UI_STYLE_GUIDE needs verification against the `emerald-400`/`red-400` P&L invariant; DECISIONS needs verification against refactor history
- **3 unverified strategy docs** — BestSupertrend.md, MicroMacroRSIDivergence.md (already fixed), MultiDivergence.md params were not individually checked before their fixes were applied; confirm in a later pass
- **Indicator "Currently Used By" column** — not exhaustively verified; low risk but silently rots
