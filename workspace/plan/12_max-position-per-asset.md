# Plan 12 — Max Position Per Asset

**Status:** Shipped 2026-07-15 (1a confirmed pre-existing, 1b implemented) · **Priority:** P2 · **Phase:** 9 · **Depends on:** 11 · **Related:** 6

## Shipped summary (2026-07-15) — 1b

Implemented as designed. `LiveAdapter.execute_entry()` (`engine/core/live_bot_manager.py`) gained
a `max_open_positions` check right after the existing rate-limiter guard — same pattern as the
TradingState/Protections/RateLimiter checks already there (log + `strategy.buy/sell = None` +
`return False`, no exception). Guard condition: `symbol not in session["open_positions"] and
len(session["open_positions"]) >= max_open_positions` — only blocks a genuinely new symbol; a
symbol already counted (e.g. a re-evaluation) is never blocked by its own presence. Session dict
gained a `max_open_positions` key (`None` = unlimited, the default — byte-identical to
pre-Plan-12 behavior for every existing session). Wired from Node:
`server/src/controllers/algo.controller.js`'s `startSession` reads an optional `maxOpenPositions`
from the request body and passes it as `max_open_positions` to the engine; omitted/invalid values
resolve to `null` (unlimited). **Chaos sessions deliberately not wired** — chaos mode's per-
strategy fixed-symbol-list design doesn't have an obvious single cap semantic yet, and leaving it
unwired is automatically safe (engine defaults to unlimited when the key is absent). No new UI
control was added (out of scope for 1b's minimal design — the plan only calls for "server passes
it", not a wizard field); a future Settings/wizard field can set `maxOpenPositions` in the
request body without any further engine change.

**Verified:** 3 new tests in `engine/tests/test_live_fill_booking.py` — blocked when at cap (and
confirms zero order calls attempted, not just a returned `False`), allowed for a symbol already
counted even at cap, and unset cap behaves exactly as before. Full engine suite 127/127 (was 124;
+3). No golden-master re-check needed — this only touches `LiveAdapter` (live path), zero import
overlap with the backtest path, same reasoning as every other live-adapter-only change this
session.

> **2026-07-15 audit confirmation:** sub-item 1a below (per-asset notional cap) is already live —
> `engine/core/strategy.py:353`'s `max_qty()` clamps against `self.max_exposure_notional`, wired
> from both `backtest_runner.py:900` and `live_bot_manager.py:1096`. The "verify V0" conditions
> in 1a and the Sequencing section are resolved: it's wired. Only **1b** (session-level
> `max_open_positions` count gate) is unbuilt.

**Goal:** Cap exposure on a per-symbol basis so a single asset can't dominate the portfolio, and
cap the number of concurrent open positions in live/chaos multi-symbol runs.

---

## Current state (audited)

- `engine/core/models/portfolio.py:63–70` — `DefaultPortfolioModel.construct()` already enforces an
  **aggregate** risk cap: `max_portfolio_risk` (default 0.06) vetoes a new entry if
  `(risk_per_unit × qty) / equity > max_portfolio_risk`. This is portfolio-wide, **not per-asset**.
- The (deleted) Risk Dashboard plan §6 specified `max_exposure_notional` (per-symbol notional cap) via
  `engine/core/strategy.py → max_qty()`. **Audit it during V0** — if present, S1's notional cap is
  partially done and S1 only adds the *count* cap. If absent, S1 adds both.
- Backtest is single-symbol per run, so "max open positions" only bites in **live/chaos**
  (`engine/core/live_bot_manager.py`) where many symbols run under one session.

## Upstream reference

- **freqtrade `max_open_trades`** — a global integer ceiling on concurrent open trades across all
  pairs. When at the cap, new entry signals are skipped (not queued). Also `max_position_size` /
  per-pair stake limits cap notional per asset.
- **nautilus `PositionId` limits / risk engine** — `max_notional_per_order`, `max_notionals_per_day`,
  and per-instrument position caps enforced in the `RiskEngine` before an order is routed.

Both enforce **at the gate, before sizing commits** — exactly where Enma's PCM `construct()` sits.

## Design

Two independent, additive caps. Both default to "off/∞" so golden master is byte-identical.

### 1a. Per-asset notional cap (engine, PCM)
- Read `max_exposure_notional` off the strategy (already injected per-symbol via the risk resolver).
- In `DefaultPortfolioModel.construct()`, after `_size()` and before the `max_portfolio_risk` veto,
  clamp: `raw_qty = min(raw_qty, max_exposure_notional / s.price)` when `max_exposure_notional` is finite.
- If `max_qty()` already applies it (verify V0), no change here — just confirm.

### 1b. Max concurrent open positions (live/chaos only)
- This is a **session-level** concern, not a per-strategy one — `live_bot_manager.py` owns the set of
  active symbols and their open/flat state.
- Add `max_open_positions` to the session config (server passes it; default `None` = unlimited).
- Before a symbol's loop opens a new position, `LiveBotManager` checks the count of currently-open
  symbols in the session; if `>= max_open_positions`, **skip the entry this candle** (log it, don't error).
- Mirror freqtrade: skip, don't queue. Next candle re-evaluates.

> Keep 1b out of the five-model pipeline — the pipeline is per-symbol and must stay golden-master
> pure. The count gate lives in the session orchestrator above it.

## Files to create / modify

| Action | File | Change |
|--------|------|--------|
| Modify | `engine/core/models/portfolio.py` | Per-asset notional clamp in `construct()` (1a), if not already in `max_qty()` |
| Modify | `engine/core/live_bot_manager.py` | `max_open_positions` count gate before entry (1b) |
| Modify | `server/src/controllers/algo.controller.js` | Pass `maxOpenPositions` from session/chaos config to engine |
| Modify | `server/src/models/Settings.js` | Add `maxOpenPositions` to chaos/global defaults (optional) |
| Create | `engine/tests/test_max_position_caps.py` | Unit: notional clamp + count gate |

## Verification gate

- **Golden master byte-identical** with defaults off (`max_exposure_notional=∞`, `max_open_positions=None`):
  `golden_master compare --a baseline --b s1` must be OK on all 5 strategies.
- Unit test: with `max_exposure_notional` set below the natural size, qty is clamped exactly.
- Unit/integration: a 3-symbol session with `max_open_positions=2` never holds 3 at once.

## Sequencing & risks

- **First** after V0 — smallest blast radius, pure risk primitive.
- Risk: 1b touches the live loop; an off-by-one in the count gate could deadlock entries. Gate must
  count **open** positions only (exclude pending/closing) and re-check each candle.
- Depends on V0 confirming whether `max_exposure_notional` is already wired (avoids double-clamping).
