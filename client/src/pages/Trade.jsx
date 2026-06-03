import { useCallback, useEffect, useRef, useState } from 'react'
import { createChart, CandlestickSeries } from 'lightweight-charts'
import useBinanceWS from '@/hooks/useBinanceWS'
import {
  useTradeAccount,
  useTradePositions,
  useTradeOpenOrders,
  useTradeSymbolConfig,
  useChangeLeverage,
  useChangeMarginType,
  usePlaceOrder,
  useCancelOrder,
} from '@/hooks/useTrade'

const SYMBOL = 'BTC-USDT'
const BINANCE_SYMBOL = 'BTCUSDT'
const STREAM_PREFIX = BINANCE_SYMBOL.toLowerCase()

const BOTTOM_TABS = ['Positions', 'Open Orders', 'Order History', 'Assets']

// ─── Formatters ──────────────────────────────────────────────────────────────

function fmtPrice(n) {
  return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtQty(n, dp = 4) {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

function fmtPct(n) {
  const v = parseFloat(n)
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}

// ─── TickerBar ────────────────────────────────────────────────────────────────

function TickerBar() {
  const [ticker, setTicker] = useState(null)

  const onTicker = useCallback((data) => {
    setTicker({
      price: parseFloat(data.c),
      changePct: parseFloat(data.P),
      high: parseFloat(data.h),
      low: parseFloat(data.l),
      volume: parseFloat(data.v),
    })
  }, [])

  useBinanceWS(`${STREAM_PREFIX}@ticker`, onTicker)

  const changePct = ticker?.changePct ?? 0
  const isPositive = changePct >= 0

  return (
    <div className="h-14 bg-gray-900 border border-gray-800 rounded flex items-center px-4 gap-8 shrink-0">
      <span className="text-emerald-400 font-bold text-sm tracking-wide">{SYMBOL}</span>
      <div className="flex items-center gap-6 text-xs">
        <div className="flex flex-col">
          <span className="text-gray-500">Last Price</span>
          <span className="text-gray-100 font-semibold">
            {ticker ? fmtPrice(ticker.price) : '$—'}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-gray-500">24h Change</span>
          <span className={isPositive ? 'text-emerald-400 font-semibold' : 'text-red-400 font-semibold'}>
            {ticker ? fmtPct(ticker.changePct) : '—'}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-gray-500">24h High</span>
          <span className="text-gray-100">{ticker ? fmtPrice(ticker.high) : '$—'}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-gray-500">24h Low</span>
          <span className="text-gray-100">{ticker ? fmtPrice(ticker.low) : '$—'}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-gray-500">24h Volume</span>
          <span className="text-gray-100">
            {ticker ? fmtQty(ticker.volume, 0) + ' BTC' : '—'}
          </span>
        </div>
      </div>
    </div>
  )
}

// ─── ChartContainer ───────────────────────────────────────────────────────────

function ChartContainer() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const [chartError, setChartError] = useState(null)

  // Chart init + historical data
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      layout: {
        background: { color: 'rgb(17, 24, 39)' },
        textColor: 'rgb(156, 163, 175)',
      },
      grid: {
        vertLines: { color: 'rgba(31, 41, 55, 0.5)' },
        horzLines: { color: 'rgba(31, 41, 55, 0.5)' },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    })

    chartRef.current = chart
    seriesRef.current = candleSeries

    fetch(`/api/v1/trade/klines?symbol=${SYMBOL}&interval=1m&limit=200`)
      .then((r) => r.json())
      .then((res) => {
        if (!res.success) {
          setChartError(res.error || 'Failed to load candles')
          return
        }
        const raw = res.data
        if (!Array.isArray(raw)) return
        const data = raw.map((k) => ({
          time: Math.floor(k[0] / 1000),
          open: parseFloat(k[1]),
          high: parseFloat(k[2]),
          low: parseFloat(k[3]),
          close: parseFloat(k[4]),
        }))
        candleSeries.setData(data)
        chart.timeScale().fitContent()
      })
      .catch((err) => setChartError(err.message))

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.resize(
          containerRef.current.clientWidth,
          containerRef.current.clientHeight
        )
      }
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
    }
  }, [])

  // Imperative live candle update — bypasses React re-render
  const onKline = useCallback((data) => {
    const k = data.k
    if (seriesRef.current) {
      seriesRef.current.update({
        time: Math.floor(k.t / 1000),
        open: parseFloat(k.o),
        high: parseFloat(k.h),
        low: parseFloat(k.l),
        close: parseFloat(k.c),
      })
    }
  }, [])

  useBinanceWS(`${STREAM_PREFIX}@kline_1m`, onKline)

  return (
    <div className="bg-gray-900 border border-gray-800 rounded relative flex-1 min-h-0 overflow-hidden">
      {chartError && (
        <div className="absolute top-2 left-2 right-2 z-10 bg-red-900/20 text-red-400 p-2 rounded text-sm">
          {chartError}
        </div>
      )}
      <div ref={containerRef} className="w-full h-full" />
    </div>
  )
}

// ─── OrderBook ────────────────────────────────────────────────────────────────

function OrderBook() {
  const [book, setBook] = useState({ asks: [], bids: [] })

  const onDepth = useCallback((data) => {
    const rawAsks = data.asks || data.a || []
    const rawBids = data.bids || data.b || []

    // Top 10 asks ascending (lowest ask first, displayed top-to-bottom reversed)
    const asks = rawAsks.slice(0, 10).map(([price, qty]) => ({
      price: parseFloat(price),
      qty: parseFloat(qty),
    }))
    // Top 10 bids descending (highest bid first)
    const bids = rawBids.slice(0, 10).map(([price, qty]) => ({
      price: parseFloat(price),
      qty: parseFloat(qty),
    }))
    setBook({ asks, bids })
  }, [])

  useBinanceWS(`${STREAM_PREFIX}@depth20@100ms`, onDepth)

  const maxQty = Math.max(
    ...book.asks.map((r) => r.qty),
    ...book.bids.map((r) => r.qty),
    1
  )

  function BookRow({ price, qty, side }) {
    const barPct = Math.min((qty / maxQty) * 100, 100)
    const isAsk = side === 'ask'
    return (
      <div className="relative flex items-center justify-between text-xs py-[2px] px-1">
        <div
          className={`absolute inset-y-0 right-0 opacity-10 ${isAsk ? 'bg-red-500' : 'bg-emerald-500'}`}
          style={{ width: `${barPct}%` }}
        />
        <span className={isAsk ? 'text-red-400 z-10' : 'text-emerald-400 z-10'}>
          {price.toFixed(1)}
        </span>
        <span className="text-gray-400 z-10">{fmtQty(qty, 3)}</span>
      </div>
    )
  }

  const spread =
    book.asks.length && book.bids.length
      ? (book.asks[0].price - book.bids[0].price).toFixed(1)
      : '—'

  return (
    <div className="bg-gray-900 border border-gray-800 rounded flex flex-col min-h-0 flex-1">
      <div className="px-2 py-1.5 border-b border-gray-800 shrink-0">
        <span className="text-xs font-medium text-gray-300">Order Book</span>
      </div>

      <div className="flex justify-between px-2 py-0.5 shrink-0">
        <span className="text-[10px] text-gray-600">Price</span>
        <span className="text-[10px] text-gray-600">Qty</span>
      </div>

      {/* Asks — reversed so lowest ask is closest to spread */}
      <div className="flex flex-col-reverse overflow-hidden shrink-0">
        {book.asks.length === 0
          ? Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-4 mx-1 my-px bg-gray-800 rounded animate-pulse" />
            ))
          : book.asks.slice(0, 8).map((row, i) => (
              <BookRow key={i} price={row.price} qty={row.qty} side="ask" />
            ))}
      </div>

      <div className="flex items-center justify-center py-1 shrink-0">
        <span className="text-xs text-gray-500">Spread: {spread}</span>
      </div>

      {/* Bids */}
      <div className="flex flex-col overflow-hidden shrink-0">
        {book.bids.length === 0
          ? Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-4 mx-1 my-px bg-gray-800 rounded animate-pulse" />
            ))
          : book.bids.slice(0, 8).map((row, i) => (
              <BookRow key={i} price={row.price} qty={row.qty} side="bid" />
            ))}
      </div>
    </div>
  )
}

// ─── RecentTrades ─────────────────────────────────────────────────────────────

const MAX_TRADES = 50

function RecentTrades() {
  const [trades, setTrades] = useState([])

  const onTrade = useCallback((data) => {
    setTrades((prev) => {
      const entry = {
        id: data.t,
        price: parseFloat(data.p),
        qty: parseFloat(data.q),
        time: new Date(data.T).toLocaleTimeString(),
        isBuyerMaker: data.m, // true = seller aggressor (red), false = buyer aggressor (green)
      }
      const next = [entry, ...prev]
      if (next.length > MAX_TRADES) next.length = MAX_TRADES
      return next
    })
  }, [])

  useBinanceWS(`${STREAM_PREFIX}@trade`, onTrade)

  return (
    <div className="bg-gray-900 border border-gray-800 rounded flex flex-col overflow-hidden" style={{ height: '220px' }}>
      <div className="px-2 py-1.5 border-b border-gray-800 shrink-0">
        <span className="text-xs font-medium text-gray-300">Recent Trades</span>
      </div>
      <div className="flex justify-between px-2 py-0.5 shrink-0">
        <span className="text-[10px] text-gray-600">Price</span>
        <span className="text-[10px] text-gray-600">Qty</span>
        <span className="text-[10px] text-gray-600">Time</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {trades.length === 0 ? (
          <div className="flex flex-col gap-1 p-1">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-3 bg-gray-800 rounded animate-pulse mx-1" />
            ))}
          </div>
        ) : (
          trades.map((t) => (
            <div
              key={t.id}
              className="flex justify-between px-2 py-[2px] text-[10px] hover:bg-gray-800/50"
            >
              <span className={t.isBuyerMaker ? 'text-red-400' : 'text-emerald-400'}>
                {t.price.toFixed(1)}
              </span>
              <span className="text-gray-400">{fmtQty(t.qty, 3)}</span>
              <span className="text-gray-600">{t.time}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ─── BottomPanel ──────────────────────────────────────────────────────────────

function SkeletonRow({ cols }) {
  return (
    <tr>
      {cols.map((_, i) => (
        <td key={i} className="py-2 pr-4">
          <div className="h-3 bg-gray-800 rounded w-full animate-pulse" />
        </td>
      ))}
    </tr>
  )
}

function EmptyRow({ message }) {
  return (
    <tr>
      <td colSpan={99} className="py-6 text-center text-gray-600 text-xs">
        {message}
      </td>
    </tr>
  )
}

function PositionsTable({ data, isLoading }) {
  const cols = ['Symbol', 'Side', 'Size', 'Entry Price', 'Mark Price', 'Liq Price', 'Unrealized PnL', '']
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-gray-500 border-b border-gray-800">
          {cols.map((c) => <th key={c} className="text-left py-2 pr-4 font-medium">{c}</th>)}
        </tr>
      </thead>
      <tbody className="text-gray-400">
        {isLoading ? (
          <>
            <SkeletonRow cols={cols} />
            <SkeletonRow cols={cols} />
          </>
        ) : !data?.length ? (
          <EmptyRow message="No open positions" />
        ) : (
          data.map((p) => {
            const size = parseFloat(p.positionAmt)
            const side = size > 0 ? 'Long' : 'Short'
            const pnl = parseFloat(p.unRealizedProfit)
            const isPnlPos = pnl >= 0
            return (
              <tr key={p.symbol} className="border-b border-gray-800/40 hover:bg-gray-800/30">
                <td className="py-1.5 pr-4 text-gray-100">{p.symbol.replace('USDT', '-USDT')}</td>
                <td className={`py-1.5 pr-4 font-medium ${side === 'Long' ? 'text-emerald-400' : 'text-red-400'}`}>{side}</td>
                <td className="py-1.5 pr-4">{Math.abs(size).toFixed(4)}</td>
                <td className="py-1.5 pr-4">{fmtPrice(p.entryPrice)}</td>
                <td className="py-1.5 pr-4">{fmtPrice(p.markPrice)}</td>
                <td className="py-1.5 pr-4">{fmtPrice(p.liquidationPrice)}</td>
                <td className={`py-1.5 pr-4 ${isPnlPos ? 'text-emerald-400' : 'text-red-400'}`}>
                  {isPnlPos ? '+' : ''}{pnl.toFixed(4)} USDT
                </td>
                <td className="py-1.5">
                  <button disabled className="px-2 py-0.5 text-[10px] rounded border border-gray-700 text-gray-600 cursor-not-allowed">
                    Close
                  </button>
                </td>
              </tr>
            )
          })
        )}
      </tbody>
    </table>
  )
}

function OpenOrdersTable({ data, isLoading }) {
  const cols = ['Symbol', 'Type', 'Side', 'Price', 'Qty', 'Filled', 'Status', '']
  const { mutate: execCancel, isPending: cancelPending, variables: cancelVars } = useCancelOrder()

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-gray-500 border-b border-gray-800">
          {cols.map((c) => <th key={c} className="text-left py-2 pr-4 font-medium">{c}</th>)}
        </tr>
      </thead>
      <tbody className="text-gray-400">
        {isLoading ? (
          <>
            <SkeletonRow cols={cols} />
            <SkeletonRow cols={cols} />
          </>
        ) : !data?.length ? (
          <EmptyRow message="No open orders" />
        ) : (
          data.map((o) => {
            const isCancelling = cancelPending && cancelVars?.orderId === o.orderId
            return (
              <tr key={o.orderId} className="border-b border-gray-800/40 hover:bg-gray-800/30">
                <td className="py-1.5 pr-4 text-gray-100">{o.symbol.replace('USDT', '-USDT')}</td>
                <td className="py-1.5 pr-4">{o.type}</td>
                <td className={`py-1.5 pr-4 font-medium ${o.side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>{o.side}</td>
                <td className="py-1.5 pr-4">{fmtPrice(o.price)}</td>
                <td className="py-1.5 pr-4">{fmtQty(o.origQty)}</td>
                <td className="py-1.5 pr-4">{fmtQty(o.executedQty)}</td>
                <td className="py-1.5 pr-4">{o.status}</td>
                <td className="py-1.5">
                  <button
                    disabled={isCancelling}
                    onClick={() => execCancel({ symbol: SYMBOL, orderId: o.orderId })}
                    className={[
                      'px-2 py-0.5 text-[10px] rounded border transition-colors',
                      isCancelling
                        ? 'border-gray-700 text-gray-600 cursor-not-allowed'
                        : 'border-red-700/60 text-red-400 hover:bg-red-500/10 cursor-pointer',
                    ].join(' ')}
                  >
                    {isCancelling ? 'Cancelling…' : 'Cancel'}
                  </button>
                </td>
              </tr>
            )
          })
        )}
      </tbody>
    </table>
  )
}

function AssetsTable({ data, isLoading }) {
  const cols = ['Asset', 'Wallet Balance', 'Available Balance', 'Unrealized PnL']
  const assets = data?.assets?.filter((a) => parseFloat(a.walletBalance) > 0) ?? []
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-gray-500 border-b border-gray-800">
          {cols.map((c) => <th key={c} className="text-left py-2 pr-4 font-medium">{c}</th>)}
        </tr>
      </thead>
      <tbody className="text-gray-400">
        {isLoading ? (
          <>
            <SkeletonRow cols={cols} />
            <SkeletonRow cols={cols} />
          </>
        ) : !assets.length ? (
          <EmptyRow message="No assets" />
        ) : (
          assets.map((a) => {
            const pnl = parseFloat(a.unrealizedProfit)
            return (
              <tr key={a.asset} className="border-b border-gray-800/40 hover:bg-gray-800/30">
                <td className="py-1.5 pr-4 text-gray-100 font-medium">{a.asset}</td>
                <td className="py-1.5 pr-4">{parseFloat(a.walletBalance).toFixed(4)}</td>
                <td className="py-1.5 pr-4">{parseFloat(a.availableBalance).toFixed(4)}</td>
                <td className={`py-1.5 pr-4 ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {pnl >= 0 ? '+' : ''}{pnl.toFixed(4)}
                </td>
              </tr>
            )
          })
        )}
      </tbody>
    </table>
  )
}

function BottomPanel() {
  const [activeTab, setActiveTab] = useState('Positions')

  const { data: positions, isLoading: posLoading } = useTradePositions()
  const { data: openOrders, isLoading: ordLoading } = useTradeOpenOrders()
  const { data: account, isLoading: accLoading } = useTradeAccount()

  return (
    <div className="h-[220px] bg-gray-900 border border-gray-800 rounded flex flex-col shrink-0">
      <div className="flex border-b border-gray-800 shrink-0">
        {BOTTOM_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={[
              'px-4 py-2 text-xs font-medium transition-colors',
              activeTab === tab
                ? 'text-emerald-400 border-b-2 border-emerald-500 -mb-px'
                : 'text-gray-500 hover:text-gray-300',
            ].join(' ')}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-2 min-h-0">
        {activeTab === 'Positions' && (
          <PositionsTable data={positions} isLoading={posLoading} />
        )}
        {activeTab === 'Open Orders' && (
          <OpenOrdersTable data={openOrders} isLoading={ordLoading} />
        )}
        {activeTab === 'Order History' && (
          <p className="text-center text-gray-600 text-xs mt-6">Order history coming soon</p>
        )}
        {activeTab === 'Assets' && (
          <AssetsTable data={account} isLoading={accLoading} />
        )}
      </div>
    </div>
  )
}

// ─── LeverageModal ────────────────────────────────────────────────────────────

function LeverageModal({ current, onConfirm, onClose, isLoading }) {
  const [draft, setDraft] = useState(current ?? 20)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-64 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-gray-100">Adjust Leverage</span>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xs">✕</button>
        </div>

        <div className="flex items-center justify-center">
          <span className="text-3xl font-bold text-yellow-400">{draft}x</span>
        </div>

        <input
          type="range"
          min={1}
          max={125}
          step={1}
          value={draft}
          onChange={(e) => setDraft(Number(e.target.value))}
          className="w-full accent-yellow-400"
        />

        <div className="flex justify-between text-[10px] text-gray-600">
          <span>1x</span>
          <span>25x</span>
          <span>50x</span>
          <span>75x</span>
          <span>125x</span>
        </div>

        <button
          onClick={() => onConfirm(draft)}
          disabled={isLoading}
          className="w-full py-2 rounded text-xs font-semibold bg-yellow-500 hover:bg-yellow-400 text-gray-950 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isLoading ? 'Updating…' : 'Confirm'}
        </button>
      </div>
    </div>
  )
}

// ─── OrderForm ────────────────────────────────────────────────────────────────

function OrderForm() {
  const [orderType, setOrderType] = useState('Limit')
  const [qtyUnit, setQtyUnit] = useState('BTC')
  const [price, setPrice] = useState('')
  const [qty, setQty] = useState('')
  const [pct, setPct] = useState(null)
  const [showLeverageModal, setShowLeverageModal] = useState(false)
  const [formError, setFormError] = useState(null)

  // Live mid-price kept in a ref to avoid re-renders on every tick
  const currentPriceRef = useRef(0)
  const onTicker = useCallback((data) => {
    currentPriceRef.current = parseFloat(data.c) || 0
  }, [])
  useBinanceWS(`${STREAM_PREFIX}@ticker`, onTicker)

  const { data: config, isLoading: configLoading } = useTradeSymbolConfig(SYMBOL)
  const { data: account } = useTradeAccount()

  const activeLeverage = config?.leverage ?? '—'
  const activeMarginType = config?.marginType === 'isolated' ? 'Isolated' : 'Cross'

  // Available USDT balance from the account assets array
  const availableBalance = parseFloat(
    account?.assets?.find((a) => a.asset === 'USDT')?.availableBalance ?? 0
  )

  const { mutate: execChangeLeverage, isPending: leveragePending } = useChangeLeverage()
  const { mutate: execChangeMarginType, isPending: marginPending } = useChangeMarginType()
  const { mutate: execPlaceOrder, isPending: orderPending } = usePlaceOrder()

  const isConfigBusy = configLoading || leveragePending || marginPending

  const PCT_OPTIONS = [25, 50, 75, 100]

  function handleMarginMode(mode) {
    if (isConfigBusy) return
    setFormError(null)
    execChangeMarginType(
      { symbol: SYMBOL, marginType: mode },
      {
        onError: (err) => {
          const detail = err.response?.data?.message || err.response?.data?.detail || err.message
          setFormError(typeof detail === 'string' ? detail : 'Failed to change margin type')
        },
      }
    )
  }

  function handleLeverageConfirm(newLeverage) {
    setFormError(null)
    execChangeLeverage(
      { symbol: SYMBOL, leverage: newLeverage },
      {
        onSuccess: () => setShowLeverageModal(false),
        onError: (err) => {
          const detail = err.response?.data?.message || err.response?.data?.detail || err.message
          setFormError(typeof detail === 'string' ? detail : 'Failed to change leverage')
          setShowLeverageModal(false)
        },
      }
    )
  }

  function handlePctClick(p) {
    setPct(p)
    const leverage = typeof activeLeverage === 'number' ? activeLeverage : 1
    const targetUSDT = availableBalance * leverage * (p / 100)
    if (qtyUnit === 'USDT') {
      setQty(targetUSDT.toFixed(2))
    } else {
      const cp = currentPriceRef.current
      setQty(cp > 0 ? (targetUSDT / cp).toFixed(3) : '')
    }
  }

  function buildOrderPayload(side) {
    const cp = currentPriceRef.current
    let quantity = parseFloat(qty)
    if (isNaN(quantity) || quantity <= 0) return null

    // Convert USDT-denominated input to BTC size
    if (qtyUnit === 'USDT') {
      if (cp <= 0) return null
      quantity = quantity / cp
    }

    const payload = { symbol: SYMBOL, side, type: orderType.toUpperCase(), quantity }
    if (orderType === 'Limit') {
      const p = parseFloat(price)
      if (isNaN(p) || p <= 0) return null
      payload.price = p
    }
    return payload
  }

  function handleSubmit(side) {
    setFormError(null)
    const payload = buildOrderPayload(side)
    if (!payload) {
      setFormError('Enter a valid quantity' + (orderType === 'Limit' ? ' and price' : ''))
      return
    }
    execPlaceOrder(payload, {
      onSuccess: () => {
        setQty('')
        setPrice('')
        setPct(null)
      },
      onError: (err) => {
        const detail = err.response?.data?.message || err.response?.data?.detail || err.message
        setFormError(typeof detail === 'string' ? detail : 'Order failed')
      },
    })
  }

  return (
    <>
      {showLeverageModal && (
        <LeverageModal
          current={typeof activeLeverage === 'number' ? activeLeverage : 20}
          onConfirm={handleLeverageConfirm}
          onClose={() => setShowLeverageModal(false)}
          isLoading={leveragePending}
        />
      )}

      <div className="bg-gray-900 border border-gray-800 rounded p-4 flex flex-col gap-3 overflow-y-auto flex-1 min-h-0">
        {formError && (
          <div className="bg-red-950/20 border border-red-800/40 rounded p-2 text-[10px] text-red-400 leading-snug">
            {formError}
          </div>
        )}

        <div className="flex items-center justify-between">
          <div className={`flex rounded overflow-hidden border text-xs transition-opacity ${isConfigBusy ? 'opacity-50 pointer-events-none' : 'border-gray-700'}`}>
            {['Cross', 'Isolated'].map((mode) => (
              <button
                key={mode}
                onClick={() => handleMarginMode(mode)}
                disabled={marginPending}
                className={[
                  'px-3 py-1.5 transition-colors',
                  activeMarginType === mode
                    ? 'bg-gray-700 text-gray-100'
                    : 'text-gray-500 hover:text-gray-300',
                ].join(' ')}
              >
                {marginPending && activeMarginType !== mode ? '…' : mode}
              </button>
            ))}
          </div>

          <button
            onClick={() => { setFormError(null); setShowLeverageModal(true) }}
            disabled={isConfigBusy}
            className="text-xs text-yellow-400 border border-yellow-600/40 rounded px-2 py-1 hover:bg-yellow-500/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {leveragePending ? '…' : `${activeLeverage}x`}
          </button>
        </div>

        <div className="flex gap-2 border-b border-gray-800 pb-1">
          {['Limit', 'Market'].map((type) => (
            <button
              key={type}
              onClick={() => { setOrderType(type); setPrice('') }}
              className={[
                'text-xs pb-1 transition-colors',
                orderType === type
                  ? 'text-gray-100 border-b-2 border-emerald-500 -mb-[5px]'
                  : 'text-gray-500 hover:text-gray-300',
              ].join(' ')}
            >
              {type}
            </button>
          ))}
        </div>

        {orderType === 'Limit' && (
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Price (USDT)</label>
            <input
              type="number"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="0.00"
              disabled={orderPending}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-xs text-gray-100 placeholder-gray-600 focus:outline-none focus:border-emerald-600 disabled:opacity-50"
            />
          </div>
        )}

        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500">Quantity</label>
          <div className="flex border border-gray-700 rounded overflow-hidden">
            <input
              type="number"
              value={qty}
              onChange={(e) => { setQty(e.target.value); setPct(null) }}
              placeholder="0.000"
              disabled={orderPending}
              className="flex-1 bg-gray-800 px-3 py-2 text-xs text-gray-100 placeholder-gray-600 focus:outline-none min-w-0 disabled:opacity-50"
            />
            <div className="flex shrink-0">
              {['BTC', 'USDT'].map((unit) => (
                <button
                  key={unit}
                  onClick={() => { setQtyUnit(unit); setQty(''); setPct(null) }}
                  disabled={orderPending}
                  className={[
                    'px-2 text-xs transition-colors',
                    qtyUnit === unit
                      ? 'bg-gray-700 text-gray-100'
                      : 'bg-gray-800 text-gray-500 hover:text-gray-300',
                  ].join(' ')}
                >
                  {unit}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex gap-1">
          {PCT_OPTIONS.map((p) => (
            <button
              key={p}
              onClick={() => handlePctClick(p)}
              disabled={orderPending}
              className={[
                'flex-1 py-1 text-xs rounded transition-colors border',
                pct === p
                  ? 'bg-emerald-600/20 border-emerald-600 text-emerald-400'
                  : 'border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-600',
              ].join(' ')}
            >
              {p}%
            </button>
          ))}
        </div>

        <p className="text-xs text-gray-600">
          Available: ${availableBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT
        </p>

        <button
          onClick={() => handleSubmit('BUY')}
          disabled={orderPending}
          className="w-full py-2.5 rounded text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
        >
          {orderPending ? (
            <>
              <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Placing…
            </>
          ) : 'Buy / Long'}
        </button>
        <button
          onClick={() => handleSubmit('SELL')}
          disabled={orderPending}
          className="w-full py-2.5 rounded text-xs font-semibold bg-red-600 hover:bg-red-500 text-white transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
        >
          {orderPending ? (
            <>
              <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Placing…
            </>
          ) : 'Sell / Short'}
        </button>
      </div>
    </>
  )
}

// ─── Trade (root) ─────────────────────────────────────────────────────────────

export default function Trade() {
  return (
    <div className="bg-gray-950 text-gray-100 flex flex-col p-2 gap-2 h-[calc(100vh-56px)] overflow-hidden mt-14">
      <TickerBar />

      <div className="grid grid-cols-12 gap-2 flex-1 min-h-0">
        {/* Left — chart + bottom panel */}
        <div className="col-span-8 flex flex-col gap-2 min-h-0">
          <ChartContainer />
          <BottomPanel />
        </div>

        {/* Middle — order book + recent trades */}
        <div className="col-span-2 flex flex-col gap-2 min-h-0">
          <OrderBook />
          <RecentTrades />
        </div>

        {/* Right — order form */}
        <div className="col-span-2 flex flex-col gap-2 min-h-0">
          <OrderForm />
        </div>
      </div>
    </div>
  )
}
