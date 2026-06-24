# 02 — Risk Management: Enma vs. freqtrade

> Checkpoint 2 on the pipeline spine. Position sizing, stops, drawdown circuit-breaker, exposure caps.
> **Upstream reference:** `freqtrade/wallets.py` (sizing), strategy `stoploss`/`trailing_stop`, protections.

---

## Uncomfortable truth first: Enma's sizing model is *ahead* of freqtrade's default

freqtrade sizes by **stake fraction**, not by risk-per-trade:
- `get_trade_stake_amount()` → `get_available_stake_amount()` = `min(total*tradable_balance_ratio - open_stakes, free)`.
- Unlimited mode: `(available + tied_up) / max_open_trades` — i.e. divide capital by slot count.
- It does **not** size from stop distance. Risk-per-trade is implicit (stop % × stake), not targeted.

Enma sizes by **risk budget**: `RiskBudgetPortfolio._size()` = `min(budget/risk_per_unit, max_notional/price) × conviction`
where `budget = equity × risk_pct` and `risk_per_unit = |entry − stop|` (`engine/core/models/portfolio.py`).
This is the textbook risk-targeting approach and is **more sophisticated** than freqtrade's stake split.
So this doc is not "copy freqtrade's sizing" — it's where freqtrade's *guardrails around* sizing are
tighter than Enma's. Don't regress Enma's model.

---

## Side-by-side

| Concern | freqtrade | Enma |
|---|---|---|
| Sizing basis | stake fraction (`get_trade_stake_amount`) | risk budget `equity*risk_pct / |entry-stop|` (`portfolio.py:_size`) |
| Below-minimum behaviour | `validate_stake_amount()` returns **0 → skip trade** (only bumps within +30%) | `clamp_and_round_qty()` **bumps qty UP to minNotional** (`symbols.py`) |
| Capital reserve | `tradable_balance_ratio` | per-symbol `allocate()` + `max_portfolio_risk` veto (6%) |
| Exposure cap | `max_open_trades` | `max_portfolio_risk` (new_risk_pct veto), `max_notional = equity*leverage` |
| Stop type | fixed `stoploss` % or `custom_stoploss`; `trailing_stop` | ATR bracket (`AtrBracketRiskModel`), trailing + breakeven, Chandelier variant |
| Drawdown breaker | `protections` (MaxDrawdown) module | `DefaultRiskModel.can_trade()` session DD vs `max_session_dd` |
| Param clamping | config schema | server 4-tier cascade `risk.js` + engine `PARAMS` clamp |

Enma's ATR stops, trailing+breakeven, Chandelier, and session-drawdown breaker are **at or above**
freqtrade parity. Findings below are the two places its guardrails are looser.

---

## Gaps & root causes

### The min-notional bump silently violates the risk budget — RC-1's risk-side twin
This is the most important risk finding and it connects to RC-1. When the risk-sized quantity is
below the exchange minimum, `clamp_and_round_qty()` **bumps the quantity UP to minNotional**. The
position then carries **more risk than `risk_pct` allows** — the core risk invariant (CLAUDE.md
rule #6) is silently broken on exactly the small-equity / high-minNotional symbols (JUPUSDT class).
freqtrade does the opposite: `validate_stake_amount()` returns **0 and skips the trade** when stake
is below minimum (it only bumps within a +30% tolerance). Enma has no such tolerance gate or skip —
it always bumps. → **F-013**

### Server hard-limits are not re-enforced in the engine
`server/src/utils/risk.js:resolveStrategyRiskParams()` applies a 4-tier cascade *and* global hard
limits (max risk/trade, max session DD, max leverage) before calling the engine. But the engine
(`backtest_runner.py` step 6a, live session config) clamps only to per-strategy `PARAMS` bounds and
**trusts** the incoming risk values. Any path that reaches the engine without going through `risk.js`
(internal call, future endpoint, a backtest invoked directly) bypasses the global caps. The hard
limit lives in only one of the two services that can set risk. → **F-014**

---

## Findings

| ID | Severity | One-line | Enma file(s) | Reference |
|----|----------|----------|--------------|-----------|
| F-013 | HIGH | Min-notional bump raises qty above the `risk_pct` budget → silently takes more risk than configured (breaks invariant #6) on small-equity/high-minNotional symbols | `engine/utils/symbols.py:clamp_and_round_qty`, `engine/core/live_bot_manager.py:_execute_entry` | freqtrade `validate_stake_amount` (returns 0 → skip below min, +30% cap) |
| F-014 | MEDIUM | Global risk hard-limits enforced only in `risk.js`; engine trusts incoming values, so non-`risk.js` paths bypass caps | `server/src/utils/risk.js:resolveStrategyRiskParams`, `engine/services/backtest_runner.py` (param injection ~L282-335) | freqtrade single config-validated path |

---

## What Enma could adopt

- Add a **skip-or-tolerance gate** to the min-notional bump: if reaching minNotional would push
  realized risk above `risk_pct` (beyond a small tolerance), **skip the trade** rather than silently
  over-risk — freqtrade's `validate_stake_amount` semantics. Resolves F-013 and closes RC-1's risk side.
- Re-assert the global hard-limit clamp **inside the engine** as a defensive floor, so risk caps hold
  regardless of which service set the params.
- Keep Enma's risk-budget sizing and ATR/Chandelier stops — they exceed freqtrade's defaults; do not
  replace them.
