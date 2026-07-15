# workspace/ — Shared Project Memory

Tracked-in-git documentation shared by every AI agent and the user. Entry point for agents is
`AGENTS.md` (repo root); this file is the map of what lives here and the rules that keep it minimal.

## Layout

| Path | What | Changes |
|------|------|---------|
| `docs/core/` | Durable knowledge: `ARCHITECTURE`, `API_CONTRACTS`, `DECISIONS`, `MODELS`, `binance-api`, `UI_STYLE_GUIDE` | Rarely; on architectural change |
| `docs/state/CURRENT_STATE.md` | **Single source of truth** for what is implemented right now | Every feature change |
| `docs/state/DEPRECATED.md` | What was removed — never reference or rebuild these | Every removal |
| `docs/features/<name>/SPEC.md` | Per-feature deep specs (threshold rules in `.claude/GOVERNANCE.md`) | Per feature |
| `docs/indicators/`, `docs/strategies/` | Catalogs, one file per item + `INDEX.md` | When adding one |
| `docs/ops/DEPLOYMENT.md` | Production deployment runbook (OCI VPS, nginx/TLS, dev/main branch model) | Per deploy learning |
| `plan/` | Forward build queue: numbered specs `1–19` + `ref_*` research/backlog + `mergeContext.md` | When planning/shipping |
| `plan/handoff.md` | Session resume log — **max 3 entries**, newest first | Every multi-phase session |
| `skills/README.md` | Thin pointer to the skill inventory (canonical list in `.claude/GOVERNANCE.md` Part 2) | Never |

## Lifecycle rules (keep it minimal)

1. **Git history is the archive.** When a plan/spec is fully shipped and reconciled into
   `CURRENT_STATE.md`, **delete the file** — do not create archive folders or redirect stubs.
2. **Every removal gets a `DEPRECATED.md` entry** (what, why, when, replacement) and all references
   to it are removed from active docs.
3. **`handoff.md` is a resume prompt, not a log.** Adding entry 4 deletes entry 1.
4. **Code wins over docs.** If they disagree, fix the docs immediately.
5. **New docs go where the table says** — anything that doesn't fit is probably transient and
   belongs in `plan/` until shipped, then deleted per rule 1.
