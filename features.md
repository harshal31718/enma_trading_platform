# ENMA Quant Platform — Backtest Results: Storage & Display

## Overview

After a backtest run completes, results are **not persisted to a database**. They are held entirely in React state in the browser for the duration of the session. The backend computes and streams results, the frontend captures them, and four UI components render them in different modes.

---

## 1. Data Flow: Backend → Frontend

### Backend Endpoints (`backend/main.go`)

| Endpoint | Method | Purpose |
|---|---|---|
| `POST /backtest` | REST | Synchronous backtest (legacy, unused in UI) |
| `POST /backtest/stream` | SSE | Streaming backtest with real-time progress |
| `GET /history` | REST | Fetch raw candles for the chart after results |

### Result Shape

**`BacktestResponse`** (JSON, carried in the final SSE `DONE` event):
```json
{
  "trades": [
    { "time": 1712750000000, "type": "BUY",  "price": 70500.5, "quantity": 0.141820, "pnl": 0 },
    { "time": 1712840000000, "type": "SELL", "price": 71200.1, "quantity": 0.141820, "pnl": 97.42 }
  ],
  "total_pnl": 97.42
}
```

**Trade struct** (`backend/internal/backtest/engine.go`):
- `time` — Unix ms timestamp of the candle
- `type` — `"BUY"` or `"SELL"`
- `price` — execution price with 0.05% slippage applied
- `quantity` — position size in base asset
- `pnl` — realized PnL on SELL trades (0 for BUY)

### How Results Are Produced (`engine.go`)

The engine runs an **EMA crossover strategy**:
- Calculates fast and slow EMAs over all candles
- On a bullish crossover → BUY (full balance, minus 0.1% fee + slippage)
- On a bearish crossover → SELL (close position, minus fees + slippage)
- If a position is open at the last candle, it is **force-closed**
- Max drawdown, win rate etc. are computed client-side from the trade list

### SSE Progress Stages (`backtestStreamHandler`)

Progress events are emitted as `text/event-stream`:

| Stage | % Range | Color in UI |
|---|---|---|
| `FETCHING` | 0 – 60 | Blue |
| `INITIALIZING` | 60 | Yellow |
| `SIMULATING` | 60 – 95 | Purple |
| `FINALIZING` | 95 | Green |
| `DONE` | 100 | Green (carries full payload) |
| `ERROR` | 0 | Red |

---

## 2. State Management (`app/backtest/page.tsx`)

All results live in component-level React state — **no localStorage, no DB**:

```ts
const [trades, setTrades]       = useState<Trade[]>([]);
const [totalPnL, setTotalPnL]   = useState<number | null>(null);
const [chartData, setChartData] = useState<Candle[]>([]);
```

On run:
1. `AbortController` is created for cancellation support
2. SSE stream is read line-by-line; progress state updates the `BacktestProgress` UI
3. On `DONE` event: `finalTrades` and `finalPnL` are captured
4. A **second fetch** hits `/history` to get the raw candle array for the chart
5. Both sets of state are committed → results panels render

---

## 3. Display Modes

### 3a. BacktestProgress — Live Progress Overlay
**File:** `frontend/components/backtest/BacktestProgress.tsx`

Shown while `isLoading === true`. Renders:
- A color-coded **stage badge** (each stage has a distinct color)
- A CSS `animate-spin` **spinner** (hidden on DONE/ERROR)
- A **progress bar** (`width` driven by `percent`, animated via CSS transition)
- A large **percentage number** (`font-mono`)
- A **status message** string from the SSE event
- A **"■ Stop Simulation"** cancel button (hidden on DONE/ERROR)

### 3b. BacktestChart — Candlestick Chart with Trade Markers
**File:** `frontend/components/backtest/BacktestChart.tsx`  
**Library:** `klinecharts` (open-source, canvas-based)

Two **custom canvas overlays** are registered globally once on mount:

| Overlay | Shape | Color |
|---|---|---|
| `buyMarker` | Filled triangle ▲ | `#22c55e` (green) |
| `sellMarker` | Filled triangle ▼ | `#ef4444` (red) |

Initialization is split into three `useEffect` hooks to avoid race conditions:
1. **Chart init** — delayed 100ms; creates the `klinecharts` instance, hides grid lines
2. **Data load** — fires when `data` + `isReady`; maps candles to `{ timestamp, open, high, low, close, volume }` and calls `chart.applyNewData()`
3. **Trade markers** — fires when `trades` arrive; removes old `trade-*` overlays and places new ones at each trade's `(timestamp, price)` coordinate with a ±0.3% vertical offset so markers don't overlap the candle body

The chart renders **no chart-level data persistence** — if the page reloads, the chart is empty.

### 3c. StatsPanel — Performance Overview Card
**File:** `frontend/components/backtest/StatsPanel.tsx`

All metrics are derived client-side via `useMemo` from the `trades[]` array:

| Metric | Calculation |
|---|---|
| **Total PnL** | Passed directly from backend `total_pnl` |
| **Win Rate** | `winTrades.length / sellTrades.length × 100` |
| **Total Trades** | Count of SELL trades (= closed positions) |
| **Max Drawdown** | Peak-to-trough of cumulative PnL across SELL trades |
| **Avg Profit** | `totalPnL / sellTrades.length` |
| **Consistency bar** | `min(completedTrades / 50, 1) × 100%` — visual fill bar |

Color coding: green (`#0ecb81`) for profit, red (`#f6465d`) for loss, yellow (`#f0b90b`) for neutral.

### 3d. TradesTable — Paginated Order History
**File:** `frontend/components/backtest/TradesTable.tsx`

Columns: **Time · Side · Price · Size · PnL · Cum. PnL**

Key implementation details:
- `useMemo` pre-computes a **running cumulative PnL** column across all trades
- **20 rows per page** (`ROWS_PER_PAGE = 20`)
- Pagination uses a windowed page number generator (max 7 visible, with `…` ellipsis)
- BUY/SELL badges: green-tinted vs red-tinted pill labels
- PnL cells colored green/red/gray depending on sign
- Row `onClick` → `onRowClick(time)` prop (wired for future chart scroll-to feature)
- Row `onMouseEnter/Leave` → `onRowHover(time | null)` prop (reserved for chart highlight)
- Resets to page 1 whenever `trades` prop changes (new backtest run)

---

## 4. Supporting Chart Components (Live Mode)

These are separate from backtest — used on market pages:

### SimpleChart (`frontend/components/charts/SimpleChart.tsx`)
- Uses `klinecharts` core (`init`/`dispose`)
- Loads history via `GET /history`, then opens a WebSocket to `ws://localhost:8080/ws` for live tick updates (`chart.updateData()`)
- Grid lines disabled

### ComplexChart (`frontend/components/charts/ComplexChart.tsx`)
- Uses `@klinecharts/pro` (full-featured: drawing toolbar, period selector, symbol search)
- Connects via `BinanceDatafeed` service which implements the KLineChartPro datafeed interface
- Supports overlaying **Fast EMA** (blue, `#2563eb`) and **Slow EMA** (red, `#dc2626`) via `createIndicator('EMA', ...)`
- Symbol search opens the new market in a **new tab**, reverts the current chart
- ENMA watermark (`rgba(255,255,255,0.05)`) rendered at center

---

## 5. What Does NOT Exist Yet (Gaps)

| Feature | Status |
|---|---|
| **Calendar view** (daily PnL heatmap) | ❌ Not implemented |
| **Equity curve / PnL line chart** | ❌ Not implemented (only candlestick + markers) |
| **Result persistence** (DB / localStorage) | ❌ Results lost on page reload |
| **Strategy parameter UI** (fast/slow EMA sliders) | ❌ Hard-coded to `fast=9, slow=21` |
| **Multi-strategy support** | ❌ Only `ema_crossover` wired |
| **Export** (CSV / JSON download) | ❌ Not implemented |
| **Sharpe ratio, Sortino, Calmar** | ❌ Not calculated |

---

## 6. File Map

```
backend/
  main.go                              — HTTP routes, SSE handler, result JSON shape
  internal/backtest/engine.go          — EMA crossover engine, Trade struct, Progress struct

frontend/
  lib/types.ts                         — Trade, Candle, BacktestResponse interfaces
  app/backtest/page.tsx                — State orchestration, SSE reading, result dispatch
  components/backtest/
    BacktestControls.tsx               — Input form (symbol, interval, date range, balance)
    BacktestProgress.tsx               — Live SSE progress overlay
    BacktestChart.tsx                  — klinecharts candlestick + BUY/SELL triangle overlays
    StatsPanel.tsx                     — Derived metrics (win rate, drawdown, avg profit)
    TradesTable.tsx                    — Paginated trade history with cumulative PnL column
  components/charts/
    SimpleChart.tsx                    — Lightweight live chart (klinecharts core + WS)
    ComplexChart.tsx                   — Full pro chart (KLineChartPro + EMA indicators)
```
