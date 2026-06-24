# Enma — Risk Dashboard Plan

This plan details the design, quantitative features, control architecture, and database integrations for the **Risk Dashboard** — a dedicated page positioned in the horizontal navigation bar between **Strategies** and **Backtest**. 

The Risk Dashboard provides a single pane of glass for real-time portfolio exposure monitoring, historical risk profiling, and hierarchical parameter control.

---

## 1. Overview & Strategic Goals

Enma is a single-user, self-hosted algorithmic trading platform. Adding the Risk Dashboard elevates the platform from symbol-centric tracking to **portfolio-level risk intelligence**. It enforces safety rails across live trading bots and backtests alike.

### Key Architecture Constraints (from `AGENTS.md`)
- **Single-User:** No `user_id` fields are introduced. Settings are stored under the `'global'` document in MongoDB.
- **Layer Boundaries:** All mathematical and statistical risk calculations (Value at Risk, Beta, Correlation) live inside the Python `engine/`. The Node `server/` handles metadata caching, API routing, and BullMQ job management. The React `client/` is responsible for visual presentation.
- **P&L Colors:** Strictly uses `emerald-400` (profit / low risk) and `red-400` (loss / high risk) over the dark theme (`bg-gray-950`).
- **Testnet-First:** Live risk monitoring applies to active Binance Testnet API feeds.
- **UI Styling Rules:** Enforce strict sharp edges (Rule 1: No rounded corners, no `rounded-*` classes) and connected layouts (Rule 2).

### Navbar Integration
Positioned in `client/src/components/layout/Navbar.jsx` between **Strategies** and **Backtest**:
```javascript
const navItems = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
  { label: 'Trade', icon: Activity, to: '/trade' },
  { label: 'Strategies', icon: Code2, to: '/strategies' },
  { label: 'Risk Dashboard', icon: ShieldAlert, to: '/risk-dashboard' }, // <-- Dedicated Page
  { label: 'Backtest', icon: FlaskConical, to: '/backtest' },
  { label: 'AlgoTrading', icon: Bot, to: '/algo' },
  { label: 'Order History', icon: History, to: '/order-history' },
  { label: 'Settings', icon: Settings, to: '/settings' },
]
```

### Route Configuration
Mounted in `client/src/App.jsx`:
```jsx
<Route path="/risk-dashboard" element={<RiskDashboard />} />
```

---

## 2. Dashboard Features & Visual Layout

The page is designed with a professional trading terminal aesthetic, structured into three distinct zones:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                   ZONE 1: Real-Time Portfolio Risk                       │
│  [Margin Ratio Gauge]   [Exposure Bar Chart]   [Rolling Correlation Map]  │
├──────────────────────────────────────────────────────────────────────────┤
│                   ZONE 2: Hierarchical Parameter Controls                │
│  [Global Limits]       [Strategy Overrides]      [Symbol/Vol Clamps]     │
├──────────────────────────────────────────────────────────────────────────┤
│                   ZONE 3: Backtest & Historical Risk Profiler            │
│  [Leverage Sensitivity] [Sharpe/Calmar Metrics] [Monte Carlo Ruin Curve] │
└──────────────────────────────────────────────────────────────────────────┘
```

### Zone 1: Real-Time Portfolio Risk (Live Active Sessions)
1. **Aggregate Margin & Leverage Gauge:** Total locked initial margin vs. free wallet balance on Binance Testnet, alongside the net portfolio leverage (Total Notional / Equity).
2. **Net Exposure & Directionality:** A horizontal stacked bar chart showing aggregate Long vs. Short notional exposure across all traded symbols.
3. **Value-at-Risk (VaR) & Conditional VaR (CVaR) Panel:** Live estimate of maximum potential portfolio loss over a 1-day horizon at 95% and 99% confidence levels.
4. **Rolling Pearson Correlation Heatmap:** An interactive grid visualization showing relationships between close-price returns of all actively traded symbols in the last 30 days (720 hours).
5. **Drawdown Circuit Breakers:** Status bar indicating the session drawdown of the active portfolio relative to the allowed limit (`max_session_dd`).

### Zone 2: Hierarchical Parameter Controls
An interactive configuration panel to adjust parameters that govern trading execution. Rather than static settings, parameters are managed in a cascading hierarchy:

| Control Level | Scope | Example Parameter | Editable On Dashboard? |
|---|---|---|---|
| **1. Global Hard Limits** | Platform-wide hard ceiling (circuit breakers) | `hardMaxLeverage`, `hardMaxSessionDrawdown` | Yes (Requires confirmation) |
| **2. Global Defaults** | Default fallbacks for wizards | `defaultRiskPct` (0.01), `defaultMinEdgeMult` (0.05) | Yes |
| **3. Strategy-Specific** | Tied to a strategy class | `AdaptiveTrend.trail_atr_mult` (2.5) | Yes |
| **4. Symbol-Specific** | Tied to market asset rules | `DOGEUSDT.max_leverage_clamp` (10x limit) | Yes |
| **5. Run-Specific** | Individual session wizard overrides | `risk_pct` (0.02 override for this run only) | No (Configured in Wizard) |

### Zone 3: Backtest & Historical Risk Profiler
An analytics panel that aggregates metrics from completed backtest runs (`backtestResults` and `backtestTrades`):
1. **Leverage Sensitivity Analysis:** A line chart plotting simulated net profit vs. maximum drawdown under hypothetical leverage overrides (1x, 2x, 5x, 10x, 20x).
2. **Excursion Analysis Scatter Plot:** Plots Maximum Favorable Excursion (MFE) vs. Maximum Adverse Excursion (MAE) of completed trades to visualize stop-placement safety margins.
3. **Monte Carlo Probabilities:** Distribution curve displaying probability of ruin and drawdown recovery timelines based on resampled trade logs.

---

## 3. Parameter Controls & Precedence Flow

When a live bot or a backtest starts, parameter resolution follows a strict precedence:

```
┌──────────────────────────────────────────────┐
│       1. Start Backtest / Live Session       │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  Did the user specify custom parameters?     │
│  (e.g., custom parameters in launch Wizard)  │
└──────┬───────────────────────────────┬───────┘
       │ Yes                           │ No
       ▼                               ▼
┌──────────────────────────────┐ ┌──────────────────────────────┐
│ Use Wizard Run Overrides     │ │ Read Strategy-Specific       │
│                              │ │ Parameter Overrides (Db)     │
└──────┬───────────────────────┘ └──────┬───────────────────────┘
       │                               │ If absent
       │                               ▼
       │                         ┌──────────────────────────────┐
       │                         │ Read Global Default Settings │
       │                         │ (Settings collection)        │
       └───────────────┬─────────┴──────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ Apply Symbol-Specific Leverage Clamping     │
│ (e.g. clamp leverage to max allowed bracket) │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ Enforce Global Hard Limits                   │
│ (e.g. clamp resolved values to hard ceilings)│
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│       Final Resolved Runtime Parameters      │
└──────────────────────────────────────────────┘
```

### Param Resolver Logic (`server/src/utils/risk.js`)

To resolve parameters and maintain compatibility with the database and the Python Engine, the resolver outputs **snake_case** keys and correctly accesses the database schema fields:

```javascript
const { RISK_FIELDS, clamp } = require('./risk');

/**
 * Resolves final risk parameters for a backtest or live session symbol.
 * Handles the cascading priority: Wizard Override -> Strategy Override -> Symbol Override -> Global defaults.
 * Clamps output values by Global Hard Limits.
 */
function resolveStrategyRiskParams(strategyName, symbol, savedSettings = {}, wizardOverride = {}) {
  const strategyRules = (savedSettings.strategyOverrides || {}).get?.(strategyName) || {};
  const symbolRules = (savedSettings.symbolOverrides || {}).get?.(symbol) || {};
  const hardLimits = savedSettings.globalHardLimits || {};

  const out = {};
  
  // Resolve base fields and map to engine's snake_case contract
  for (const [camelField, rule] of Object.entries(RISK_FIELDS)) {
    let val = wizardOverride[camelField];
    if (val === undefined || val === null) val = strategyRules[camelField];
    if (val === undefined || val === null) val = symbolRules[camelField];
    if (val === undefined || val === null) val = savedSettings[camelField]; // top-level defaults
    if (val === undefined || val === null) val = rule.fallback;
    
    // Clamp by Global Hard Limits (using correct schema keys)
    if (camelField === 'riskPct' && hardLimits.maxRiskPctPerTrade !== undefined) {
      val = Math.min(val, hardLimits.maxRiskPctPerTrade);
    }
    if (camelField === 'maxSessionDrawdown' && hardLimits.maxSessionDrawdown !== undefined) {
      val = Math.min(val, hardLimits.maxSessionDrawdown);
    }
    
    out[rule.engineKey] = clamp(val, rule.min, rule.max);
  }
  
  // Resolve leverage specifically
  let leverageVal = wizardOverride.leverage;
  if (leverageVal === undefined || leverageVal === null) leverageVal = symbolRules.maxLeverage;
  if (leverageVal === undefined || leverageVal === null) leverageVal = savedSettings.defaultLeverage;
  if (leverageVal === undefined || leverageVal === null) leverageVal = 1;
  
  if (hardLimits.maxLeverageAllowed !== undefined) {
    leverageVal = Math.min(leverageVal, hardLimits.maxLeverageAllowed);
  }
  out.leverage = clamp(leverageVal, 1, 125);
  
  // Custom settings passed down to engine
  out.volatility_multiplier = symbolRules.volatilityMultiplier ?? 1.0;
  out.max_exposure_notional = symbolRules.maxExposureNotional ?? Infinity;
  out.custom_atr_mult = strategyRules.customAtrMult ?? null;

  return out;
}

module.exports = {
  resolveStrategyRiskParams,
  // ... existing exports
};
```

---

## 4. Database Schema Expansion

We expand the MongoDB `Settings` collection schema (`server/src/models/Settings.js`) to support the nested hierarchy.

```javascript
// Append to Mongoose SettingsSchema
const SettingsSchemaExpansion = {
  // ── Global Hard Constraints (Safety Circuit Breakers) ───────────────────
  globalHardLimits: {
    maxLeverageAllowed:   { type: Number, default: 50,    min: 1,    max: 125 },
    maxSessionDrawdown:   { type: Number, default: 0.30,  min: 0.05, max: 0.90 },
    maxRiskPctPerTrade:   { type: Number, default: 0.05,  min: 0.001,max: 0.20 },
    cooldownPeriodHours:  { type: Number, default: 12,    min: 1,    max: 72   },
  },

  // ── Global Default Fallbacks (Currently top-level properties) ───────────
  // We keep the top-level parameters for backward compatibility but allow
  // the dashboard to manage them cleanly in a grouped interface.

  // ── Strategy-Specific Custom Rules ────────────────────────────────────────
  // Keyed by Strategy Name (e.g., "AdaptiveTrend", "MicroScalper")
  strategyOverrides: {
    type: Map,
    of: new mongoose.Schema({
      riskPct:            { type: Number, min: 0.0001, max: 1   },
      riskRewardRatio:    { type: Number, min: 0.1,    max: 100 },
      maxSessionDrawdown: { type: Number, min: 0.01,   max: 1   },
      liqBufferPct:       { type: Number, min: 0,      max: 0.5 },
      minEdgeMult:        { type: Number, min: 0,      max: 10  },
      customAtrMult:      { type: Number }, // Strategy specific stop mults
    }, { _id: false }),
    default: {}
  },

  // ── Symbol-Specific Risk Parameters ─────────────────────────────────────
  // Keyed by Symbol Name (e.g., "BTCUSDT", "SOLUSDT")
  symbolOverrides: {
    type: Map,
    of: new mongoose.Schema({
      maxLeverage:        { type: Number, min: 1, max: 125 },
      volatilityMultiplier: { type: Number, default: 1.0 }, // scaling factor for ATR stops
      maxExposureNotional:{ type: Number, min: 100 },       // max dollar size allowed
    }, { _id: false }),
    default: {}
  }
};
```

---

## 5. API Contracts & Communication Flow

Three REST endpoints coordinate the client, server, and engine. Numeric values conform to the `API_CONTRACTS.md` string precision rule:

### 1. `GET /api/v1/risk/settings` & `PUT /api/v1/risk/settings`
- **Purpose:** Read and write hierarchical limits.
- **Server Controller:** `server/src/controllers/settings.controller.js` updates the maps.
- **JSON Payload (PUT):**
  ```json
  {
    "globalHardLimits": {
      "maxLeverageAllowed": 25,
      "maxSessionDrawdown": 0.25
    },
    "strategyOverrides": {
      "AdaptiveTrend": {
        "riskPct": 0.015,
        "riskRewardRatio": 3.0
      }
    },
    "symbolOverrides": {
      "SOLUSDT": {
        "maxLeverage": 10,
        "maxExposureNotional": 5000
      }
    }
  }
  ```

### 2. `GET /api/v1/risk/live-metrics`
- **Purpose:** Returns real-time risk summaries of active bot sessions.
- **Caching Mechanism:** Cache results for 10 seconds to avoid exceeding Binance rate limits.
- **Response Format:**
  ```json
  {
    "success": true,
    "data": {
      "aggregateMarginUsed": "450.25",
      "aggregateWalletBalance": "10000.00",
      "netLeverage": "2.15",
      "activeSymbols": ["BTCUSDT", "ETHUSDT"],
      "exposures": {
        "BTCUSDT": { "side": "long", "notional": "12000.00", "leverage": "10" },
        "ETHUSDT": { "side": "short", "notional": "9500.00", "leverage": "5" }
      },
      "valueAtRisk": {
        "var95_1d": "340.50",
        "var99_1d": "510.75",
        "cvar95_1d": "420.00"
      },
      "correlationMatrix": {
        "BTCUSDT": { "BTCUSDT": "1.00", "ETHUSDT": "0.82" },
        "ETHUSDT": { "BTCUSDT": "0.82", "ETHUSDT": "1.00" }
      }
    }
  }
  ```

### 3. `GET /api/v1/risk/backtest/:id/simulation`
- **Purpose:** Returns leverage sensitivity metrics and Monte Carlo ruin probabilities for completed backtests.
- **Response Format:**
  ```json
  {
    "success": true,
    "data": {
      "leverageSensitivity": [
        { "leverage": 1, "netProfitPct": "12.50", "maxDrawdownPct": "4.20" },
        { "leverage": 2, "netProfitPct": "24.10", "maxDrawdownPct": "8.50" },
        { "leverage": 5, "netProfitPct": "48.20", "maxDrawdownPct": "19.30" }
      ],
      "monteCarlo": {
        "ruinProbability": "0.025",
        "drawdownDistribution": [
          { "drawdownPct": "10.00", "probability": "0.85" },
          { "drawdownPct": "20.00", "probability": "0.45" }
        ]
      }
    }
  }
  ```

---

## 6. Python Engine Risk Math Calculations

The Python `engine/` implements a new service `engine/utils/risk_math.py` using vectorized calculations on candle data.

### 1. Value at Risk (VaR) & Conditional VaR (CVaR)
Computed using **Historical Simulation** over the last 100 periods of 1-hour returns. Includes guards against empty histories and NaNs:

```python
import numpy as np
from typing import List, Dict, Tuple

def calculate_portfolio_var(
    position_notionals: Dict[str, float], 
    price_histories: Dict[str, np.ndarray], 
    confidence_level: float = 0.95
) -> Tuple[float, float]:
    """
    Calculates historical Value at Risk (VaR) and CVaR for a portfolio.
    position_notionals: dict mapping symbol -> signed notional size (+ for long, - for short)
    price_histories: dict mapping symbol -> numpy array of historical closing prices
    """
    if not price_histories or not position_notionals:
        return 0.0, 0.0

    # Compute logarithmic returns for each symbol
    returns = {}
    min_len = min(len(prices) for prices in price_histories.values())
    if min_len < 2:
        return 0.0, 0.0
    
    for symbol, prices in price_histories.items():
        p = prices[-min_len:]
        # Remove NaNs and compute returns
        p = p[~np.isnan(p)]
        if len(p) < 2:
            continue
        returns[symbol] = np.diff(np.log(p))

    if not returns:
        return 0.0, 0.0

    assets = list(returns.keys())
    # Ensure all aligned returns are the same length
    run_len = min(len(returns[a]) for a in assets)
    if run_len < 1:
        return 0.0, 0.0
        
    r_matrix = np.column_stack([returns[a][-run_len:] for a in assets])
    
    # Portfolio weights based on absolute notional values
    sizes = np.array([position_notionals[a] for a in assets])
    total_notional = np.sum(np.abs(sizes))
    if total_notional == 0:
        return 0.0, 0.0
    
    # Signed weights (shorts have negative weights)
    weights = sizes / total_notional
    port_returns = np.dot(r_matrix, weights)
    
    alpha = 1.0 - confidence_level
    var_pct = np.percentile(port_returns, alpha * 100)
    
    # Clean up edge case where returns are positive even in the tail
    var_pct = min(0.0, var_pct)
    var_amount = abs(var_pct * total_notional)
    
    tail_losses = port_returns[port_returns <= var_pct]
    if len(tail_losses) > 0:
        cvar_amount = abs(np.mean(tail_losses) * total_notional)
    else:
        cvar_amount = var_amount
        
    return float(var_amount), float(cvar_amount)
```

### 2. Rolling Pearson Correlation Matrix
Calculated from 1-hour returns over a rolling 30-day (720-hour) window. Guards against division by zero:

```python
import pandas as pd
import numpy as np
from typing import Dict

def calculate_correlation_matrix(price_histories: Dict[str, np.ndarray]) -> Dict[str, Dict[str, float]]:
    """
    Returns correlation matrix as a nested dictionary.
    """
    if not price_histories:
        return {}
    
    df_data = {}
    for symbol, prices in price_histories.items():
        # Remove NaNs
        clean_prices = prices[~np.isnan(prices)]
        if len(clean_prices) < 2:
            continue
        df_data[symbol] = np.diff(np.log(clean_prices))
        
    if not df_data:
        return {}
        
    min_len = min(len(arr) for arr in df_data.values())
    if min_len < 2:
        return {}
        
    aligned_data = {k: v[-min_len:] for k, v in df_data.items()}
    
    df = pd.DataFrame(aligned_data)
    corr_df = df.corr(method='pearson').fillna(0.0)
    
    # Standardize diagonal elements to 1.0
    for col in corr_df.columns:
        corr_df.loc[col, col] = 1.0
        
    return corr_df.to_dict()
```

### 3. Engine Wiring of Custom Constraints

#### `engine/core/models/base.py → atr_stop()`
Multiply the ATR multiplier by the symbol's configured volatility multiplier:
```python
def atr_stop(self, s, direction: str, mult: float = 2.0, period: int = 14,
             entry_price: float | None = None) -> float:
    """ATR-based stop: long = entry − mult·ATR, short = entry + mult·ATR."""
    entry = entry_price if entry_price is not None else s.price
    atr = s._atr(period)
    
    # Fetch resolved symbol-specific volatility multiplier
    vol_mult = float(getattr(s, "volatility_multiplier", 1.0))
    mult = mult * vol_mult
    
    return entry - mult * atr if direction == "long" else entry + mult * atr
```

#### `engine/core/models/risk.py → AtrBracketRiskModel.assess()`
Override the stop multiplier dynamically if `custom_atr_mult` is defined for the strategy:
```python
# Stop: prefer precomputed vars -> custom_sl_pct -> custom_atr_mult -> default sl_atr_mult
sl_mult = float(getattr(s, "custom_atr_mult", None) or getattr(s, "sl_atr_mult", 2.0))
```

#### `engine/core/strategy.py → max_qty()`
Cap the maximum affordable quantity using the symbol's `max_exposure_notional`:
```python
def max_qty(self, entry_price: float | None = None) -> float:
    """Max quantity affordable, capped by equity leverage and symbol exposure limits."""
    entry = entry_price if entry_price is not None else self.price
    if entry <= 0:
        return 0.0
    max_notional = self.equity * max(self.leverage, 1)
    
    # Enforce symbol-specific maximum exposure
    symbol_max_exposure = float(getattr(self, "max_exposure_notional", float('inf')))
    max_notional = min(max_notional, symbol_max_exposure)
    
    return max_notional / entry
```

#### Multi-Symbol Risk Config Injection (`engine/core/live_bot_manager.py`)
Extract the symbol-specific configuration slice from the received session `risk_params`:
```python
_risk_all = risk_params or {}
# Support symbol-specific nested dictionaries or fall back to default settings
_risk = _risk_all.get(symbol) or _risk_all.get("default") or _risk_all

strategy.risk_pct          = float(_risk.get("risk_pct",       strategy.risk_pct))
strategy.rrr               = float(_risk.get("rrr",            strategy.rrr))
strategy.liq_buffer_pct    = float(_risk.get("liq_buffer_pct", strategy.liq_buffer_pct))
strategy.max_session_dd    = float(_risk.get("max_session_dd", strategy.max_session_dd))

# Custom fields
strategy.volatility_multiplier = float(_risk.get("volatility_multiplier", 1.0))
strategy.max_exposure_notional = float(_risk.get("max_exposure_notional", float('inf')))
strategy.custom_atr_mult       = _risk.get("custom_atr_mult")
if strategy.custom_atr_mult is not None:
    strategy.custom_atr_mult = float(strategy.custom_atr_mult)
```

---

## 7. Frontend Mockups & CSS Requirements

### Heatmap Component Styling
Conforms strictly to **Rule 1 (No rounded corners)** and UI Guide palette styles. Computes text contrast dynamically:

```jsx
// client/src/components/risk/CorrelationHeatmap.jsx
import React from 'react';

export default function CorrelationHeatmap({ matrix = {} }) {
  const symbols = Object.keys(matrix);
  
  const getBgColor = (val) => {
    // val is between -1.0 and 1.0
    if (val > 0) {
      const opacity = Math.round(val * 90);
      return `hsla(142, 70%, 45%, ${opacity / 100})`; // emerald-500 equivalent
    } else {
      const opacity = Math.round(Math.abs(val) * 90);
      return `hsla(350, 70%, 45%, ${opacity / 100})`; // red-500 equivalent
    }
  };

  const getTextColor = (val) => {
    // Dynamic contrast check: light gray for transparent/low opacity cells, dark for saturated cells
    return Math.abs(val) > 0.5 ? 'text-slate-950' : 'text-slate-300';
  };

  return (
    <div className="bg-[#0d1117] border border-slate-700/50 p-5 shadow-2xl">
      <h3 className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-4">
        Rolling 30d Asset Correlation
      </h3>
      <div className="grid gap-0" style={{ gridTemplateColumns: `repeat(${symbols.length + 1}, minmax(0, 1fr))` }}>
        {/* Label Header row */}
        <div className="text-[10px] font-semibold text-slate-500 p-1"></div>
        {symbols.map(s => (
          <div key={s} className="text-[10px] font-semibold text-slate-400 p-1 font-mono text-center truncate">
            {s.replace("USDT", "")}
          </div>
        ))}

        {/* Heatmap rows */}
        {symbols.map(rowSymbol => (
          <React.Fragment key={rowSymbol}>
            <div className="text-[10px] font-semibold text-slate-400 p-1 font-mono flex items-center">
              {rowSymbol.replace("USDT", "")}
            </div>
            {symbols.map(colSymbol => {
              const val = matrix[rowSymbol]?.[colSymbol] ?? 0;
              return (
                <div
                  key={colSymbol}
                  className={`aspect-square flex items-center justify-center text-[10px] font-semibold font-mono m-0.5 ${getTextColor(val)}`}
                  style={{ backgroundColor: getBgColor(val) }}
                  title={`${rowSymbol} vs ${colSymbol}: ${val.toFixed(2)}`}
                >
                  {val.toFixed(1)}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
```

---

## 8. Verification & Execution Testing Plan

### Automated Test Cases (`engine/tests/test_risk_math.py`)
Verify calculations are mathematically correct:
- **Test VaR calculations:** Generate synthetic price history with a known downward trend. Verify that `calculate_portfolio_var` returns positive risk amounts. Handle empty inputs without throwing Exceptions.
- **Test correlation boundaries:** Generate series with exact linear dependencies ($Y = 2X$ and $Z = -X$). Assert correlation returns exactly `1.0` and `-1.0` respectively, and check that diagonal elements are always `1.0`.
- **Test precedence clamping:** Assert that running `resolveStrategyRiskParams` with a wizard override larger than the global hard ceiling clamps the output value exactly to the hard ceiling.

### Manual Verification
1. Open settings, configure `maxLeverageAllowed` to `10x` under the global hard limits.
2. Launch a backtest using the New Backtest Wizard and attempt to set leverage to `20x`.
3. Verify that the backtest configuration form warns the user, and the execution is clamped to `10x` in the resulting run metrics.
4. Launch multiple bot sessions via Chaos Mode. Navigate to the new `/risk-dashboard` page and verify that the correlation matrix and Value-at-Risk parameters update in real-time.
