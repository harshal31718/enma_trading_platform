/**
 * chaosAllocator.js — Pure symbol allocation for Chaos Mode.
 *
 * No I/O, no DB calls, no Binance calls. Deterministic given the same inputs.
 * Designed to be unit-testable in isolation.
 *
 * Semantics (Resolved Decisions D1/D2/D3/D4 — see DECISIONS.md #16, #21):
 *   D1 — Leftovers distributed round-robin across ALL active strategies, up to
 *        each strategy's maxSymbolsPerBot and the run's chaosMaxTotalSymbols.
 *        A "manual" strategy keeps its hand-picked symbols AND still receives
 *        a share of the leftover pool (bounded by the same two caps). Symbols
 *        that don't fit either cap are reported in `dropped`, not an error.
 *   D2 — Manual symbol cap (maxManualSymbols) plus the per-bot/total-run caps
 *        (maxSymbolsPerBot/chaosMaxTotalSymbols — see Settings.limits). Each
 *        symbol used by exactly one strategy (no cross-strategy sharing).
 *   D3/D4 — Pool split into 3 volume tiers (high/mid/low). Distributed via
 *        round-robin within each tier → every strategy gets a comparable mix.
 */

const { TIERED_SYMBOLS: STATIC_TIERED } = require('../constants/top_symbols')

/**
 * Fisher–Yates in-place shuffle (mutates the array).
 * @param {any[]} arr
 */
function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}

/**
 * Allocate symbols for a Chaos Mode run.
 *
 * @param {Object} opts
 * @param {string[]}                opts.activeStrategies    Strategy names in run order (already capped).
 * @param {Object.<string,string[]>} opts.manualPicks        { strategyName: [symbol, …] } — hand-picked per strategy.
 * @param {string[]}                opts.lockedSymbols       Symbols locked by OTHER live sessions (skip from pool).
 * @param {string[]}                opts.curatedSymbols      Full curated list (TOP_SYMBOLS from top_symbols.js).
 * @param {number}                  opts.maxManualSymbols    Hard cap on reserved picks per strategy.
 * @param {number}                  opts.maxSymbolsPerBot    Hard cap on total symbols (reserved + leftover) per strategy.
 * @param {number}                  opts.chaosMaxTotalSymbols Hard cap on the sum of symbols across the whole run.
 *
 * @returns {{
 *   assignments: Object.<string, string[]>,   // { strategyName: [finalSymbols] }
 *   dropped: string[],                        // pool symbols that couldn't be assigned (per-bot or total cap reached)
 *   errors: { strategy: string, code: string, message: string }[]
 * }}
 *
 * Throws { status: 400, code, message } for hard validation failures (duplicate manual picks,
 * symbol not in curated list, manual picks alone exceeding a cap, etc.) — the controller
 * converts these to ApiError.
 */
function allocateChaosSymbols({ activeStrategies, manualPicks = {}, lockedSymbols = [], curatedSymbols, maxManualSymbols, maxSymbolsPerBot, chaosMaxTotalSymbols, tierMap: tierMapInput }) {
  const errors = []
  const lockedSet = new Set(lockedSymbols)
  const curatedSet = new Set(curatedSymbols)

  // ── STEP 1: Validate + reserve manual picks ──────────────────────────────────
  // Rules: symbol ∈ curated list, symbol not locked, no cross-strategy duplicate.
  const globalClaimed = new Set()  // union of all manual picks — uniqueness guard
  const reservedMap = {}           // { strategyName: Set<symbol> }

  for (const strat of activeStrategies) {
    reservedMap[strat] = new Set()
    const picks = manualPicks[strat] || []

    if (picks.length > maxManualSymbols) {
      throw {
        status: 400,
        code: 'CHAOS_MANUAL_CAP_EXCEEDED',
        message: `Strategy "${strat}" has ${picks.length} manual symbols but the cap is ${maxManualSymbols}.`,
      }
    }

    for (const sym of picks) {
      if (!curatedSet.has(sym)) {
        throw {
          status: 400,
          code: 'CHAOS_SYMBOL_NOT_IN_LIST',
          message: `Symbol "${sym}" (strategy "${strat}") is not in the curated Chaos symbol list.`,
        }
      }
      if (globalClaimed.has(sym)) {
        throw {
          status: 400,
          code: 'CHAOS_SYMBOL_DUPLICATE',
          message: `Symbol "${sym}" is manually assigned to more than one strategy.`,
        }
      }
      if (lockedSet.has(sym)) {
        throw {
          status: 409,
          code: 'CHAOS_SYMBOL_LOCKED',
          message: `Symbol "${sym}" (strategy "${strat}") is locked by another live session.`,
        }
      }
      reservedMap[strat].add(sym)
      globalClaimed.add(sym)
    }

    // Manual picks are a user-explicit guarantee (D1) — over-budget manual picks must be a
    // hard validation error, never silently dropped to satisfy the per-bot cap.
    if (reservedMap[strat].size > maxSymbolsPerBot) {
      throw {
        status: 400,
        code: 'CHAOS_SYMBOL_PER_BOT_CAP_EXCEEDED',
        message: `Strategy "${strat}" has ${reservedMap[strat].size} manually-picked symbols but the per-bot cap is ${maxSymbolsPerBot}.`,
      }
    }
  }

  // Same guarantee, run-wide: manual picks across all strategies must never be silently
  // trimmed to fit the total cap.
  const totalReserved = Object.values(reservedMap).reduce((sum, set) => sum + set.size, 0)
  if (totalReserved > chaosMaxTotalSymbols) {
    throw {
      status: 400,
      code: 'CHAOS_TOTAL_CAP_EXCEEDED',
      message: `Manually-picked symbols total ${totalReserved} across all strategies, exceeding the chaos run cap of ${chaosMaxTotalSymbols}.`,
    }
  }

  // ── STEP 2: Build the free pool (curated − reserved − locked) ────────────────
  const pool = curatedSymbols.filter((s) => !globalClaimed.has(s) && !lockedSet.has(s))

    // ── STEP 3: Bucket + shuffle pool by tier (D3/D4) ───────────────────────────
    // Accept an optional tierMap; fall back to static TIERED_SYMBOLS.
    const tierMap = new Map(
      (tierMapInput || STATIC_TIERED).map((e) => [e.symbol, e.tier])
    )
    function _bucket(arr) {
      const r = { high: [], mid: [], low: [] }
      for (const sym of arr) r[tierMap.get(sym) || 'low'].push(sym)
      return r
    }
    const { high, mid, low } = _bucket(pool)
    shuffle(high)
    shuffle(mid)
    shuffle(low)

  // ── STEP 4: Round-robin distribute per tier across ALL active strategies (D1),
  //           bounded by maxSymbolsPerBot (per strategy) and chaosMaxTotalSymbols (run-wide) ──
  const assignedMap = {}  // { strategyName: string[] }
  for (const strat of activeStrategies) {
    assignedMap[strat] = [...reservedMap[strat]]  // start with reserved picks
  }

  const dropped = []
  const n = activeStrategies.length
  let runningTotal = totalReserved  // manual picks already count against the total cap

  for (const tierBucket of [high, mid, low]) {
    let i = 0
    for (const sym of tierBucket) {
      if (runningTotal >= chaosMaxTotalSymbols) {
        dropped.push(sym)
        continue
      }

      // Find the next strategy (starting at the round-robin cursor) that still has room
      // under its per-bot cap. If all n strategies are full, the symbol is undistributable.
      let placed = false
      for (let tries = 0; tries < n; tries++) {
        const strat = activeStrategies[(i + tries) % n]
        if (assignedMap[strat].length < maxSymbolsPerBot) {
          assignedMap[strat].push(sym)
          runningTotal++
          placed = true
          i = i + tries + 1
          break
        }
      }
      if (!placed) {
        dropped.push(sym)
        i++
      }
    }
  }

  return {
    assignments: assignedMap,
    dropped, // pool symbols left unassigned once the per-bot and/or total-run caps were reached
    errors,
  }
}

module.exports = { allocateChaosSymbols }
