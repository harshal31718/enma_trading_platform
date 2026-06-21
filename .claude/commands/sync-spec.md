# Sync Spec

Required post-implementation verification checklist. Run this after every code change.

Work on Enma is NOT complete until every applicable item below is satisfied.

## Instructions

For every service and document modified, perform these verification steps:

1. **API Contracts**: If endpoints changed, update `workspace/docs/core/API_CONTRACTS.md` with the exact request/response shapes.

2. **Architecture**: If topology, database connections, or service bindings changed, update `workspace/docs/core/ARCHITECTURE.md`.

3. **Decisions**: If any core architectural choices (such as modifying `BaseStrategy` or database structures) were made, append them to `workspace/docs/core/DECISIONS.md` with decision + rationale.

4. **Current State**: Update `workspace/docs/state/CURRENT_STATE.md` to move tasks from planned to implemented.

5. **Deprecations**: If any component, folder, or configuration was deleted, log it in `workspace/docs/state/DEPRECATED.md` (what, why, when, what replaced it).

6. **Packages**: Register any new dependency in the relevant service `CLAUDE.md`.

## Output

Output a summary listing each document updated and any steps skipped. Do not silently skip steps — if a step is not applicable, say so in one line. If a step cannot be completed (e.g. uncertain about a decision), flag it explicitly.

## Completion Gate (absorbed from the former `/new-feature`)

A change is NOT done until **all** of the following hold:

- [ ] No stubs, TODOs, or placeholder logic remain.
- [ ] Linter / type-checker passes for every service touched.
- [ ] The doc-sync checklist above is complete — docs match what was built.
- [ ] Drift is clean — spawn the `drift-reviewer` agent; it must report zero boundary/contract violations.
