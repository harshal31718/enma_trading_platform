# Skills / Commands — Discovery Pointer

Skills live in `.claude/commands/` and are invocable as `/command-name` in Claude Code
sessions or via the Skill tool in the agent harness. All files are plain Markdown — any AI
tool can read them directly at `.claude/commands/<name>.md`.

This file exists only so tools that don't auto-discover `.claude/commands/` know where to look.

---

## Canonical inventory

**`.claude/GOVERNANCE.md` → Part 2 (AI Infrastructure Inventory)** is the single source of truth
for the full skill/command list (currently **6 commands + 1 agent**), their types, and status.
**Do not duplicate the list here** — read it there to avoid the count/status drift that comes from
parallel copies.

---

## Auto-Deployment Rule

For tasks that match a skill's trigger, **invoke the skill automatically** — don't wait to be
asked:
- Adding an indicator → `/add-indicator` first
- Adding a strategy → `/add-strategy` first
- Implementation complete → `/sync-spec` before reporting done
- Large refactor complete → spawn the `drift-reviewer` agent

Full specification: `CLAUDE.md` → Rule F (Subagent / Skill Auto-Deployment).
