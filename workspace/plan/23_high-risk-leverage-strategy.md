# 23 — New Strategy: High-Risk / High-Leverage Breakout Scalper ("MarginSurge")

**Status:** ✅ Done — **VALIDATION FAILED, NOT SHIPPED** (verdict reached 2026-07-21; see
"Validation outcome" section at the end of this file)
**Created:** 2026-07-16 · **Priority:** P2 (feature work; gated on live-correctness fixes below)
**Requested as:** "a new strategy, fixed to give high returns, high risk, entry conditions +
SL/TP levels, optimised for heavy margin use."

## The uncomfortable part (read first)

**"Fixed to give high returns" is not a thing that can be built, and this plan does not claim
it.** No entry rule fixes returns — leverage scales *both* tails. What CAN be engineered:
a strategy whose *expected* return is high **conditional on positive edge**, whose leverage is
chosen by measured ruin-probability rather than vibes, and whose risk is capped by hard,
parameterized controls. High risk here means: this design targets high return with **expected
drawdowns of 30–60% and a real chance of losing the allocated capital**. If backtest + Monte
Carlo show the edge doesn't survive fees at high leverage, the correct outcome of this plan is
**"don't ship it"** — that is a success of the process, not a failure. The plan below is
written to make that verdict cheap and honest.

**Prerequisites (hard):** live sessions for this strategy must wait for Plan 21 steps
21.1–21.4 (fill-path fixes, bracket cancel-on-close, SL amend-on-tighten — M-4 directly affects
this strategy's trailing stop) and ideally 22.1–22.2 (session governor + liq-buffer wiring,
since B-1 means `liq_buffer_pct` is decorative today and this design leans on it). Backtest
work can start immediately.

---

## 1 · Concept

`MarginSurge` — volatility-compression breakout scalper on 5m/15m, long+short, isolated margin,
high leverage (selected in §4, target range 20–50x), tight ATR stop, 2R take-profit with
breakeven move and ATR trail. Alpha family: momentum/breakout (the highest-variance,
highest-ceiling family that fits candle-driven execution and the existing indicator set — no
new indicators or dependencies required).

Five-model bindings (all existing components, no new model classes needed):
`AtrBracketRiskModel` (trail + breakeven + ATR-percentile filter — all already implemented,
default-off knobs turned ON here) · `RiskBudgetPortfolio` · `DefaultTransactionCostModel` ·
`LiveExecution`/`BacktestExecution`. Strategy is Alpha-only per the Narang contract:
`forecast()` + `prepare()`/`before()`, no account reads, no order writes.

## 2 · Entry conditions (Alpha spec)

All computed in `prepare()` (vectorized), indexed in `before()`, decided on candle close.

**Long entry — ALL of:**
1. **Breakout:** close > Donchian(`dc_period`=20) upper band of the *prior* candle (band
   shifted by 1 — no self-inclusion lookahead; validate with the 9.5 sentinel).
2. **Compression precondition:** Bollinger(20) bandwidth of the prior candle in the bottom
   `squeeze_pct`=30% of its rolling 200-candle history (breakouts from compression carry the
   edge; raw breakouts in already-expanded vol are chase entries).
3. **Momentum confirmation:** ADX(14) ≥ `adx_min`=25 **and** rising vs 3 candles ago.
4. **Flow confirmation:** MFI(14) ≥ 55 (long) — volume behind the break, not a wick.
5. **Trend alignment (same-TF, no Plan-13 dependency):** close > EMA(200). When Plan 13
   (`self.htf()`) ships, replace with 1h EMA(50) alignment — parameterized as `trend_filter`.
6. **Volatility floor:** `atr_percentile_min`=0.4 via the existing AtrBracket filter — vetoes
   entries when current ATR sits in the bottom 40% of session history (dead-market filter;
   tight stops in dead markets = fee bleed).

**Short entry:** exact mirror (Donchian lower break, MFI ≤ 45, close < EMA(200)).

**No-trade guards (session/protections layer, not Alpha):** CooldownPeriod 2 candles after any
exit; StoplossGuard halt after 4 stop-outs in 60 min (both already exist); governor checks once
22.1 ships.

## 3 · SL / TP levels (Risk spec)

- **Stop-loss:** `sl_atr_mult`=0.75 × ATR(14) from entry — deliberately tight; the design's
  risk unit. At 5m on majors this is roughly 0.2–0.6% of price.
- **Liquidation clearance (the heavy-margin invariant):** the stop MUST sit inside the
  liquidation price by ≥ `liq_buffer_pct`=0.5% of price: enforce
  `sl_distance_pct + liq_buffer_pct < 1/leverage − mmr_headroom`. At 50x, liquidation sits
  ≈1.6–1.9% away (isolated, tier-1 MMR) — a 0.75-ATR stop fits on majors, does NOT fit on
  high-ATR alts → **the check must veto or de-lever, not silently proceed.** Today this check
  is decorative (Plan 22 B-1); until 22.2 wires `respects_liq_buffer()`, the backtest harness
  for this strategy must assert it per-trade in the run report.
- **Take-profit:** `rrr`=2.0 → TP at 2R (2 × 0.75 ATR). With taker fees 0.05%×2 and slippage
  ~0.05%, breakeven win rate ≈ 36–40% at 2R depending on symbol (fee drag is the scalper
  killer — computed per-symbol in §5's cost-realism gate).
- **Breakeven move:** `breakeven_r`=1.0 — stop to entry at +1R (already implemented).
- **Trail:** `trail_atr_mult`=1.0 after breakeven — ride the runner. **Live caveat: M-4** —
  until 21.4 ships, the trail is engine-side only (exchange SL stays at the original level);
  acceptable on testnet, unacceptable for any real-money conversation.
- **Time stop:** exit at market after `max_hold_candles`=24 if neither SL nor TP hit
  (compression breakouts that go nowhere are dead trades paying funding).

## 4 · Heavy-margin optimization (how leverage is actually chosen)

Leverage is a **measured output, not an input**:
1. Backtest the strategy at leverage ∈ {10, 20, 35, 50} via the existing
   leverage-sensitivity runner (per-symbol clamping already applies).
2. Monte Carlo (block bootstrap, existing engine) each leverage tier → P(max drawdown > 50%)
   and P(ruin) curves.
3. **Selection rule:** highest leverage where P(dd>50%) < 10% and P(ruin) < 2% over 1,000
   trades. If no tier passes, the strategy ships at the highest passing tier or not at all.
4. Sizing: `risk_pct`=0.03–0.05 (3–5% per trade — aggressive; hard-capped at 0.20 by F-014).
   Note the interplay: with risk-based sizing, leverage mostly buys **margin efficiency**
   (smaller isolated margin per position → more concurrent positions per wallet), not bigger
   size — size is `(equity×risk_pct)/stop_distance`, capped by `max_qty(equity×leverage)`.
   "Optimised for heavy margin use" therefore concretely means: max concurrent positions
   (`maxOpenPositions` 4–6), high margin utilization (governor ceiling 0.8 once 22.1 ships),
   minimal idle capital — not YOLO notional.
5. Chaos-mode stress: one 10–15 symbol run at the selected tier to observe cross-symbol margin
   contention live on testnet before any standing session.

## 5 · Parameters (PARAMS schema, typed per F-015/F-016)

| Param | Type | Default | Range |
|---|---|---|---|
| `dc_period` | int | 20 | 10–55 |
| `squeeze_pct` | float | 0.30 | 0.1–0.6 |
| `adx_min` | int | 25 | 15–40 |
| `sl_atr_mult` | float | 0.75 | 0.5–2.0 |
| `rrr` | float | 2.0 | 1.0–4.0 |
| `breakeven_r` | float | 1.0 | 0–2.0 |
| `trail_atr_mult` | float | 1.0 | 0–3.0 |
| `atr_percentile_min` | float | 0.40 | 0–0.8 |
| `max_hold_candles` | int | 24 | 6–96 |
| `risk_pct` (risk params) | float | 0.03 | ≤0.05 wizard-capped |

## 6 · Validation gates (in order; each can kill the strategy — that's the point)

1. **Cost realism first:** per-symbol breakeven-win-rate table (fees+slippage at 0.75-ATR
   stops, 5m and 15m). Symbols where breakeven WR > 45% are excluded from the pairlist before
   any optimization.
2. **Backtest across regimes:** ≥ 3 windows (trend month, chop month, crash week — e.g. the
   windows already cached in TimescaleDB), 5m and 15m, per-symbol and small multi-symbol.
   Kill threshold: expectancy ≤ 0 after costs in 2 of 3 regimes.
3. **Lookahead sentinel (9.5)** green — mandatory (Donchian shift and BB-bandwidth history are
   the risky spots).
4. **Grid optimize** only `dc_period`, `sl_atr_mult`, `rrr` (3 params max — QNT-6 overfit
   warning stands; min 100 trades per combo). Manual OOS split until Plan 10 Phase 3
   walk-forward exists: optimize on window A, validate untouched on window B; accept only if
   B's expectancy ≥ 50% of A's.
5. **MC + leverage selection** per §4.
6. **Chaos stress run**, then a 1–3 symbol standing testnet session — only after 21.1–21.4.

## 7 · Deliverables & sequencing (implementation session, not this plan)

`engine/strategies/MarginSurge.py` + seeder registration + `workspace/docs/strategies/INDEX.md`
entry (check indicator INDEX for duplicates first, per AGENTS.md) + boundary-test inclusion +
validation-report doc in `workspace/docs/strategies/`. **Invoke `/add-strategy` at the start of
the implementation session (Rule F).** No golden-master impact (new strategy file, additive;
existing baselines untouched). Backtest phases (§6 gates 1–5) can start now; live phase gated
on Plan 21.

## 8 · Open questions

1. 5m or 15m as primary? Proposal: validate both, ship the one that passes gate 2; 1m is
   excluded (fee drag + the QNT-8/9 live-parity caveats bite hardest there).
2. Pairlist: fixed majors (BTC/ETH/SOL/BNB) vs dynamic VolumePairList top-10? Proposal: fixed
   majors for validation (clean data, tight spreads), dynamic later.
3. Does the user want the losing verdict respected? If gates 1–5 fail, this plan's
   recommendation is to not ship — confirm that's acceptable up front, because "high returns"
   cannot be rescued by raising leverage on a negative-expectancy edge (it only accelerates
   the loss).

**Resolved 2026-07-21** — user authorized proceeding autonomously ("use recommended paths, do not
stop") on the implementation/validation session, which is exactly a pre-authorization of this
section's own proposals: validate both 5m/15m and ship whichever passes (§8.1), fixed majors for
validation (§8.2), and respect a losing verdict (§8.3). See below.

---

## Validation outcome (2026-07-21) — DO NOT SHIP

Implemented `engine/strategies/MarginSurge/__init__.py` exactly per §2/§3/§5 above (Donchian
breakout from a BB squeeze, ADX/MFI/EMA(200) confirmation, ATR bracket via `AtrBracketRiskModel`,
`RiskBudgetPortfolio` sizing), registered in the seeder, added to `test_boundaries.py` and the
lookahead sentinel. Ran gates 1–4 of §6 autonomously (open questions above pre-resolved, so no
mid-session questions were needed):

- **Gate 1 (cost-realism)** — default params, leverage=20/risk_pct=3%, full year 2024, all 4 fixed
  majors × 5m/15m: every combo showed heavy net losses (-46% to -51% of capital). Only
  `SOLUSDT/15m` technically passed the breakeven-WR≤45% filter (payoff 1.42 → BE-WR 41%), but its
  *actual* win rate (29%) sat below that bar — an alpha problem, not (only) a cost problem.
- **Diagnostic re-run** at leverage=50/risk_pct=1% (isolates alpha quality from the margin-
  rejection noise gate 1's many `[Entry rejected]` lines showed): **negative expectancy on all 6
  combos re-tested** (-$18 to -$114/trade). Confirms the negative edge isn't a sizing artifact of
  gate 1's specific leverage/risk_pct choice.
- **Gate 3 (lookahead sentinel, 9.5)** — PASS. `scripts/lookahead_sentinel.py` shows zero
  divergence between full-array and expanding-window `prepare()` for MarginSurge.
- **Gate 4 (grid optimize + manual OOS split)** — 64 combos over `dc_period`/`sl_atr_mult`/`rrr`
  on the least-bad combo (SOLUSDT/15m), train H1 2024 / validate H2 2024: best in-sample result
  looked strong (Sharpe 1.76, +7.3%, expectancy +$33/trade) but **inverted sign out-of-sample**
  (22% win rate, -17.8%, expectancy -$44.56/trade) — this plan's own §6.4 acceptance rule ("B's
  expectancy ≥ 50% of A's") isn't marginally missed, it fails on a sign flip. Textbook in-sample
  overfitting (QNT-6's own warning, borne out exactly).
- **Gates 5–6 (Monte Carlo/leverage selection, chaos stress) — deliberately not run.** Gate 4's
  OOS failure is itself a kill per this plan's own §6 framing ("each can kill the strategy — that's
  the point"); spending further compute on Monte Carlo ruin-probability curves for an already-
  disproven parameter set would manufacture false confidence, not real signal.

**Verdict, per this plan's own pre-committed framing: don't ship.** The strategy is implemented
correctly (passes `test_boundaries.py`, passes the lookahead sentinel) and stays in the codebase as
a working, boundary-clean reference — but its specified alpha has no demonstrated edge on any
tested symbol/timeframe, and the one combo that looked good in-sample was a textbook overfit that
failed OOS by a wide margin, not a marginal miss. Seeded with its validation outcome stated
explicitly in the description (`services/strategy_seeder.py`) so it isn't mistaken for a normal,
ready-to-trade strategy. Full report: `workspace/docs/strategies/MarginSurge.md`. Decision recorded
in `DECISIONS.md` #29.

**Verified:** engine pytest 670/670 (24 boundary cases across 6 strategies, +6 new
`test_strategy_load_failure.py`-adjacent counts unaffected), golden-master byte-identical
(`MultiDivergence trades=55 netProfit=-1784.02 winRate=0.36 cagr=-71.32 sqn=-2.08` — additive-only
change, zero impact on the 5 existing seeded strategies), engine container restarted clean with all
6 strategies seeded.
