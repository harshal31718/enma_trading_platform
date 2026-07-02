# Enma — Future Paths (Exploration Backlog)

**Status:** Exploration only. **Nothing here is committed or scheduled.** This is a registry of
directions we *could* take Enma next, so the decision is easy when we make it.

**Source:** Originally captured in a root-level `futurePlans.md` scratch file, ingested + organized
here on 2026-06-24; that scratch file was then deleted (fully superseded by this doc).

**Relationship to other docs:**
- `workspace/docs/state/CURRENT_STATE.md` → what Enma *is* today (source of truth).
- `CURRENT_STATE.md` "Planned / Not Yet Implemented" → committed-but-unbuilt (Mainnet, Monte Carlo,
  multi-exchange). Those are **cross-referenced** below under "Already on the official roadmap."
- This file → **exploratory ideas**, not yet promoted to the official roadmap.

---

## How to read this

Each entry is tagged so we can triage fast:

- **Fit** — how well it sits on Enma's current architecture (single-user, crypto, Binance futures, Python engine):
  - 🟢 **Strong** — extends what exists; lands inside `engine/`/`server/`/`client/` cleanly.
  - 🟡 **Partial** — fits, but needs a new subsystem (new data source, new page, new pipeline stage).
  - 🔴 **Detour** — different asset class or paradigm; effectively a second product or a big architectural fork.
- **Effort** — rough order of magnitude: **S** (days) · **M** (1–2 wks) · **L** (weeks) · **XL** (month+ / new domain).
- **Type** — **Adopt** (integrate an external lib/framework) · **Build** (in-house) · **Research** (read/prototype first).

> These are first-pass gut estimates for triage, not engineering commitments.

---

## Strategic forks (decide these before picking items)

Several ideas only make sense after we pick a side on a higher-level question. Tracking the forks
explicitly so individual items don't get evaluated in a vacuum:

> **Resolved (2026-06-24) — Build vs. adopt a backtest/exec framework:** keep extending Enma's
> bespoke five-model engine. VectorBT/Nautilus dropped from the backlog — a vectorized/parallel
> engine breaks the backtest=live `pipeline.evaluate()` invariant and isn't ground truth for
> validating our sim. Re-open only if we outgrow the in-house engine.

1. **Crypto-only vs. add equities.** A whole cluster (Stock Screener, Insider/Form-4 tracker, FinBERT,
   much of News Sentiment) assumes a *stock* data domain Enma doesn't have today. Adding equities means
   a new market-data source, new symbols model, and arguably a separate route — a second product surface.
   Decide once; it gates ~5 items.
2. **Classical quant vs. ML/RL.** GARCH/regime-detection/PyPortfolioOpt are classical and explainable.
   portfolio_grpo / TensorTrade are RL — high ceiling, heavy infra, harder to trust with real (testnet) capital.
3. **Single-symbol strategies vs. portfolio-level allocation.** Today each bot/backtest is symbol-centric.
   PyPortfolioOpt, Smart Portfolio Optimizer, and portfolio_grpo all assume a *portfolio* abstraction
   (weights across assets) we'd need to introduce first.

---

## Already on the official roadmap (cross-reference)

These were in `futurePlans.md` *and* already tracked in `CURRENT_STATE.md` → Planned. Listed so we don't
double-count:

| Idea (futurePlans) | Official roadmap entry |
|---|---|
| ~~Monte Carlo Simulation~~ | **Shipped** — `engine/services/monte_carlo.py`, wired into the Risk Dashboard. Stale as of the 2026-06-25 reconciliation (`00-current-state-reconciliation.md`); row kept for history only. |
| (multi-symbol / multi-exchange ambitions) | "Multi-exchange support" (Planned) |
| (live mainnet, implied by several) | "Mainnet trading" (Planned) |

---

## Track A — Backtesting, Optimization & Portfolio Engines

| Item | Fit | Effort | Type | Notes / Enma mapping |
|---|---|---|---|---|
| **PyPortfolioOpt** | 🟡 | M | Adopt | Mean-Variance / Black-Litterman / risk-parity weight allocation across symbols. Needs a portfolio abstraction first (fork #3). Natural complement to Chaos Mode's multi-symbol fan-out — could decide capital weights instead of round-robin. |
| ~~**Monte Carlo Simulation**~~ | 🟢 | M | **Shipped, not "Build"** | Stale — `engine/services/monte_carlo.py` is live and wired into the Risk Dashboard per `00-current-state-reconciliation.md` (2026-06-25). This doc predates that reconciliation and was never updated after. Do not schedule this as new work. |
| **Smart Portfolio Optimizer** | 🟡 | L | Build | Dynamic rebalancing on live signals + risk constraints (beyond static PyPortfolioOpt weights). Depends on portfolio abstraction (#3) and a live risk layer. Pairs with the Risk Management Dashboard (Track D). |

## Track B — ML / RL & Forecasting

| Item | Fit | Effort | Type | Notes / Enma mapping |
|---|---|---|---|---|
| **Volatility Forecasting (GARCH/EGARCH/ML)** | 🟢 | M | Research→Build | Predict forward vol → feeds position sizing & risk model (we already have ATR-based sizing). Classical, explainable, self-contained in `engine/`. Could surface as a new indicator/risk input. Strong fit, low blast radius. |
| **Market Regime Detection (HMM/clustering/vol filters)** | 🟢 | M–L | Research→Build | Classify trending/ranging/hi-lo-vol/bull-bear → switch strategy behavior. Fits the Alpha/Risk model boundary; AdaptiveTrend already gestures at "regime-aware." Could become a shared engine service strategies consume. |
| **portfolio_grpo (RL, GRPO)** | 🔴 | XL | Research | RL portfolio mgmt, 16 parallel sims, no critic; claims +639% OOS 2020–2024. Impressive but: RL infra, portfolio abstraction (#3), and trust/validation burden. Reference repo: github.com/Priyanshu-5257/portfolio_grpo. Deep-dive/prototype before any commitment. Fork #2. |
| **TensorTrade** | 🔴 | L | Research | RL trading via simulated-market trial-and-error. **Project largely inactive** — marked exploration-only by user. Read for ideas, don't depend on it. |

## Track C — Signals & Alternative Data

| Item | Fit | Effort | Type | Notes / Enma mapping |
|---|---|---|---|---|
| **News Sentiment Analyzer** | 🟡 | M–L | Build | Headline/article sentiment (bullish/bearish) as confluence signal. Needs a news data source + ingestion; partly crypto-applicable (crypto news), partly equities. New engine service + signal input. Pairs with FinBERT. |
| **FinBERT** | 🟡 | M | Adopt/Research | BERT fine-tuned on financial text — the model that powers the sentiment analyzer above. "Deep dive later" per user. Adds an ML model dependency (note in CLAUDE.md if pursued). |
| **Insider Trading Tracker (SEC Form 4)** | 🔴 | L | Build | Track insider buy/sell filings as leading signal. **Equities-only** (no crypto equivalent) → gated by fork #1. Separate data pipeline (SEC EDGAR). |
| **HFT Tracker — Catch & Follow** | 🟡 | L–XL | Research→Build | Detect HFT via order-flow / volume spikes / bid-ask dynamics on L2 data; piggyback or avoid. Enma already ingests Binance depth20 + trades streams (Trade page) — raw material exists, but tape-reading logic is hard and noisy. Research first. |

## Track D — Risk & Research Infrastructure

| Item | Fit | Effort | Type | Notes / Enma mapping |
|---|---|---|---|---|
| ~~**Risk Management Dashboard**~~ | 🟢 | M | **Shipped, not "Build"** | Stale — `engine/routers/risk.py` + `client/src/pages/RiskDashboard.jsx` (Zones 1–3: margin/exposure/correlation, live metrics, Monte Carlo & leverage-scenario simulation) are live per `00-current-state-reconciliation.md` (2026-06-25). Do not schedule this as new work. |
| **Personal Quant Research Framework** | 🟢 | L | Build | Structured loop: hypothesis → data → backtest → documented result → iterate. This is arguably the *meta-spine* tying everything together — and Enma's `workspace/docs` + strategy/backtest stack is already a partial implementation. Could formalize as a research-notebook/journal surface. |
| **Hedge Fund in a Spreadsheet** | 🟢 | S | Research | Replicate allocation/risk/P&L/Monte Carlo in spreadsheet formulas to *understand the math* before coding it. Not a product feature — a learning exercise that de-risks Track A/D builds. Cheap, useful precursor to Monte Carlo + Risk Dashboard. |

## Track E — Asset-Class Expansion

| Item | Fit | Effort | Type | Notes / Enma mapping |
|---|---|---|---|---|
| **Stock Screener (from scratch, separate route)** | 🔴 | L–XL | Build | Filter stocks on technical/fundamental criteria. User already flags it as a **distinct module / separate route** — correctly, since stocks ≠ crypto data sources & rules. This is the anchor of fork #1 (the whole equities cluster: + Insider tracker, FinBERT, parts of News Sentiment). Decide the equities question once, holistically. |

## Track F — Reference / Inspiration (not features to build)

| Item | Why it's here |
|---|---|
| **QuantDinger** | Self-hosted local-first quant infra covering the full loop (Idea→Indicator→Strategy→Backtest→Optimize→Execute→Monitor), multi-asset, multi-exchange, **MCP-enabled for AI agents**. Closest spiritual sibling to Enma's ambitions — study its scope/UX as a north-star, especially the MCP-agent angle. github.com/brokermr810/QuantDinger |
| **WiseQuant** | Backtesting-related platform; link/version unclear. **Revisit when found** — placeholder so it's not lost. |
| **Three Layer Setup** | Tauric Research (GitHub) · Paperclip · Open Data Platform — a layered architecture pattern to deep-dive later. |

---

## Quick triage view (highest-fit "could-do-next" shortlist)

If we wanted near-term wins that ride existing architecture (no fork required):

1. ~~**Monte Carlo Simulation** (Track A)~~ — **shipped**, see note above; no longer a candidate.
2. ~~**Risk Management Dashboard** (Track D)~~ — **shipped**, see note above; no longer a candidate.
3. **Volatility Forecasting** (Track B) — self-contained engine addition feeding the existing risk model.
4. **Market Regime Detection** (Track B) — fits the Alpha/Risk boundary; AdaptiveTrend already leans this way.
5. **Hedge Fund in a Spreadsheet** (Track D) — zero-code precursor that de-risks #1 and #2.

Everything in Tracks C/E and the RL items in B should wait on the **strategic forks** above.

---

## Open questions (for when we decide)

1. **Equities: in or out?** Resolves fork #1 and ~5 items at once.
2. **Is there appetite for ML/RL,** or stay classical/explainable for now? Resolves fork #2.
3. **Do we introduce a portfolio (multi-asset weight) abstraction?** Unblocks PyPortfolioOpt, Smart
   Optimizer, portfolio_grpo.
4. **MCP-agent angle (à la QuantDinger):** do we want AI agents to run backtests/trades autonomously
   through Enma? (We already have rich `.claude/` infra — this could be a differentiator.)
