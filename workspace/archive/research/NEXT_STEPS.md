# Enma Optimization — Next Steps

**Date:** 2026-06-17
**Parent:** `OPTIMIZATION_PLAN.md`

---

## Immediate Next Steps

### 1. Start with Phase 1 (Quick Wins)
These are low-risk, high-value changes that can be implemented in 1-2 weeks:

| Task | File(s) to Modify | Estimated Time |
|------|-------------------|----------------|
| **Parallel candle fetching** | `engine/services/candle_importer.py` | 2-3 hours |
| **Exponential backoff** | `engine/core/live_bot_manager.py` (line ~393) | 30 minutes |
| **React Query stale times** | `client/src/hooks/*.js` | 1 hour |
| **BullMQ retry config** | `server/src/services/backtestQueue.js` | 30 minutes |
| **Per-endpoint rate limits** | `server/src/app.js` | 1 hour |

### 2. Validate Before Implementing
Before any code changes:
1. Run existing tests: `pytest engine/` (if tests exist)
2. Run golden master: `python engine/scripts/golden_master.py`
3. Start the stack: `docker-compose up`
4. Run a backtest and verify results match

### 3. Implementation Rules
Per AGENTS.md:
- All changes stay in `engine/`, `server/`, or `client/` (layer boundaries)
- No new npm/pip packages without updating CLAUDE.md
- No changes to `.env` files
- Update `docs/state/CURRENT_STATE.md` after any feature change
- Engine writes backtestResults; server only updates status

---

## Priority Ranking (by Impact/Effort Ratio)

```
HIGH IMPACT, LOW EFFORT (do first):
  ├── Parallel candle fetching
  ├── Exponential backoff reconnection
  └── BullMQ retry with DLQ

HIGH IMPACT, MEDIUM EFFORT (do second):
  ├── Pre-compute indicators on full series
  ├── Centralized parameter injection
  └── Strategy SDK/template generator

MEDIUM IMPACT, MEDIUM EFFORT (do third):
  ├── Combined WS stream for live bots
  ├── API key rotation support
  ├── Graceful shutdown
  └── Heartbeat/watchdog monitoring

HIGH IMPACT, HIGH EFFORT (plan carefully):
  ├── Shared ExecutionEngine base class
  ├── Mainnet trading support
  └── Monte Carlo optimization
```

---

## Open Questions for User

Before proceeding with implementation, these decisions need user input:

1. **Mainnet trading:** Should we implement the mode selector now or defer?
   - Current: Testnet only
   - Proposed: Add mode toggle in Exchange Settings

2. **Strategy SDK:** Would a template generator be useful, or is manual creation preferred?

3. **Backtest comparison:** Is side-by-side comparison a priority feature?

4. **TypeScript migration:** Worth the effort for type safety, or stick with JSX?

5. **Multi-exchange:** Is this on the roadmap, or Binance-only indefinitely?

---

## Files Changed in This Session

| File | Action | Description |
|------|--------|-------------|
| `docs/changes/OPTIMIZATION_PLAN.md` | Created | Full optimization plan (28 items) |
| `docs/changes/NEXT_STEPS.md` | Created | This file — implementation roadmap |

---

## How to Use This Plan

1. **Read `OPTIMIZATION_PLAN.md`** for the full analysis
2. **Pick a Phase** based on your timeline
3. **Start with Quick Wins** — they're safe and immediately valuable
4. **Create a DECISIONS.md entry** for any architectural change
5. **Update CURRENT_STATE.md** after implementing each item
