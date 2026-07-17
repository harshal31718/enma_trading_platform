# 0 — Fixes Queue (small, independent, ship-one-by-one)

**Role:** the *punch-list view* over the plan catalog. Where [`0_roadmap.md`](0_roadmap.md)
sequences whole plans by phase and [`0_tracker.md`](0_tracker.md) is the status board, this file
is a flat, dependency-light queue of the **small, self-contained, ship-any-time** items scattered
across the plans — the ones a single session can pick up top-down and close one by one without
booting a multi-day effort or a golden-master re-baseline round-trip.

**Created:** 2026-07-16. **Source of truth for scope stays the plan files** — this file only
sequences and points. Update the linked plan + `0_tracker.md` when an item ships; then delete the
row here (git history is the archive). *F1–F6 shipped 2026-07-16 and their rows were dropped
2026-07-16 per that rule — see git history / `handoff.md` for what they were.*

**Inclusion rule for this queue (all four must hold):**
1. ≤ ~1 session of work.
2. No dependency on Plan 5 fully landing, or on Plans 6/7 refactors.
3. Does **not** change backtest outputs (no golden-master re-baseline / sign-off needed), **or**
   is default-off/dead-code-path only.
4. Independently verifiable on its own.

Anything failing one of these lives in **§ Not in this queue** below with the reason.

---

## The queue (work top-down)

### F7 — Algo/conditional fill detection: fix the now-identified root causes · Plan 21 (21.1–21.2) · **21.1+21.2 code-shipped 2026-07-17, live verification pending**
- **History:** F7 began as "confirm `ORDER_TRADE_UPDATE` emits for algo orders". The 2026-07-16
  live Chaos run answered it (fills NOT reliably caught — ~50-55s UI/state staleness until the
  next candle's REST poll) and surfaced two more bugs (TP-placement 400s, FXSUSDT stuck open
  after stop). The Plan 21 audit (same day) then **identified the likely root causes by code
  read**, converting F7 from an investigation into a concrete fix list.
- **21.1 shipped 2026-07-17** (three surgical diffs, live-adapter/UDS-only, no golden master —
  see `21_live-algo-industry-standard-audit.md` Part C and `handoff.md`):
  - **A-2 [Certain] — fixed:** `_on_fill` crashed with `AttributeError` on every FILLED frame
    (`clientOrderId` key doesn't exist — Binance uses `c`; the `i` fallback is an int) — the
    reconcile call at the end of the callback never ran, so the event-driven path was dead code.
    Fixed via the new `_extract_fill_client_id()` helper + wrapping the OUO peer-cancel block in
    its own try/except so reconcile can't be skipped by an earlier failure. Tests:
    `engine/tests/test_on_fill_client_id_extraction.py`.
  - **A-1 [Certain] — fixed:** the userTrades real-exit reconstruction call omitted its required
    `api_key`/`api_secret` args → every `exchange_sync` close booked an estimate instead of
    Binance's authoritative fill. Credentials now passed. Tests:
    `engine/tests/test_query_real_exit_from_user_trades.py`.
  - **A-3 [Certain] — fixed:** `LISTEN_KEY_EXPIRED` `return`ed out of `_run_ws`, permanently
    killing the user-data stream on long sessions. Now `break`s the message loop so the outer
    reconnect `while` re-enters with the refreshed listen key. Tests:
    `engine/tests/test_uds_listen_key_expired_reconnect.py`.
  - **Not yet done:** the engine test suite has NOT been run inside the container (no Docker
    access from this session) — run `docker exec enma_trading_platform-engine-1 pytest
    /app/tests/test_query_real_exit_from_user_trades.py
    /app/tests/test_on_fill_client_id_extraction.py
    /app/tests/test_uds_listen_key_expired_reconnect.py` plus the full suite before treating 21.1
    as verified. A fresh small (1-3 symbol) live session against Binance Testnet is also needed to
    confirm the ~60s staleness is actually gone, per this queue's acceptance criterion below.
- **21.2 shipped 2026-07-17** (ACCOUNT_UPDATE-driven reconcile — closes the ~60s window regardless
  of Binance's algo-order event semantics): `_on_account_update` registered per symbol in
  `_run_symbol_loop` alongside `_on_fill`, reconciles immediately on any OPEN<->FLAT disagreement
  between Binance's `P[]` position delta and the local `strategy.position` view, debounced via the
  existing per-symbol lock (`.locked()` check — skip if a reconcile is already in flight). Decision
  logic in `_account_update_needs_reconcile()`. Tests:
  `engine/tests/test_account_update_reconcile_decision.py`. See
  `21_live-algo-industry-standard-audit.md` A-8 for the full writeup, including a correction: the
  UDS-side dispatch mechanism (`register_account_callback`) already existed in the repo before this
  session but was never invoked — 21.2 registers the missing consumer, not new plumbing.
- **Acceptance:** 21.1+21.2's diffs shipped + tested (code done, container test run + live session
  still pending); a small (1–3 symbol) live session shows a conditional SL/TP fill reflected in
  session state in seconds (not ~60s); the improved `_binance_error_detail` logging captures the
  real Binance code if the TP-400 reproduces.
- **Out of F7's scope, tracked separately:** TP-400 root cause (needs the reproduction with the
  fixed logging; Plan 21's A-7 stop re-arm converts this class to self-healing) and the
  FXSUSDT-stuck-open anomaly (needs that session's engine logs).

### F8 — Redis `requirepass` · Plan 4.5 · **needs an infra window**
- **What:** The one real infra item deferred from Plan 4 — authenticate Redis (`requirepass` + update
  every client connection string: server BullMQ/ioredis, engine, health check). Wide-ish blast radius
  (touches every service's Redis config) so it wants a deliberate window, not a squeeze-in.
- **Acceptance:** Redis rejects unauthenticated connections; all services reconnect; queues + pub/sub
  + cache all functional; `/health` still honest.
- **Effort:** small–medium but **touches every service's config** — do it when you can restart the
  full stack and watch it, not at the tail of another task. Last in the queue for that reason.

---

## Ordering rationale

1. **F7 first** — it is live-trading correctness debt with root causes already in hand; every
   live/chaos session run before 21.1 lands is trading on a dead event path and estimated PnL.
2. **F8 last** — the only item that wants a dedicated full-stack-restart window, unrelated to F7.

New small items from Plan 21 (21.3 bracket-cancel, 21.4 naked-position re-arm) and Plan 22
(22.2 liq-buffer wiring) are **deliberately not queued here yet** — they're sequenced in their
plan files behind 21.1/21.2; add them as F-rows only if they get picked up out of order.

---

## Not in this queue (and why)

These are real remaining work — they're just **not small**. Kept here so the queue's scope stays
honest. Full detail in each plan file; sequencing in [`0_roadmap.md`](0_roadmap.md) and
[`0_tracker.md`](0_tracker.md)'s Execution order.

| Item | Plan | Why it's out |
|------|------|--------------|
| Decimal money ledger | 5.5 | Largest/riskiest live piece; **needs a deliberate golden-master re-baseline with sign-off** (Rule C). Never bundle into a fixes pass. |
| Restart / recovery from event log | 5.6 | Depends on the "LiveSession becomes a pure projection" work 5.1 did *not* ship; multi-step, needs the projection built first. |
| `LiveBotManager` decomposition + Exchange abstraction | 6 | Multi-PR refactor; **blocked on Plan 5 fully landing** so the correctness model is settled before code moves. |
| Server/client structure (god-controllers, jobs-not-timeouts, `Trade.jsx` split) | 7 | Multi-day; depends on 2 (done) **and 5** (renders the new state model). |
| Warmup math (8.3), candle-column safety (8.4) | 8 | Both **golden-master-touching** — re-baseline + sign-off, not a quick fix. |
| Multi-session same-account modelling (8.6) | 8 | Product decision (forbid overlap vs central exposure model) before any code. |
| Funding ledger (9.7), intrabar sim (9.8), fill-model ladder (9.10) | 9 | **Change backtest outputs by design** → per-step golden-master re-baseline with sign-off. |
| Strategy Lab: job plumbing / UI / optimizer / MC-scored selection | 10 (1b–4) | Multi-day product surface (BullMQ jobs, `labResults`, new page, Optuna). |
| Informative / multi-timeframe `self.htf()` | 13 | Genuinely new *feature* work, not a "fix." Own focused pass, then 17. |
| Recursive-formula / warmup-insufficiency analysis | 17 | New analysis tool; **sequence after 13** so it also sweeps multi-TF indicators. |
| Session Risk Governor (all of Plan 22) | 22 | Multi-step new subsystem; **depends on 21.1–21.4 landing first** (a governor over a wrong-state fill path enforces limits against fiction). |
| Plan 21 remaining fixes (21.3–21.5, 21.7) | 21 | Sequenced behind 21.1/21.2 in the plan file; medium-sized, not squeeze-ins. |

**Rule of thumb:** if an item needs a golden-master sign-off, a Plan-5-complete precondition, or more
than a session, it belongs to a phase in `0_roadmap.md`, not to this queue.
