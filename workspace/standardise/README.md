# Standardise Study — Enma vs. Mature OSS Trading Engines

> **Status:** Map-only (Phase 1). No code changes in this phase. Fixes are a later, separately-approved phase.
> **Created:** 2026-06-24

## Why this study exists

Enma's live and backtest logic has accumulated suspected logical/process errors. The visible
symptoms are the JUPUSDT / MKRUSDT / `MARKET_LOT_SIZE` class of order-rejection bugs and
recurring bot↔exchange desync (several recent commits are reconciliation patches landing one
at a time). Rather than keep patching symptoms, this study reads **how mature open-source
projects solved the same problems** and turns the gaps into a ranked correction backlog.

The intent is **inspiration, not architecture transplant.** Enma stays a single-user,
three-service (engine / server / client) platform on Mongo / TimescaleDB / Redis. We are not
copying anyone's architecture — only how they handled the *features and failures we struggle with*.

## Reference repositories (decision)

| Repo | Role | Why |
|---|---|---|
| **`freqtrade/freqtrade`** | **Primary** | Closest domain & flow match: strategy→signal→sizing→SL/TP→backtest, with a web UI. |
| **`nautechsystems/nautilus_trader`** | Secondary | OCO / contingent-order & execution correctness only. |
| ~~`hummingbot/hummingbot`~~ | **Dropped** | Market-making / arbitrage domain — wrong flow for Enma. |

## Organising principle: pipeline-first

The spine is the end-to-end flow; the six problem areas are checkpoints hung off it:

```
signal → entry sizing → SL/TP placement → OCO mutual-cancel → reconciliation → real data on UI
```

User-named problem areas: (1) backtesting, (2) risk management, (3) parameter & portfolio
handling, (4) SL/TP order placement, (5) minimum-requirement boundaries, (6) a correct
end-to-end pipeline.

## Headline finding (confirmed from Enma's own code, before reading freqtrade)

The dominant systemic defect is **backtest↔live asymmetry**: precision / min-notional / risk
guards run on the **live** path and are **skipped** in **backtest**.

| Guard | Live (enforced) | Backtest (missing) |
|---|---|---|
| `clamp_and_round_qty()` (stepSize, minQty, minNotional bump) | `engine/core/live_bot_manager.py:523` | not called — `backtest_runner.py:563-564, 607-608` read `strategy.buy/sell` raw |
| `round_price()` (tickSize) for SL/TP | `live_bot_manager.py:526-527` | not called — `backtest_runner.py:689-725` use raw prices |
| Notional vs buying-power validation | `live_bot_manager.py:538-554` | not enforced |
| Server hard-limit clamp (`risk.js` 4-tier) | applied before live call | engine assumes pre-clamped params |

**Consequence:** backtests fill orders the exchange would reject (JUPUSDT $6 sized fill vs $50
min-notional live reject), so reported backtest performance is structurally optimistic and not
reproducible live. This single asymmetry ties areas 1, 5, and 6 to one root cause and is the
thread the study pulls on.

## How to read this study

Docs are **root-cause-forward**: each topic doc leads with the structural "why this is wrong"
and ties individual findings back to shared root causes (the asymmetry above is the first).

```
00-pipeline-overview.md       the spine: Enma flow vs freqtrade freqtradebot.py main loop
01-backtesting.md             fill model, fees, slippage, SL/TP-in-backtest, candle handling
02-risk-management.md          sizing, stops, drawdown circuit-breaker, exposure caps
03-params-portfolio.md         param schema/validation, equity/portfolio accounting, multi-symbol
04-sltp-oco.md                 SL/TP placement + OCO mutual-cancel + unprotected-position window
05-boundaries.md               exchange filters: minNotional/LOT_SIZE/tick/step, precision rounding
06-reconciliation-uistate.md   bot↔exchange desync + how true state reaches the UI
07-additive-features.md        NEW capabilities to borrow (protections, pairlists, metrics, DCA)
findings-index.md              ALL findings (F-xxx), flat & severity-ranked, independently shippable
CLAUDE.md                      implementation playbook (how to execute) — read by ANY agent
tracker.md                     live status board for all 38 items, phased step-by-step
```

> **To implement:** read `CLAUDE.md` first, then work `tracker.md` top-to-bottom, one item at a time.

> `00`–`06` + `findings-index.md` cover **corrections** (`F-xxx` — what is wrong). `07` covers
> **additions** (`A-xxx` — what is missing); it is a capability wishlist, not a defect list.

Each `0X-*.md` topic doc uses one template per finding:
- **Enma today** — exact `file:function` + behaviour.
- **freqtrade (primary)** — equivalent module/function + upstream path; how they handle it.
- **nautilus** — only where relevant (OCO/execution).
- **Gap** — the concrete divergence and why it's wrong for Enma.
- **Finding(s)** — tagged severity, self-contained, naming the file(s) a future fix touches.

## Severity legend

| Tag | Meaning |
|---|---|
| `[CRITICAL]` | Produces wrong money/state or makes backtest non-reproducible live. Fix first. |
| `[HIGH]` | Real correctness/risk gap; not immediately money-losing but unsafe. |
| `[MEDIUM]` | Inconsistency, missing validation, or duplication that will cause future bugs. |
| `[LOW]` | Cleanup, dead code, documentation drift. |

## Method for reading the reference repos

Planning/study task → docs only, no code stubs. Reference source is read read-only via:
1. `mcp__github__get_file_contents` / `search_code` against the two repos (no local clone).
2. `WebFetch` on raw GitHub file URLs for specific modules.
3. Shallow clone into a scratch dir **outside** the repo only if a deep local read is needed.

Every upstream claim must cite a real upstream path — no assertions from memory.

## Out of scope (this phase)

- Any code fix or stub (deferred to a later approved phase).
- hummingbot analysis.
- Architecture changes — the single-user, 3-service, Mongo/Timescale/Redis design stays.
