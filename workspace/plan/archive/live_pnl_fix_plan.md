# Plan: Live PnL Resolution in Algo Trading (SessionCard)

This document analyzes the issue where the `Live PnL` displays as `—` (dash) for active bot positions that were opened before the user loaded or refreshed the frontend page. It proposes concrete solutions to synchronize the initial state.

---

## 1. Root Cause Analysis
*   In [SessionCard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/algo/SessionCard.jsx), the `livePnl` of open positions is calculated dynamically using:
    ```javascript
    const d = positionDetails[sym]
    const cur = prices[sym]
    if (d && cur) { ... }
    ```
*   `positionDetails` is local component state initialized to an empty object `{}`.
*   This state is only populated when the client receives the socket event `algo:position:open` which triggers during a live trade entry.
*   If a user reloads the browser, logs in, or opens the tab *after* a position has already been opened by a bot, the component does not receive the `algo:position:open` event.
*   Because `positionDetails[sym]` is `undefined`, the frontend lacks entry price and size details. The live PnL calculation defaults to `null` and displays as `—` (though `QNTUSDT` in the user's image shows a live P&L because it was entered while the browser socket session was active).

---

## 2. Brainstormed Solutions

### Option A: Persistent DB Storage of Position Details (Recommended)
*   **Design:** Save position details directly into the MongoDB session document when they are opened, and clear them when they are closed.
*   **Server Changes:**
    1.  Update `server/src/models/LiveSession.js` to add a new `positionDetails` field:
        ```javascript
        positionDetails: { type: mongoose.Schema.Types.Mixed, default: {} }
        ```
    2.  Update the `handleEngineStats` controller in `server/src/controllers/algo.controller.js`:
        *   On `event === 'position:open'`:
            ```javascript
            await LiveSession.findByIdAndUpdate(id, {
              $set: { [`positionDetails.${eventData.symbol}`]: eventData }
            })
            ```
        *   On `event === 'position:close'`:
            ```javascript
            await LiveSession.findByIdAndUpdate(id, {
              $unset: { [`positionDetails.${eventData.symbol}`]: "" }
            })
            ```
*   **Frontend Changes:**
    *   In `client/src/components/algo/SessionCard.jsx`, initialize the state directly from the pre-loaded session:
        ```javascript
        const [positionDetails, setPositionDetails] = useState(() => session.positionDetails || {})
        ```
*   **Pros:**
    *   Zero dynamic engine-polling overhead on page load/render.
    *   The database serves as a robust source of truth.
    *   Fast initial page render.
*   **Cons:**
    *   Requires a small Mongoose schema migration (non-breaking, since default is `{}`).

---

### Option B: Query Engine Status on Component Mount/Expand
*   **Design:** Retrieve active position details directly from the running engine process when the session card expands or mounts.
*   **Engine Changes:**
    *   Update `get_session_status` in `engine/core/live_bot_manager.py` to return the full `open_positions` dictionary (containing entries like `side`, `price`, `qty`, `leverage`) as `openPositionsDetails`:
        ```python
        return {
            "status": session["status"],
            "pnl": str(round(session["pnl"], 2)),
            "openPositions": open_pos,
            "openPositionsDetails": session.get("open_positions", {})
        }
        ```
*   **Server Changes:**
    *   Provide a proxy endpoint on the Node server (e.g. `GET /api/v1/algo/sessions/:id/positions`) that queries the engine status.
*   **Frontend Changes:**
    *   In `SessionCard.jsx`, perform an `useEffect` fetch when the card mounts or is expanded, and merge the returned positions into `positionDetails` state.
*   **Pros:**
    *   No Mongoose schema changes required.
*   **Cons:**
    *   Creates a cascade of REST calls (React → Node → Python) when loading the Algo Trading page, making page load slower.
    *   Unusable if the engine process restarts or is temporarily unresponsive.

---

## 3. Recommended Approach
Implement **Option A** because it decouples frontend loading from engine API availability and maintains state robustness in MongoDB.
