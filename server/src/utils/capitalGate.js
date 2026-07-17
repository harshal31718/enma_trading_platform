// Plan 22 Step 22.1 (B-11/B-12) — capital integrity gate, server side.
//
// B-11: session `capital` was an honor-system number — `startSession` only
// checked *presence* (`!capital` -> 400), never numeric validity or bounds,
// and never compared against the real Binance wallet. A non-numeric string
// crashed the engine's `float()` at session start; a negative value flowed
// straight through into sizing math.
//
// B-12: nothing summed committed capital across a user's concurrently
// running sessions — 10 bots x 1,000 capital each "allocates" 10,000 against
// whatever the wallet actually holds, and Chaos multiplies this further
// (each launched strategy gets its own full `capital`, so an N-strategy
// Chaos run commits capital x N with zero aggregate check).
//
// Decided 2026-07-17 (DECISIONS.md #23, Part F Q5): hard-reject non-numeric/
// negative/zero capital always; a request that would over-commit the wallet
// (requested + already-reserved > available balance) is a warn-and-confirm
// on testnet (fake money, users deliberately stress-test with oversized
// paper capital) — becomes a hard reject the day mainnet is ever considered.
//
// Kept as pure, standalone functions (no DB/HTTP) per this repo's own
// testing convention — the controller does the async balance fetch /
// LiveSession query and passes plain numbers in here.

/**
 * Validate a raw capital value is a genuinely usable positive number.
 * Deliberately conservative: NaN, Infinity, strings that don't parse
 * cleanly, zero, and negative values are all rejected. This is the "hard
 * reject always" half of the Q5 decision — no confirm flow overrides it.
 *
 * @param {*} rawCapital - whatever arrived in the request body (string/number/anything)
 * @returns {{ valid: boolean, value: number|null, error: string|null }}
 */
function validateCapitalValue(rawCapital) {
  const value = Number(rawCapital)
  if (!Number.isFinite(value)) {
    return { valid: false, value: null, error: 'capital must be a finite number' }
  }
  if (value <= 0) {
    return { valid: false, value: null, error: 'capital must be greater than zero' }
  }
  return { valid: true, value, error: null }
}

/**
 * Sum the `capital` field across a set of currently running/starting/
 * stopping LiveSession docs for this user — the B-12 reservation ledger.
 * Non-numeric stored values (shouldn't happen post-validateCapitalValue,
 * but defensively) are treated as 0 rather than corrupting the sum with NaN.
 *
 * @param {Array<{capital: string|number}>} runningSessions
 * @returns {number}
 */
function sumReservedCapital(runningSessions) {
  return (runningSessions || []).reduce((total, session) => {
    const value = Number(session && session.capital)
    return total + (Number.isFinite(value) ? value : 0)
  }, 0)
}

/**
 * Decide whether a new capital request over-commits the wallet, given what's
 * already reserved by this user's other running sessions.
 *
 * `availableBalance == null` means the balance fetch itself failed (network
 * blip, credentials not yet configured elsewhere in the flow, etc.) — in
 * that case we cannot make the over-commit determination at all, so this
 * returns `{ overCommit: false, checked: false }` rather than guessing;
 * the caller logs that the check was bypassed (mirrors the engine-side
 * backstop's own framing: this IS the primary check, the engine's
 * `_fetch_available_balance` clamp is the backstop for when this is
 * bypassed or skipped).
 *
 * @param {object} params
 * @param {number} params.requestedCapital - capital this new session/launch wants (Chaos: capital x strategyCount)
 * @param {number} params.reservedCapital - sum of this user's other running sessions' capital
 * @param {number|null} params.availableBalance - real wallet available balance, or null if unknown
 * @returns {{ checked: boolean, overCommit: boolean, totalCommitted: number, availableBalance: number|null }}
 */
function checkCapitalAgainstBalance({ requestedCapital, reservedCapital, availableBalance }) {
  const totalCommitted = requestedCapital + reservedCapital
  if (availableBalance == null) {
    return { checked: false, overCommit: false, totalCommitted, availableBalance: null }
  }
  return {
    checked: true,
    overCommit: totalCommitted > availableBalance,
    totalCommitted,
    availableBalance,
  }
}

module.exports = { validateCapitalValue, sumReservedCapital, checkCapitalAgainstBalance }
