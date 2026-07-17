# Plan 14 — Webhook Notifications

**Status:** Shipped 2026-07-16 (fixes-queue F3) · **Priority:** P2 · **Phase:** 9 · **Depends on:** 11 (independent) · **Related:** —

**Goal:** POST a JSON payload to a user-configured URL on trade lifecycle events (entry, exit,
liquidation, session start/stop, error) so Enma can push to Discord/Slack/IFTTT.

## Shipped summary (2026-07-16)

Implemented as designed below, with one scope note: `handleEngineStats` is server-side event
fan-out as planned, but the six lifecycle events map to the two existing hook points rather than
new engine instrumentation — `startSession` (session_start) and `handleEngineStats`'s
`position:open`/`position:close`/`status:error`/`stopped` branches (entry_fill, exit_fill +
conditional `liquidation` when `exitReason === 'liquidation'`, session_error, session_stop). The
`liquidation` event is wired and tested but not yet observed live — the live adapter's
`execute_exit` never currently passes `reason="liquidation"` (that path is backtest-only in
`kernel.py`; live liquidation would surface via reconciliation with some other reason today), so
this event fires the day live liquidation detection lands, not before.

Files: `server/src/models/Settings.js` (`webhook` sub-schema), new `server/src/utils/webhook.js`
(`dispatchWebhook`, `sendTestWebhook`, `VALID_EVENTS`), new `server/src/utils/__tests__/
webhook.test.js` (14 tests), `server/src/controllers/settings.controller.js` (nested-object
validation + `testWebhook` controller, same dot-path pattern as `limits`), `server/src/routes/
settings.routes.js` (`POST /webhook/test`), `server/src/controllers/algo.controller.js` (dispatch
call sites), `client/src/hooks/useExchangeSettings.js` (`useTestWebhook`), `client/src/pages/
Settings.jsx` (Notifications panel).

Verification: unit tests caught a real bug (`events: []` was being treated as "unfiltered"
instead of "opted into nothing" — fixed the filter's short-circuit condition); full server suite
63/63 after the fix. Live-verified via Claude in Chrome against the actual running stack: panel
renders, "Send Test" round-trips a real HTTP POST (both a failure — httpbin.org 503 — and a
success — postman-echo.com 200 — surfaced correctly as toasts), and the saved config survives a
full page reload (persisted through Mongo, not just local state). No golden master needed
(server-only change, zero engine/pipeline touch).

**Not done / deferred:** Telegram (explicitly out of scope per the original design). A real live
`exit_fill` delivery during an actual bot/chaos session was not separately observed — the "Send
Test" round trip plus the unit-tested dispatch logic covers this at the point of shipping; revisit
if a future session runs a live/chaos session and can confirm a real trade event lands.

---

## Current state (audited)

- **Nothing exists.** Grep for `webhook|telegram|notify.*url` across `server/src`, `client/src`,
  `engine/` returns nothing.
- The server already owns the live-session event stream: `server/src/controllers/algo.controller.js`
  has `handleEngineStats` which processes engine events (`position:open`, `position:close`, etc.) and
  persists to `LiveSession`. **This is the natural emit point** — webhooks fire from the same handler.
- **Revised 2026-07-02 — premise was stale.** Originally scoped as "one global webhook config, no
  per-user routing" under the single-user assumption. That assumption no longer holds: multi-user
  Google OAuth + JWT auth has shipped, and `Settings` (`server/src/models/Settings.js:5`) is now a
  required, unique `userId`-keyed document, not a global singleton. Webhook config must be scoped per
  user (a field on the per-user `Settings` doc), and `handleEngineStats`/the emit point must resolve
  the webhook URL for the `LiveSession`'s owning `userId`, not a single global value.

## Upstream reference (freqtrade webhooks)

From freqtrade's webhook config:
- **Events:** `entry`, `entry_fill`, `entry_cancel`, `exit`, `exit_fill`, `exit_cancel`, `status`.
- **Config:** `{enabled, url, format: form|json|raw, retries, retry_delay, timeout, <per-event templates>}`.
- **Entry payload fields:** `trade_id, exchange, pair, direction, leverage, open_rate, amount,
  stake_amount, order_type, current_rate, enter_tag`.
- **Exit payload adds:** `gain, close_rate, profit_amount, profit_ratio, exit_reason, open_date,
  close_date, is_final_exit`.
- Delivery is **fire-and-forget with bounded retries** — a webhook failure never blocks trading.

## Design (Enma-native)

Server-side only (server owns event fan-out; engine stays Binance-isolated and stateless re: notifications).

### Config (`Settings`)
```js
webhook: {
  enabled:   { type: Boolean, default: false },
  url:       { type: String,  default: '' },
  format:    { type: String,  enum: ['json','form'], default: 'json' },
  events:    { type: [String], default: ['exit_fill','liquidation','session_error'] }, // opt-in subset
  retries:   { type: Number, default: 2 },
  timeoutMs: { type: Number, default: 5000 },
}
```

### Emitter (`server/src/utils/webhook.js` — new)
- `dispatchWebhook(eventType, payload)` — reads `Settings.webhook`; if disabled or event not in
  `events`, no-op. Otherwise POST with `retries`/`timeoutMs`, **never throw** (catch + log).
- Use the existing HTTP client already in `server/` (axios/got — match whatever `engineClient` uses).
- Payload shape mirrors freqtrade so existing Discord/IFTTT recipes work:
  ```json
  { "event": "exit_fill", "symbol": "BTCUSDT", "side": "long", "qty": "0.5",
    "entryPrice": "...", "exitPrice": "...", "pnl": "...", "pnlPct": "...",
    "exitReason": "take_profit", "strategy": "AdaptiveTrend", "sessionId": "...",
    "ts": "2026-06-25T12:00:00Z" }
  ```

### Wiring
- In `algo.controller.js → handleEngineStats`, after persisting each event, call `dispatchWebhook()`:
  - `position:open` → `entry_fill`
  - `position:close` → `exit_fill` (include `exitReason`; if `liquidation`, also `liquidation` event)
  - session lifecycle → `session_start` / `session_stop` / `session_error`
- All numeric fields are **strings** (per `API_CONTRACTS.md` formatting rule).

### Client
- Settings page: a "Notifications" panel — enable toggle, URL input, event checkboxes, "Send test"
  button (`POST /api/v1/settings/webhook/test` → dispatches a dummy `status` payload).

## Files to create / modify

| Action | File | Change |
|--------|------|--------|
| Create | `server/src/utils/webhook.js` | `dispatchWebhook()` + retry/timeout |
| Modify | `server/src/models/Settings.js` | `webhook` sub-schema |
| Modify | `server/src/controllers/settings.controller.js` | validate webhook config + `testWebhook()` |
| Modify | `server/src/routes/settings.routes.js` | `POST /webhook/test` |
| Modify | `server/src/controllers/algo.controller.js` | call `dispatchWebhook()` in `handleEngineStats` |
| Modify | `client/src/pages/Settings.jsx` | Notifications panel (no rounded corners, emerald/red tokens) |
| Create | `server/test/webhook.test.js` | unit: disabled no-op, event filter, retry on failure, never-throws |

## Verification gate

- Unit: disabled config → no HTTP call; event not in `events` → no call; failing endpoint → retries
  then swallows (no throw, trade path unaffected).
- Manual: point `url` at a webhook.site bin, run a backtest-to-live or a chaos session, confirm a real
  `exit_fill` payload lands.

## Sequencing & risks

- Independent — can ship any time after V0 (no engine/pipeline touch, no golden master).
- Risk: a slow/hanging webhook endpoint must never stall `handleEngineStats`. Enforce `timeoutMs` and
  fire without `await` blocking the persist path (dispatch after the DB write resolves).
- Out of scope (deferred per `ref_gap-matrix-freqtrade-nautilus.md`): Telegram. Webhooks cover the notification need.
