# Next Steps — Feature Gap Analysis vs freqtrade & nautilus_trader

**Created:** 2026-06-25  
**Purpose:** Map features from [freqtrade](https://github.com/freqtrade/freqtrade) and [nautilus_trader](https://github.com/nautechsystems/nautilus_trader) onto Enma's current state, identify gaps, and propose a sequenced implementation plan.

> [!NOTE]
> **This is the gap matrix (reference). The actionable, sequenced subset is now specified in
> [`workspace/next_phase/`](../next_phase/README.md) as S1–S8** (max position per asset, informative
> multi-TF, webhooks, data CLI, lookahead/recursive/walk-forward analysis, Bayesian hyperopt).
> Implementing agents build from `next_phase/`, not from this matrix. This doc stays as the
> full landscape (incl. deferred multi-venue/ML items).

> **Read this with:** `workspace/docs/state/CURRENT_STATE.md`, `workspace/plan/INDEX.md`, `workspace/plan/future_paths.md`

---

## How to Read

Each row evaluates whether Enma has the feature. Three states:

- ✅ **Implemented** — feature exists and is production-grade
- 🟡 **Partial** — feature exists but is incomplete or less mature
- ❌ **Missing** — not implemented; candidate for future work

---

## 1. Feature Comparison Matrix

### 1.1 Architecture & Core

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| Event-driven engine | ✅ Python | ✅ Rust-native | ✅ Python (ExecutionKernel) | — |
| Three-DB separation | ❌ SQLite | ✅ Yes | ✅ Mongo+Timescale+Redis | — |
| Five-model quant pipeline | ❌ Custom | ✅ Yes | ✅ Narang pipeline | — |
| Deterministic time model | 🟡 Partial | ✅ Nanosecond | ✅ Candle-level | Enma lacks nanosecond tick precision |
| Containerized | ✅ Docker | ✅ Docker | ✅ Docker | — |
| Rust core for perf | ❌ Python | ✅ Rust+PyO3 | ❌ Python | Nautilus uses Rust for hot path; Enma is all Python |

### 1.2 Market Data & Candles

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| OHLCV storage | ✅ SQLite | ✅ Parquet catalog | ✅ TimescaleDB hypertable | — |
| Candle auto-fetch | ✅ download-data | ✅ Catalog | ✅ `ensure_candles_available()` | — |
| Tick-level data | ❌ Candle-only | ✅ Quote ticks, trade ticks | ❌ Candle-only | Enma has no tick data model or storage |
| Order book data | ❌ | ✅ L2/L3 book | ❌ Not in backtest | Trade page shows live depth20 but not in simulation |
| Custom data types | ❌ | ✅ Arrow-encoded | ❌ | Nautilus supports arbitrary data type registration |
| Multiple data providers | ❌ | ✅ Databento, Tardis, CSV | ❌ Binance only | Enma only fetches from Binance |
| Data catalog / versioned datasets | ❌ | ✅ ParquetDataCatalog | ❌ | No local data catalog; re-fetches from Binance |
| Tick-level backtesting | ❌ | ✅ | ❌ | Candle-level only |

### 1.3 Backtesting

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| Candle replay | ✅ | ✅ Bar aggregation | ✅ Sequential replay | — |
| Multi-pair backtest | ✅ | ✅ | ✅ Phase 3 | — |
| Multi-strategy backtest | ✅ `--strategy-list` | ✅ | ❌ | One strategy per backtest run |
| Multi-venue backtest | ❌ Native | ✅ | ❌ | Binance only |
| Parameter optimization | ✅ Hyperopt (optuna) | ✅ Grid search | ✅ Grid search (Phase 8) | freqtrade has Bayesian hyperopt; Enma has grid only |
| Hyperopt loss functions | ✅ 10+ built-in | ✅ Custom | ❌ | Enma has 8 objectives but no Bayesian search |
| Performance calendar | ✅ Built-in | ❌ | ✅ | — |
| Backtest report metrics | ✅ Sharpe, Sortino, Calmar, SQN, etc. | ✅ Full suite | ✅ 14-metric grid + Phase 2 | Enma's report is more visual than freqtrade's CLI |
| Trade export | ✅ CSV/JSON | ✅ Parquet | ✅ JSON | — |
| Position stacking | ✅ | ✅ | ❌ | Multiple entries same pair not supported |
| Lookahead analysis | ✅ | ❌ | ❌ | No automated lookahead detection |
| Recursive analysis | ✅ | ❌ | ❌ | No automated recursion bias detection |
| Walk-forward analysis | ✅ Custom | ✅ | ❌ | Not implemented |
| MCPT (Monte Carlo Permutation Test) | ❌ | ❌ | 🟡 Research | `mcpt-repo-analysis.md` exists but not implemented |

### 1.4 Order Types & Execution

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| Market orders | ✅ | ✅ | ✅ | — |
| Limit orders | ✅ | ✅ | ✅ | — |
| Stop-loss / TP | ✅ | ✅ | ✅ | — |
| Trailing stop | ✅ | ✅ | ✅ | Added in Workstream #2 |
| OCO (One-Cancels-Other) | ✅ | ✅ | ✅ OUO | Via Binance algo orders |
| OTO (One-Triggers-Other) | ❌ | ✅ | ❌ | Not implemented |
| IOC / FOK | ❌ | ✅ | ❌ | Not exposed in UI/engine |
| GTD / DAY | ❌ | ✅ | ❌ | Not implemented |
| Iceberg orders | ❌ | ✅ | ✅ Pluggable (Phase 8) | Enma has exec algo but not integrated with Binance |
| TWAP / VWAP | ❌ | ✅ | ✅ Pluggable (Phase 8) | Exec algo exists but not wired to live |
| Contingency orders | ❌ | ✅ | 🟡 | Partial via algo order IDs |
| DCA / Position adjustment | ❌ | ✅ | ✅ Phase 9 | — |
| Entry/exit tagging | ❌ | ✅ | ✅ Phase 9 | — |
| Emulated orders | ❌ | ✅ | ❌ | Nautilus simulates venue restrictions locally |

### 1.5 Exchanges & Venues

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| Binance Futures | ✅ | ✅ | ✅ Testnet only | — |
| Mainnet trading | ✅ | ✅ | ❌ Planned | — |
| Spot trading | ✅ | ✅ | ❌ | Futures only |
| Bybit | ✅ | ✅ | ❌ | — |
| OKX | ✅ | ✅ | ❌ | — |
| Kraken | ✅ | ✅ | ❌ | — |
| Bitget | ✅ | ✅ | ❌ | — |
| Hyperliquid DEX | ✅ | ✅ | ❌ | — |
| Gate.io | ✅ | ✅ | ❌ | — |
| Coinbase | ❌ | ✅ | ❌ | — |
| Deribit | ❌ | ✅ | ❌ | Options/futures |
| Interactive Brokers | ❌ | ✅ | ❌ | Equities/FX |
| Betfair | ❌ | ✅ | ❌ | Sports betting |
| Databento | ❌ | ✅ | ❌ | Data provider |
| Adapter architecture | ❌ ccxt | ✅ Modular adapters | ❌ | Enma has no abstraction for multi-venue |

### 1.6 Risk Management

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| Stoploss | ✅ Fixed/trailing | ✅ | ✅ | — |
| Max drawdown circuit | ✅ | ✅ | ✅ | — |
| Position sizing | ✅ | ✅ | ✅ size_by_risk | — |
| Portfolio exposure cap | ✅ | ✅ | ✅ | Added Workstream #2 |
| Value-at-Risk (VaR) | ❌ | ✅ | 🟡 | Risk Dashboard shows VaR (Zone 1) |
| Correlation matrix | ❌ | ✅ | 🟡 | Basic heatmap in Risk Dashboard |
| Monte Carlo simulation | ❌ | ❌ | 🟡 | Risk Dashboard Zone 3 + roadmap |
| Leverage sensitivity | ❌ | ❌ | 🟡 | Risk Dashboard has basic scenario re-runs |
| Per-symbol risk limits | ❌ | ✅ | 🟡 | Hierarchical overrides exist |
| Max position per asset | ✅ | ✅ | ❌ | Not implemented |

### 1.7 Live Trading

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| Dry-run / Paper trading | ✅ | ✅ | ✅ Binance Testnet | — |
| Live execution | ✅ | ✅ | ❌ Planned | Testnet only |
| Session persistence | ✅ SQLite | ✅ Redis | ✅ MongoDB | — |
| Multi-symbol live bot | ✅ | ✅ | ✅ | — |
| Multi-strategy live bot | ✅ | ✅ | ❌ | One strategy per session |
| WebUI bot control | ✅ FreqUI | ❌ | ✅ | — |
| Telegram control | ✅ | ❌ | ❌ | No Telegram integration |
| Webhook notifications | ✅ | ❌ | ❌ | Not implemented |
| Producer/Consumer mode | ✅ | ❌ | ❌ | freqtrade allows multi-bot coordination |
| Chaos mode / stress test | ❌ | ❌ | ✅ | Enma unique feature |
| Symbol lock system | ❌ | ✅ | ✅ | — |
| Exchange reconciliation | ❌ | ✅ | ✅ Phase 5 | — |
| User data stream | ❌ | ✅ | ✅ | Binance WS listen key |

### 1.8 Strategy Development

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| Python-based strategies | ✅ | ✅ | ✅ | — |
| Rust-based strategies | ❌ | ✅ | ❌ | Nautilus allows pure Rust strategies |
| Strategy templates | ✅ `new-strategy` | ✅ Examples | ✅ Clone/create | — |
| Informative pairs | ✅ Decorator | ✅ | ❌ | Enma has no multi-timeframe data in strategy |
| DataProvider API | ✅ orderbook, ticker, funding | ✅ Cache/Portfolio | 🟡 | Limited to candles + position data |
| Custom indicators | ✅ | ✅ | ✅ Pluggable backend | — |
| Backtesting via web UI | ✅ FreqUI | ❌ | ✅ | — |
| Jupyter integration | ✅ | ✅ | ❌ | No notebook support |
| Strategy analysis notebook | ✅ | ❌ | ❌ | Not implemented |
| Plotting (indicator charts) | ✅ `plot-dataframe` | ✅ Matplotlib/Plotly | 🟡 | Trade page has lightweight-charts |
| Custom data in strategies | ❌ | ✅ | ❌ | No external data sources |

### 1.9 Machine Learning / AI

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| Built-in ML pipeline | ✅ FreqAI | ❌ | ❌ | freqtrade's FreqAI has feature engineering, RL |
| Reinforcement learning | ✅ FreqAI-RL | ✅ (training speed) | ❌ | Nautilus is fast enough for RL training; Enma is not |
| Feature engineering | ✅ FreqAI | ❌ | ❌ | No automated feature pipeline |
| Adaptive model retraining | ✅ FreqAI | ❌ | ❌ | FreqAI self-trains during live |
| Backtest with live models | ✅ | ❌ | ❌ | FreqAI allows backtesting trained models |
| Volatility forecasting | ❌ | ❌ | 🟡 Research | In future_paths.md |
| Regime detection | ❌ | ❌ | 🟡 Research | In future_paths.md |

### 1.10 Platform / DevOps

| Feature | freqtrade | nautilus_trader | Enma | Gap |
|---------|-----------|-----------------|------|-----|
| CLI interface | ✅ Rich CLI | ✅ Limited | ❌ | No CLI for running tasks |
| REST API | ✅ FreqTRADE REST | ✅ gRPC-like | ✅ FastAPI | — |
| Docker Compose | ✅ | ✅ | ✅ | — |
| CI/CD | ✅ GitHub Actions | ✅ GitHub Actions | ✅ GitHub Actions | — |
| Data conversion tools | ✅ `convert-data` | ✅ CSV → Parquet | ❌ | No import/export utilities |
| Strategy updater | ✅ | ❌ | ❌ | Auto-migrate old strategy files |
| Systemd service | ✅ | ❌ | ❌ | No production deployment config |
| Documentation site | ✅ ReadTheDocs | ✅ Custom site | ❌ | Enma has workspace/docs only |

---

## 2. Categorized Gap Analysis

### 2.1 High-Value, Low-Effort (could ship in days)

These features exist in one or both reference projects and are straightforward to add to Enma:

| # | Feature | Source | Effort | Why It Matters |
|---|---------|--------|--------|----------------|
| 1 | **Max position per asset** | both | S | Prevents over-concentration; complements portfolio cap |
| 2 | **Position stacking (multiple entries same pair)** | freqtrade | M | Enables DCA-style scaling; Phase 9 groundwork exists |
| 3 | **Telegram bot notifications** | freqtrade | M | Push notifications for trade events, errors, daily summary |
| 4 | **Webhook notifications** | freqtrade | S | Slack/Discord webhooks on trade open/close |
| 5 | **Informative pairs / multi-timeframe data** | freqtrade | M | Strategies referencing higher timeframe signals (e.g., 1h trend on 5m entries) |
| 6 | **Data conversion tools** | both | S | Import/export CSV, JSON, Parquet formats |
| 7 | **Strategy analysis notebook** | freqtrade | M | Jupyter notebook to analyze backtest trades interactively |

### 2.2 Medium Value, Medium Effort (1–2 weeks)

| # | Feature | Source | Effort | Why It Matters |
|---|---------|--------|--------|----------------|
| 8 | **Bayesian hyperopt (optuna)** | freqtrade | M | Better parameter search than grid; optuna is well-established |
| 9 | **Walk-forward analysis** | freqtrade | M | Tests strategy robustness across time periods |
| 10 | **Lookahead / recursive bias detection** | freqtrade | M | Catches data leakage before deployment |
| 11 | **Jupyter / research notebook integration** | both | M | Interactive analysis improves strategy iteration speed |
| 12 | **Multi-strategy backtest** | freqtrade | M | Compare strategies on same data in one run |
| 13 | **Plotting (indicator charts with signals)** | freqtrade | M | Visual validation of entry/exit logic |
| 14 | **CLI interface for common tasks** | freqtrade | M | Run backtests, list strategies, manage bots from terminal |
| 15 | **Systemd / production service config** | freqtrade | S | Production deployment outside Docker |

### 2.3 High Value, Higher Effort (2–4 weeks)

| # | Feature | Source | Effort | Why It Matters |
|---|---------|--------|--------|----------------|
| 16 | **Multi-exchange support (adapter architecture)** | nautilus | XL | Opens Enma to Bybit, OKX, Kraken, etc. |
| 17 | **Mainnet trading** | both | M | Real capital deployment (already planned) |
| 18 | **FreqAI-style ML pipeline** | freqtrade | XL | Feature engineering + model training + live inference |
| 19 | **Parquet data catalog with versioning** | nautilus | M | Reproducible backtests with immutable datasets |
| 20 | **Tick-level data & backtesting** | nautilus | L | Higher-fidelity simulation for high-frequency strategies |
| 21 | **Order book in backtesting** | nautilus | L | L2/L3 simulation for order-flow strategies |
| 22 | **Multi-strategy live sessions** | freqtrade | M | Run multiple strategies simultaneously |
| 23 | **Advanced order types (IOC, FOK, GTD, OTO)** | nautilus | M | More precise execution control |
| 24 | **Producer/Consumer multi-bot mode** | freqtrade | M | Coordinate multiple bot instances |

### 2.4 Exploratory / Research (low priority but high ceiling)

| # | Feature | Source | Effort | Why It Matters |
|---|---------|--------|--------|----------------|
| 25 | **MCP-enabled agent integration** | nautilus | XL | QuantDinger-style AI agent orchestration |
| 26 | **Rust core migration** | nautilus | XL | Performance; enables HFT and RL training |
| 27 | **Derivatives (options) support** | nautilus | XL | Greeks, volatility surface |
| 28 | **Equities / multi-asset** | both | XL | New data sources, SEC filings |

---

## 3. Sequencing Proposal

The sequence respects Enma's existing architecture (single-user, crypto, Binance, Python engine) and builds on shipped work (Phases 1–9, Workstreams 1–2).

### Phase N-1: Quick Wins (days)

1. **Max position per asset** — add to risk model (follows `max_portfolio_risk` pattern)
2. **Webhook notifications** — POST to configured URL on trade events; configurable in Settings
3. **Data conversion CLI tools** — `enma-cli convert-data --from csv --to json`; lightweight wrapper
4. **Informative pairs in strategy contract** — allow `prepare()` to receive higher-timeframe candles (backward-compatible default)

### Phase N-2: Analysis & Optimization (1–2 weeks)

5. **Bayesian hyperopt** — add optuna to existing `optimizer.py`; optuna handles parallel trials natively
6. **Lookahead analysis command** — `scripts/lookahead.py` detects `df.iloc[-1]` or unshifted future refs
7. **Recursive analysis** — `scripts/recursive.py` re-runs strategy on growing candle window, measures indicator variance
8. **Walk-forward analysis** — split timerange into training/validation/test windows

### Phase N-3: Research Parity (1–2 weeks)

9. **Jupyter integration** — `engine/notebooks/` with pre-built cells loading backtest results and trades
10. **Strategy analysis notebook template** — freqtrade-style P&L, trade list, equity curve, drawdown
11. **Plotting (indicator + signal overlay)** — generate matplotlib/plotly charts from backtest results

### Phase N-4: Multi-Venue (2–4 weeks, only after N-3)

12. **Adapter architecture** — abstract exchange interface (`ExchangeAdapter` with `fetch_candles()`, `place_order()`, etc.)
13. **Bybit integration** — first non-Binance adapter (futures, similar API pattern)
14. **Mainnet trading** — exchange mode selector in Settings (already planned)

### Phase N-5: ML/AI (research gate)

15. **FreqAI-style feature engineering** — strategy metadata declares features; engine auto-computes them
16. **Model training + persistence** — sklearn/xgboost models saved alongside strategies
17. **Live inference** — model loaded on session start, features computed per-candle

---

## 4. Items Deferred (explicitly not planned)

| Item | Reason |
|------|--------|
| **Rust core migration** | Too invasive; Enma is Python-based and the Python engine is performant enough for 1h/15m/5m strategies |
| **Telegram bot** | Limited value for single-user self-hosted; webhooks cover notification needs |
| **Options / Greeks** | Crypto futures only; no options market support planned |
| **Betfair / sports betting** | Out of scope for crypto trading |
| **Spot trading** | Futures-only architecture; spot would require separate account model |
| **ccxt library** | Rejected per `AGENTS.md` constraints; Enma uses native httpx HMAC |
| **Multi-user / auth** | Single-user per `AGENTS.md` |

---

## 5. References

- `workspace/plan/INDEX.md` — current execution sequence (dashboard restructure, risk dashboard)
- `workspace/plan/future_paths.md` — exploratory ideas (Monte Carlo, volatility forecasting, regime detection)
- `workspace/plan/RISK_DASHBOARD_PLAN.MD` — planned Risk Dashboard (VaR, correlation, Monte Carlo)
- `workspace/plan/mcpt-repo-analysis.md` — Monte Carlo Permutation Tests (research phase)
- `workspace/docs/state/CURRENT_STATE.md` — authoritative Enma feature inventory
