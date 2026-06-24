# Chaos Mode — Configurable Launch Wizard (Upgrade Plan)

**Status:** COMPLETED — Fully implemented and verified in the codebase as of 2026-06-22.
**Date:** 2026-06-22
**Author:** AI session
**Open questions:** all resolved (see *Resolved Decisions*).

> Scope per Rule D: this is a planning doc. No code, stubs, or scaffolds are written as part of it.

---

## Goal

Turn Chaos Mode from a **fire-and-forget, hardcoded** launch (`POST /api/v1/algo/chaos` with no body → all 5 strategies, random 70-symbol split, fixed params) into a **guided wizard** — same UX pattern as the "New Bot" `NewSessionWizard`:

1. Click **Chaos Mode** → a multi-step panel opens (mirrors the New-Bot wizard toggle).
2. **Select strategies** — one, several, or none.
3. Per selected strategy, choose **symbols** with a per-strategy **`auto` / `manual`** toggle (`auto` default).
4. **Next →** set shared **risk parameters** (leverage, R:R, capital-per-strategy, max drawdown, + recommended).
5. **Activate Chaos Mode** → every resolved strategy deploys with the chosen settings.

---

## Resolved Decisions (from user, 2026-06-22)

| # | Decision | Effect on design |
|---|----------|------------------|
| **D1 — Leftovers always distributed** | Leftover symbols are split **equally across *all* active strategies**, manual or auto. Goal: stress every strategy to the extreme with the maximum symbol count. | A "manual" strategy keeps its hand-picked symbols **and still receives an equal share** of the leftover pool. The `auto/manual` toggle only controls whether a strategy has *reserved* picks — every strategy gets leftover distribution. |
| **D2 — Strategy selection & caps** | • Chaos runs **at most `maxStrategies` (default 10)** strategies. • If the user selects **0** strategies → **auto-select** up to the cap using the **most recent** strategies. • If the user selects **1…N (< cap)** → run **only those** — no auto top-up. • Manual symbols per strategy capped at **`maxManualSymbols` (default 5)**; the rest is auto-distributed. • **No symbol may belong to two strategies** (manual or auto) — every symbol is assigned to exactly one. | Replaces the old "empty ⇒ all 5" rule with "empty ⇒ recent up to cap". Since 5 strategies exist today, empty still ⇒ all 5. Caps come from settings (see Chaos Settings). |
| **D3 — Static, volume-tiered symbol list** | Curate a **fixed list of ≥70–80 symbols** once (research task), bucketed into **3 tiers by trading volume**, excluding low-volume names. No live Binance fetch. | `top_symbols.js` gains tier tags. Research deliverable in Phase 1. Honors Binance-isolation (no `server/` Binance call). |
| **D4 — 3 buckets** | Three volume tiers (high / mid / low-but-acceptable) are enough. | Bucket count is fixed at 3. |
| **D5 — Caps are settings** | All hard limits live in a new **"Chaos Setting (testnet)"** section on the Settings page, editable as variables. | New settings fields + UI section (see Chaos Settings). |

---

## What exists today (verified in code)

| Piece | Location | Behaviour |
|-------|----------|-----------|
| `startChaos()` | `server/src/controllers/algo.controller.js:530` | No body. Fisher–Yates shuffles `TOP_SYMBOLS`, deals ~14/strategy, launches all 5 via the per-strategy loop. |
| `CHAOS_LAUNCH_LIST` / consts | same file, `:438,:442` | Hardcoded high-volatility params; `CHAOS_LEVERAGE=50`, `CHAOS_CAPITAL='500'`, `CHAOS_TF='1m'`. |
| `TOP_SYMBOLS` | `server/src/constants/top_symbols.js` | Flat array of 70 symbols, **no tier metadata**. |
| `POST /api/v1/algo/chaos` | `server/src/routes/algo.routes.js` | Thin route, no body. |
| `useStartChaos()` | `client/src/hooks/useAlgoSessions.js:74` | Posts with **no payload**. |
| Chaos button + inline confirm | `client/src/pages/AlgoTrading.jsx:82-125` | Gradient button + amber confirm + error banner. |
| `NewSessionWizard` | `client/src/components/algo/NewSessionWizard.jsx` | The wizard pattern we mirror (step indicator, `SymbolPicker`, `RiskParamsFields`, review, settings-prefill via `useRef`). |
| `SymbolPicker` | `client/src/components/algo/SymbolPicker.jsx` | Lock-aware grid multi-select — reusable per-strategy. |
| `RiskParamsFields` + `riskFieldsToPayload` | `client/src/components/RiskParamsFields.jsx` | Risk inputs + payload mapper. |
| `resolveModelParams()` | `server/src/utils/risk.js` | Merges per-run risk override over saved global defaults → engine snake_case dict. |
| Settings (model/controller/UI) | `server/src/models/Settings.js`, `server/src/controllers/settings.controller.js`, `client/src/pages/Settings.jsx` | Single `global` doc; flat numeric fields validated by `EXCHANGE_FIELDS` + `FIELD_RULES`; `fundingEnabled` is the boolean special-case. |

**Key finding:** the engine's `/algo/sessions` endpoint already accepts everything needed (`strategy_name, symbols, timeframe, params, capital, leverage, fee_rate, risk_params`). **No engine changes** — this is a `server/` + `client/` upgrade only.

---

## Allocation Semantics (core of the upgrade)

Implement once as a **pure, unit-testable helper** `allocateChaosSymbols({ activeStrategies, manualPicks, lockedSymbols, buckets, maxManualSymbols })`. Controller stays thin.

### Resolve active strategies (D2)
```
if user selected ≥1 strategy:
    active = selected            // run only these, no auto top-up
else:
    active = recentStrategies()  // most-recent-first
active = active.slice(0, maxStrategies)   // hard cap (default 10)
```
*"Recent"* = sort the `strategies` collection by `updatedAt` (fallback `createdAt`) desc. (Only 5 exist today ⇒ all 5.)

### Allocate symbols (D1 + uniqueness)
```
1. RESERVE manual picks:
   - each strategy's manual symbols ≤ maxManualSymbols (else 400)
   - every manual symbol must be: in the curated list, currently free,
     and claimed by NO other strategy (no cross-strategy sharing) (else 400)
2. POOL = curatedSymbols − (all reserved) − (locked by other live sessions)
3. BUCKET POOL into 3 volume tiers: { high, mid, low }
4. DISTRIBUTE EQUALLY across ALL active strategies (manual + auto):
   for tier in [high, mid, low]:
       shuffle(tier)                         // fairness within a tier
       deal one symbol at a time, round-robin, to each active strategy
   → each strategy gets a near-equal slice of EACH tier (D1 + D4)
5. RESULT: strategy.symbols = reserved ⊕ distributed   (each symbol used once)
```

**Why round-robin per tier:** guarantees no strategy hogs the high-volume names — every strategy receives a comparable high/mid/low mix.

**Count note (D1):** leftovers are split *equally*; a manual strategy therefore ends with `reserved + equalShare` (slightly more total than a pure-auto strategy). This is intentional — manual = "guarantee these *plus* a full share."

### Edge resolutions (now bounded by caps)
- **0 selected** → recent strategies up to `maxStrategies`, full pool stratified.
- **More strategies than symbols** → cannot occur under the caps (`maxStrategies` × needs ≤ curated list size). The allocator still degrades gracefully (a strategy may get 0 leftover symbols) and the review step warns, but D2 makes this practically impossible.
- **Manual symbol locked by another session** → 409 (reuse existing lock check, `algo.controller.js:571-585`).
- **Duplicate manual claim across strategies / >`maxManualSymbols`** → 400 before any session is created.

### Market-cap / volume bucketing (D3 + D4)
- Convert `top_symbols.js` to tagged entries: `{ symbol, tier: 'high' | 'mid' | 'low' }`, **≥70–80 symbols**, curated by **trading volume** (Phase-1 research task; exclude low-volume/illiquid names).
- Keep exporting a flat `TOP_SYMBOLS` (derived) so existing imports don't break; add `bucketSymbols(symbols)` → `{ high, mid, low }`.

---

## Chaos Settings (testnet) — new Settings section (D5)

Add chaos limits + launch defaults to the single `global` Settings doc, editable from a new **"Chaos Setting (testnet)"** section on the Settings page.

| Field | Type | Default | Range / notes |
|-------|------|---------|---------------|
| `chaosMaxStrategies` | int | 10 | 1–20. Hard cap on strategies per chaos run. |
| `chaosMaxManualSymbols` | int | 5 | 0–20. Max hand-picked symbols per strategy. |
| `chaosDefaultCapital` | number | 500 | ≥1. Pre-fills wizard capital-per-strategy. |
| `chaosDefaultLeverage` | int | 50 | 1–125. Pre-fills wizard leverage. |
| `chaosDefaultTimeframe` | string | '1m' | must ∈ engine `SUPPORTED_TIMEFRAMES`. **String** → needs the same special-case handling as `fundingEnabled` (not in the numeric `FIELD_RULES` loop). |

**Files:**
- `server/src/models/Settings.js` — add the 5 fields with schema-level `min`/`max`/`enum`.
- `server/src/controllers/settings.controller.js` — add numeric fields to `EXCHANGE_FIELDS` + `FIELD_RULES`; add integer checks for the two int caps; handle `chaosDefaultTimeframe` as a string-allowlist special-case (mirroring the `fundingEnabled` branch).
- `client/src/pages/Settings.jsx` — new **"Chaos Setting (testnet)"** card/section with these inputs.
- `client/src/hooks/useExchangeSettings.js` — picks up the new fields automatically (flat passthrough); verify no hardcoded field list blocks them.

> The wizard reads these via `useExchangeSettings()` to (a) pre-fill capital/leverage/timeframe and (b) enforce `chaosMaxStrategies` / `chaosMaxManualSymbols` in the UI. The server **re-enforces** both caps server-side (never trust the client).

---

## Data Contract — `POST /api/v1/algo/chaos`

Optional JSON body (backwards-compatible — empty body reproduces today's launch, now cap-balanced):

```jsonc
{
  "timeframe": "1m",                        // optional; default = chaosDefaultTimeframe; validated vs SUPPORTED_TIMEFRAMES
  "strategies": [                           // optional; [] or omitted ⇒ recent strategies up to chaosMaxStrategies (D2)
    { "name": "MicroScalper",  "symbols": ["BTCUSDT","ETHUSDT"] },  // manual picks (≤ chaosMaxManualSymbols)
    { "name": "AdaptiveTrend" }                                      // auto (no reserved picks)
  ],
  "risk": {                                 // optional; falls back to chaos defaults + global settings
    "capital":  "500",                      // per strategy, common to all (D5 default)
    "leverage": 50,                         // requested; engine clamps per-symbol
    "riskReward": 1.5,                      // R:R ratio
    "maxDrawdown": 25,                      // % session drawdown breaker, common to all
    "riskPct": 1,                           // % equity risked per trade (recommended)
    "minEdgeMult": 1                        // cost-edge gate (recommended)
  }
}
```

**Server-side validation:** strategy names ∈ known set; ≤ `chaosMaxStrategies` entries; each `symbols` ≤ `chaosMaxManualSymbols`, all ∈ curated list, free, no cross-strategy duplicates; timeframe ∈ allowlist. Reject with 400/409 before creating any session.

**Response** keeps `{ launched, errors, note }` (207/502), plus `dropped: []` (should be empty under D1 since leftovers always distribute, but kept for transparency).

### Risk field mapping (reuse existing infra)
- `riskReward, maxDrawdown, riskPct, minEdgeMult` → `resolveModelParams(savedSettings, riskOverride)`.
- `capital, leverage` → onto each `LiveSession` + engine call (same as `startSession`).
- Per-strategy `params` stay sourced from `CHAOS_LAUNCH_LIST` presets (out of scope to expose).

---

## Backend changes (`server/`)

| File | Change |
|------|--------|
| `server/src/constants/top_symbols.js` | Tier-tag entries (≥70–80, volume-bucketed, D3); export flat `TOP_SYMBOLS` (derived) + `bucketSymbols()`. |
| `server/src/utils/chaosAllocator.js` *(new)* | Pure `allocateChaosSymbols(...)` — reserve + stratified round-robin + uniqueness (D1/D4). No DB/I/O → unit-testable. |
| `server/src/models/Settings.js` | + 5 chaos fields (D5). |
| `server/src/controllers/settings.controller.js` | Expose/validate the 5 chaos fields (string special-case for timeframe). |
| `server/src/controllers/algo.controller.js` | Rework `startChaos()`: parse+validate body → load chaos settings → resolve active strategies (recent-up-to-cap or selected) → read locks → `allocateChaosSymbols()` → feed each strategy's resolved symbol set into the **existing** per-strategy launch loop (lock→create→engine→rollback, lines 569-648). `capital/leverage/tf/risk` from body with settings/consts as defaults. |
| `server/src/routes/algo.routes.js` | `POST /chaos` now accepts a body; inline validation per convention. |

**Invariants preserved:** sessions stay `mode:'paper'`; locking via `symbolLock.js`; rollback paths unchanged; engine is sole writer of trade data.

---

## Frontend changes (`client/`)

| File | Change |
|------|--------|
| `client/src/components/algo/ChaosWizard.jsx` *(new)* | Wizard modeled on `NewSessionWizard`, rendered in the existing `Dialog`/`DialogContent`. Steps below. |
| `client/src/pages/AlgoTrading.jsx` | Replace inline `showChaosConfirm` panel (lines 102-125) with a `showChaosWizard` Dialog rendering `<ChaosWizard>` (same toggle UX as `showWizard`→`NewSessionWizard`). Keep gradient button + error banner. |
| `client/src/hooks/useAlgoSessions.js` | `useStartChaos()` `mutationFn` takes a `config` arg and posts it as the body (currently posts nothing, line 78). |
| `client/src/pages/Settings.jsx` | "Chaos Setting (testnet)" section (D5). |
| reuse | `SymbolPicker`, `RiskParamsFields`+`riskFieldsToPayload`, `useStrategies`, `useSymbols`, `useLockedSymbols`, `useExchangeSettings` (prefill + caps). |

### ChaosWizard steps
1. **Strategies** — multi-select list. Helper: *"Select none to auto-run the most recent up to N."* Enforce `chaosMaxStrategies` (disable beyond cap).
2. **Symbols per strategy** — one collapsible row per resolved strategy, each with an **Auto / Manual** toggle (default Auto). Manual reveals a scoped `SymbolPicker` capped at `chaosMaxManualSymbols`; a symbol picked for one strategy is disabled in the others (uniqueness). Live **Allocation preview** shows projected per-strategy counts + tier mix (mirrors the allocator) so D1/D4 are visible before launch.
3. **Risk parameters** — Capital per strategy, Leverage (1–125), `RiskParamsFields` (R:R, max DD, risk %, edge mult), Timeframe dropdown (allowlist). Pre-filled from Chaos Settings.
4. **Review & Activate** — summary (strategies, per-strategy counts + tier badges, capital, leverage, risk, timeframe) → **Activate Chaos Mode**. Testnet badge stays.

Styling: emerald-400 profit / red-400 loss, midnight-blue palette per `UI_STYLE_GUIDE.md`. Errors via inline banner (no `alert()`).

---

## Recommended build order

```
Phase 1 — Symbol research + tiers (top_symbols.js) + allocator (chaosAllocator.js, pure + tested)
Phase 2 — Chaos Settings (model + controller + Settings.jsx section)
Phase 3 — startChaos rework + body validation (server)
Phase 4 — useStartChaos payload + ChaosWizard + AlgoTrading wiring (client)
Phase 5 — Allocation preview panel + review polish (client, optional)
```

Phases 1-4 are the functional MVP (no engine work, no `LiveSession` schema change). Phase 5 is UX polish.
Phase 1's allocator is the highest-leverage piece — build and unit-test it first (pure function, deterministic given a seed).

---

## Constraints & invariants

- `mode:'paper'` stays the canonical chaos/testnet marker — no `isChaos` flag.
- Testnet only — no mainnet path.
- **Binance isolation:** no Binance calls from `server/` → static volume tiers, not live fetch (D3).
- Symbol locks via existing `symbolLock.js`; rollback paths unchanged.
- Caps enforced **both** client (UX) and server (authority) — never trust the client.
- P&L colours `emerald-400` / `red-400`; midnight-blue palette per `UI_STYLE_GUIDE.md`.
- No new npm/pip packages.
- Engine is sole writer of `tradeRecords` / session trade data.
- After implementation: run **`/sync-spec`** (updates `API_CONTRACTS.md` + `CURRENT_STATE.md`) and spawn `drift-reviewer` per the completion gate.

---

## Phase-1 research deliverable (D3)

Build the curated, volume-tiered symbol list (≥70–80 USDⓈ-M perpetuals, 3 tiers, low-volume excluded). This is a one-time curation — record the source/date in a comment in `top_symbols.js`. *(Can be done with web research at implementation time; not part of this planning doc.)*

---

## Companion follow-ups (deferred — more valuable once launches scale)

- **Stop-All-Chaos** button + "⚡ Chaos Active" header indicator (`sessions.some(s => s.mode==='paper' && s.status==='running')`).
- **Chaos monitor panel** — aggregate P&L / symbol count from the existing `sessions` cache (no new endpoints).
- **Chaos run history** (`ChaosRun` model) + **auto-stop** (duration / P&L floor via BullMQ) — separate session.
