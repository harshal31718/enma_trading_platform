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
  useClosePosition,
} from '@/hooks/useTrade'

const SYMBOL = 'BTC-USDT'
const BINANCE_SYMBOL = 'BTCUSDT'
const STREAM_PREFIX = BINANCE_SYMBOL.toLowerCase()

const BOTTOM_TABS = ['Positions', 'Open Orders', 'Order History', 'Assets']

// ─── Formatters ──────────────────────────────────────────────────────────────

function fmtPrice(n) {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
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
      quoteVolume: parseFloat(data.q),
    })
  }, [])

  useBinanceWS(`${STREAM_PREFIX}@ticker`, onTicker)

  const changePct = ticker?.changePct ?? 0
  const isPositive = changePct >= 0

  return (
    <div className="h-12 bg-gray-900 border-b border-gray-800 flex items-center px-4 gap-6 shrink-0">
      <div className="flex items-center gap-3 shrink-0">
        <span className="text-gray-100 font-bold text-sm">{SYMBOL}</span>
        <span className="text-[10px] text-gray-500 border border-gray-700 px-1.5 py-0.5 rounded">Perp</span>
      </div>

      <div className="flex items-center gap-1 shrink-0">
        <span className={`text-xl font-bold tabular-nums ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
          {ticker ? fmtPrice(ticker.price) : '—'}
        </span>
        <span className={`text-xs ml-1 ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
          {ticker ? fmtPct(ticker.changePct) : ''}
        </span>
      </div>

      <div className="h-6 w-px bg-gray-800 shrink-0" />

      <div className="flex items-center gap-6 text-xs overflow-x-auto">
        {[
          { label: '24h High', value: ticker ? fmtPrice(ticker.high) : '—' },
          { label: '24h Low', value: ticker ? fmtPrice(ticker.low) : '—' },
          { label: '24h Vol(BTC)', value: ticker ? fmtQty(ticker.volume, 0) : '—' },
          { label: '24h Vol(USDT)', value: ticker ? fmtQty(ticker.quoteVolume, 0) : '—' },
        ].map(({ label, value }) => (
          <div key={label} className="flex flex-col shrink-0">
            <span className="text-gray-500 text-[10px]">{label}</span>
            <span className="text-gray-200 tabular-nums">{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── ChartContainer ───────────────────────────────────────────────────────────

const TIMEFRAMES = [
  { label: '1m', interval: '1m' },
  { label: '5m', interval: '5m' },
  { label: '15m', interval: '15m' },
  { label: '1h', interval: '1h' },
  { label: '4h', interval: '4h' },
  { label: '1d', interval: '1d' },
]

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:5000'

function fetchKlines(symbol, timeframe, series, chart, signal) {
  return fetch(
    `${API_BASE}/api/v1/trade/klines?symbol=${symbol}&interval=${timeframe}&limit=500`,
    { signal }
  )
    .then((r) => r.json())
    .then((res) => {
      if (!res.success) throw new Error(res.error || 'Failed to load candles')
      const raw = res.data
      if (!Array.isArray(raw)) return
      const data = raw.map((k) => ({
        time: Math.floor(k[0] / 1000),
        open: parseFloat(k[1]),
        high: parseFloat(k[2]),
        low: parseFloat(k[3]),
        close: parseFloat(k[4]),
      }))
      series.setData(data)
      chart.timeScale().fitContent()
    })
}

function ChartContainer() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const fetchingRef = useRef(false)
  const [chartError, setChartError] = useState(null)
  const [timeframe, setTimeframe] = useState('1m')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: 'rgb(17, 24, 39)' },
        textColor: 'rgb(156, 163, 175)',
      },
      grid: {
        vertLines: { color: 'rgba(31, 41, 55, 0.4)' },
        horzLines: { color: 'rgba(31, 41, 55, 0.4)' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: 'rgba(31, 41, 55, 0.8)' },
      timeScale: {
        borderColor: 'rgba(31, 41, 55, 0.8)',
        timeVisible: true,
        secondsVisible: false,
      },
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

    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current) return
    const ac = new AbortController()
    setChartError(null)
    setLoading(true)
    fetchingRef.current = true

    fetchKlines(SYMBOL, timeframe, seriesRef.current, chartRef.current, ac.signal)
      .catch((err) => { if (err.name !== 'AbortError') setChartError(err.message) })
      .finally(() => {
        fetchingRef.current = false
        setLoading(false)
      })

    return () => {
      ac.abort()
      fetchingRef.current = false
    }
  }, [timeframe])

  const onKline = useCallback((data) => {
    if (fetchingRef.current) return
    const k = data.k
    if (!seriesRef.current || !k) return
    seriesRef.current.update({
      time: Math.floor(k.t / 1000),
      open: parseFloat(k.o),
      high: parseFloat(k.h),
      low: parseFloat(k.l),
      close: parseFloat(k.c),
    })
  }, [])

  useBinanceWS(`${STREAM_PREFIX}@kline_${timeframe}`, onKline)

  return (
    <div className="bg-gray-900 relative flex-1 min-h-0 overflow-hidden flex flex-col">
      {/* Timeframe toolbar */}
      <div className="flex items-center gap-0.5 px-3 py-1.5 border-b border-gray-800 shrink-0">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf.interval}
            onClick={() => setTimeframe(tf.interval)}
            className={[
              'px-3 py-1 text-xs rounded transition-colors font-medium',
              timeframe === tf.interval
                ? 'bg-gray-700 text-gray-100'
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800',
            ].join(' ')}
          >
            {tf.label}
          </button>
        ))}
        {loading && (
          <span className="ml-2 inline-block w-3 h-3 border-2 border-gray-600 border-t-emerald-400 rounded-full animate-spin" />
        )}
      </div>

      {chartError && (
        <div className="absolute top-12 left-2 right-2 z-10 bg-red-900/20 text-red-400 p-2 rounded text-xs">
          {chartError}
        </div>
      )}

      <div ref={containerRef} className="flex-1 min-h-0" />
    </div>
  )
}

// ─── OrderBook ────────────────────────────────────────────────────────────────

const BOOK_ROWS = 14

function OrderBook() {
  const [book, setBook] = useState({ asks: [], bids: [] })

  const onDepth = useCallback((data) => {
    const rawAsks = data.asks || data.a || []
    const rawBids = data.bids || data.b || []

    const asks = rawAsks.slice(0, BOOK_ROWS).map(([price, qty]) => ({
      price: parseFloat(price),
      qty: parseFloat(qty),
    }))
    const bids = rawBids.slice(0, BOOK_ROWS).map(([price, qty]) => ({
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

  const spread =
    book.asks.length && book.bids.length
      ? (book.asks[0].price - book.bids[0].price).toFixed(1)
      : '—'

  const bestAsk = book.asks[0]?.price ?? 0
  const bestBid = book.bids[0]?.price ?? 0
  const midPrice = bestAsk && bestBid ? ((bestAsk + bestBid) / 2).toFixed(1) : '—'

  function BookRow({ price, qty, side }) {
    const barPct = Math.min((qty / maxQty) * 100, 100)
    const isAsk = side === 'ask'
    return (
      <div className="relative flex items-center justify-between text-[11px] py-[3px] px-2 hover:bg-gray-800/60 cursor-default">
        <div
          className={`absolute inset-y-0 right-0 opacity-[0.12] ${isAsk ? 'bg-red-500' : 'bg-emerald-500'}`}
          style={{ width: `${barPct}%` }}
        />
        <span className={`tabular-nums z-10 ${isAsk ? 'text-red-400' : 'text-emerald-400'}`}>
          {price.toFixed(1)}
        </span>
        <span className="text-gray-400 tabular-nums z-10">{qty.toFixed(3)}</span>
      </div>
    )
  }

  return (
    <div className="bg-gray-900 border-r border-gray-800 flex flex-col min-h-0 flex-1">
      <div className="px-3 py-2 border-b border-gray-800 shrink-0">
        <span className="text-xs font-semibold text-gray-200">Order Book</span>
      </div>

      <div className="flex justify-between px-2 py-1 shrink-0">
        <span className="text-[10px] text-gray-600">Price (USDT)</span>
        <span className="text-[10px] text-gray-600">Size (BTC)</span>
      </div>

      {/* Asks reversed — lowest ask closest to spread */}
      <div className="flex flex-col-reverse flex-1 min-h-0 overflow-hidden">
        {book.asks.length === 0
          ? Array.from({ length: BOOK_ROWS }).map((_, i) => (
              <div key={i} className="h-[22px] mx-2 my-px bg-gray-800/60 rounded animate-pulse" />
            ))
          : book.asks.slice(0, BOOK_ROWS).map((row, i) => (
              <BookRow key={i} price={row.price} qty={row.qty} side="ask" />
            ))}
      </div>

      {/* Mid price / spread row */}
      <div className="flex items-center justify-between px-2 py-1.5 border-y border-gray-800 shrink-0">
        <span className="text-sm font-bold text-gray-100 tabular-nums">{midPrice}</span>
        <span className="text-[10px] text-gray-500">Spread: {spread}</span>
      </div>

      {/* Bids */}
      <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
        {book.bids.length === 0
          ? Array.from({ length: BOOK_ROWS }).map((_, i) => (
              <div key={i} className="h-[22px] mx-2 my-px bg-gray-800/60 rounded animate-pulse" />
            ))
          : book.bids.slice(0, BOOK_ROWS).map((row, i) => (
              <BookRow key={i} price={row.price} qty={row.qty} side="bid" />
            ))}
      </div>
    </div>
  )
}

// ─── RecentTrades ─────────────────────────────────────────────────────────────

const MAX_TRADES = 60

function RecentTrades() {
  const [trades, setTrades] = useState([])

  const onTrade = useCallback((data) => {
    setTrades((prev) => {
      const entry = {
        id: data.a,
        price: parseFloat(data.p),
        qty: parseFloat(data.q),
        time: new Date(data.T).toLocaleTimeString('en-US', { hour12: false }),
        isBuyerMaker: data.m,
      }
      const next = [entry, ...prev]
      if (next.length > MAX_TRADES) next.length = MAX_TRADES
      return next
    })
  }, [])

  useBinanceWS(`${STREAM_PREFIX}@aggTrade`, onTrade)

  return (
    <div className="bg-gray-900 border-r border-gray-800 flex flex-col min-h-0" style={{ height: '240px' }}>
      <div className="px-3 py-2 border-b border-gray-800 shrink-0">
        <span className="text-xs font-semibold text-gray-200">Trades</span>
      </div>
      <div className="flex justify-between px-2 py-1 shrink-0">
        <span className="text-[10px] text-gray-600">Price (USDT)</span>
        <span className="text-[10px] text-gray-600">Amount (BTC)</span>
        <span className="text-[10px] text-gray-600">Time</span>
      </div>
      <div className="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
        {trades.length === 0 ? (
          <div className="flex flex-col gap-1 p-2">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-3 bg-gray-800/60 rounded animate-pulse" />
            ))}
          </div>
        ) : (
          trades.map((t) => (
            <div
              key={t.id}
              className="flex justify-between px-2 py-[2px] text-[11px] hover:bg-gray-800/40"
            >
              <span className={`tabular-nums ${t.isBuyerMaker ? 'text-red-400' : 'text-emerald-400'}`}>
                {t.price.toFixed(1)}
              </span>
              <span className="text-gray-400 tabular-nums">{t.qty.toFixed(3)}</span>
              <span className="text-gray-600 tabular-nums">{t.time}</span>
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
      <td colSpan={99} className="py-8 text-center text-gray-600 text-xs">
        {message}
      </td>
    </tr>
  )
}

function PositionsTable({ data, isLoading }) {
  const cols = ['Symbol', 'Size', 'Entry Price', 'Mark Price', 'Liq Price', 'Margin Ratio', 'Unrealized PnL', '']
  const [closeError, setCloseError] = useState(null)
  const { mutate: execClose, isPending: closePending, variables: closeVars } = useClosePosition()

  function handleClose(symbol) {
    setCloseError(null)
    execClose(
      { symbol },
      {
        onError: (err) => {
          const detail =
            err.response?.data?.error?.message ||
            err.response?.data?.message ||
            err.response?.data?.detail ||
            err.message
          setCloseError(typeof detail === 'string' ? detail : 'Failed to close position')
        },
      }
    )
  }

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-gray-500 border-b border-gray-800">
          {cols.map((c) => <th key={c} className="text-left py-2 pr-6 font-medium whitespace-nowrap">{c}</th>)}
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
          <>
            {closeError && (
              <tr>
                <td colSpan={cols.length} className="py-1">
                  <div className="bg-red-950/20 border border-red-800/40 rounded px-3 py-1.5 text-[10px] text-red-400">
                    {closeError}
                  </div>
                </td>
              </tr>
            )}
            {data.map((p) => {
              const size = parseFloat(p.positionAmt)
              const side = size > 0 ? 'Long' : 'Short'
              const pnl = parseFloat(p.unRealizedProfit)
              const isPnlPos = pnl >= 0
              const isClosing = closePending && closeVars?.symbol === p.symbol
              const marginRatio = p.marginRatio ? (parseFloat(p.marginRatio) * 100).toFixed(2) + '%' : '—'
              return (
                <tr key={p.symbol} className="border-b border-gray-800/30 hover:bg-gray-800/20">
                  <td className="py-2 pr-6 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <span className="text-gray-100">{p.symbol.replace('USDT', '-USDT')}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${side === 'Long' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>{side}</span>
                    </div>
                  </td>
                  <td className="py-2 pr-6 tabular-nums">{Math.abs(size).toFixed(4)}</td>
                  <td className="py-2 pr-6 tabular-nums">{fmtPrice(p.entryPrice)}</td>
                  <td className="py-2 pr-6 tabular-nums">{fmtPrice(p.markPrice)}</td>
                  <td className="py-2 pr-6 tabular-nums">{fmtPrice(p.liquidationPrice)}</td>
                  <td className="py-2 pr-6 tabular-nums">{marginRatio}</td>
                  <td className={`py-2 pr-6 tabular-nums font-medium ${isPnlPos ? 'text-emerald-400' : 'text-red-400'}`}>
                    {isPnlPos ? '+' : ''}{pnl.toFixed(4)} USDT
                  </td>
                  <td className="py-2">
                    <button
                      disabled={isClosing}
                      onClick={() => handleClose(p.symbol)}
                      className={[
                        'px-3 py-1 text-[10px] rounded border transition-colors whitespace-nowrap',
                        isClosing
                          ? 'border-gray-700 text-gray-600 cursor-not-allowed'
                          : 'border-gray-600 text-gray-300 hover:bg-gray-700/50 cursor-pointer',
                      ].join(' ')}
                    >
                      {isClosing ? 'Closing…' : 'Close Position'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </>
        )}
      </tbody>
    </table>
  )
}

function OpenOrdersTable({ data, isLoading }) {
  const cols = ['Symbol', 'Type', 'Side', 'Price', 'Amount', 'Filled', 'Status', '']
  const { mutate: execCancel, isPending: cancelPending, variables: cancelVars } = useCancelOrder()

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-gray-500 border-b border-gray-800">
          {cols.map((c) => <th key={c} className="text-left py-2 pr-6 font-medium whitespace-nowrap">{c}</th>)}
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
              <tr key={o.orderId} className="border-b border-gray-800/30 hover:bg-gray-800/20">
                <td className="py-2 pr-6 text-gray-100 whitespace-nowrap">{o.symbol.replace('USDT', '-USDT')}</td>
                <td className="py-2 pr-6">{o.type}</td>
                <td className={`py-2 pr-6 font-medium ${o.side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>{o.side}</td>
                <td className="py-2 pr-6 tabular-nums">{fmtPrice(o.price)}</td>
                <td className="py-2 pr-6 tabular-nums">{fmtQty(o.origQty)}</td>
                <td className="py-2 pr-6 tabular-nums">{fmtQty(o.executedQty)}</td>
                <td className="py-2 pr-6">{o.status}</td>
                <td className="py-2">
                  <button
                    disabled={isCancelling}
                    onClick={() => execCancel({ symbol: SYMBOL, orderId: o.orderId })}
                    className={[
                      'px-3 py-1 text-[10px] rounded border transition-colors',
                      isCancelling
                        ? 'border-gray-700 text-gray-600 cursor-not-allowed'
                        : 'border-gray-600 text-gray-400 hover:bg-gray-700/50 cursor-pointer',
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
          {cols.map((c) => <th key={c} className="text-left py-2 pr-6 font-medium">{c}</th>)}
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
              <tr key={a.asset} className="border-b border-gray-800/30 hover:bg-gray-800/20">
                <td className="py-2 pr-6 text-gray-100 font-medium">{a.asset}</td>
                <td className="py-2 pr-6 tabular-nums">{parseFloat(a.walletBalance).toFixed(4)}</td>
                <td className="py-2 pr-6 tabular-nums">{parseFloat(a.availableBalance).toFixed(4)}</td>
                <td className={`py-2 pr-6 tabular-nums ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
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

  const posCount = positions?.length ?? 0
  const ordCount = openOrders?.length ?? 0

  return (
    <div className="bg-gray-900 border-t border-gray-800 flex flex-col shrink-0" style={{ height: '200px' }}>
      <div className="flex border-b border-gray-800 shrink-0">
        {[
          { key: 'Positions', label: `Positions(${posCount})` },
          { key: 'Open Orders', label: `Open Orders(${ordCount})` },
          { key: 'Order History', label: 'Order History' },
          { key: 'Assets', label: 'Assets' },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={[
              'px-4 py-2 text-xs font-medium transition-colors whitespace-nowrap',
              activeTab === key
                ? 'text-gray-100 border-b-2 border-emerald-500 -mb-px'
                : 'text-gray-500 hover:text-gray-300',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto px-2 min-h-0">
        {activeTab === 'Positions' && (
          <PositionsTable data={positions} isLoading={posLoading} />
        )}
        {activeTab === 'Open Orders' && (
          <OpenOrdersTable data={openOrders} isLoading={ordLoading} />
        )}
        {activeTab === 'Order History' && (
          <p className="text-center text-gray-600 text-xs mt-8">Order history coming soon</p>
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
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-72 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-gray-100">Adjust Leverage</span>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-sm leading-none">✕</button>
        </div>

        <div className="flex items-center justify-center">
          <span className="text-4xl font-bold text-yellow-400">{draft}x</span>
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
          className="w-full py-2.5 rounded text-xs font-semibold bg-yellow-500 hover:bg-yellow-400 text-gray-950 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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

  const currentPriceRef = useRef(0)
  const onTicker = useCallback((data) => {
    currentPriceRef.current = parseFloat(data.c) || 0
  }, [])
  useBinanceWS(`${STREAM_PREFIX}@ticker`, onTicker)

  const { data: config, isLoading: configLoading } = useTradeSymbolConfig(SYMBOL)
  const { data: account } = useTradeAccount()

  const activeLeverage = config?.leverage ?? '—'

  const availableBalance = parseFloat(
    account?.assets?.find((a) => a.asset === 'USDT')?.availableBalance ?? 0
  )

  const { mutate: execChangeLeverage, isPending: leveragePending } = useChangeLeverage()
  const { mutate: execChangeMarginType, isPending: marginPending } = useChangeMarginType()
  const { mutate: execPlaceOrder, isPending: orderPending } = usePlaceOrder()

  const isConfigBusy = configLoading || leveragePending || marginPending

  const PCT_OPTIONS = [25, 50, 75, 100]

  useEffect(() => {
    if (config?.marginType && config.marginType !== 'isolated' && !marginPending) {
      execChangeMarginType({ symbol: SYMBOL, marginType: 'ISOLATED' })
    }
  }, [config?.marginType, marginPending, execChangeMarginType])

  function handleLeverageConfirm(newLeverage) {
    setFormError(null)
    execChangeLeverage(
      { symbol: SYMBOL, leverage: newLeverage },
      {
        onSuccess: () => setShowLeverageModal(false),
        onError: (err) => {
          const detail =
            err.response?.data?.error?.message ||
            err.response?.data?.message ||
            err.response?.data?.detail ||
            err.message
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
        const detail =
          err.response?.data?.error?.message ||
          err.response?.data?.message ||
          err.response?.data?.detail ||
          err.message
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

      <div className="flex flex-col min-h-0 flex-1 bg-gray-900">
        {/* Margin type + Leverage row */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
          <div className={`flex rounded overflow-hidden border text-xs ${isConfigBusy ? 'opacity-50' : 'border-gray-700'}`}>
            <span className="px-3 py-1.5 bg-gray-800 text-gray-300 text-xs font-medium">
              {marginPending ? '…' : 'Isolated'}
            </span>
          </div>
          <button
            onClick={() => { setFormError(null); setShowLeverageModal(true) }}
            disabled={isConfigBusy}
            className="text-xs text-yellow-400 border border-yellow-600/40 rounded px-2.5 py-1.5 hover:bg-yellow-500/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
          >
            {leveragePending ? '…' : `${activeLeverage}x`}
          </button>
        </div>

        {/* Order type tabs */}
        <div className="flex border-b border-gray-800 px-3">
          {['Limit', 'Market'].map((type) => (
            <button
              key={type}
              onClick={() => { setOrderType(type); setPrice('') }}
              className={[
                'py-2 px-2 mr-2 text-xs font-medium transition-colors',
                orderType === type
                  ? 'text-gray-100 border-b-2 border-emerald-500 -mb-px'
                  : 'text-gray-500 hover:text-gray-300',
              ].join(' ')}
            >
              {type}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-3 p-3 overflow-y-auto flex-1 min-h-0">
          {formError && (
            <div className="bg-red-950/20 border border-red-800/40 rounded px-3 py-2 text-[10px] text-red-400 leading-snug">
              {formError}
            </div>
          )}

          {/* Available */}
          <div className="flex justify-between text-[11px]">
            <span className="text-gray-500">Available</span>
            <span className="text-gray-300 tabular-nums">
              {availableBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT
            </span>
          </div>

          {/* Price — only for Limit */}
          {orderType === 'Limit' && (
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-gray-500">Price (USDT)</label>
              <input
                type="number"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="0.00"
                disabled={orderPending}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-xs text-gray-100 placeholder-gray-600 focus:outline-none focus:border-gray-600 disabled:opacity-50 tabular-nums"
              />
            </div>
          )}

          {/* Quantity */}
          <div className="flex flex-col gap-1">
            <label className="text-[11px] text-gray-500">Size</label>
            <div className="flex border border-gray-700 rounded overflow-hidden">
              <input
                type="number"
                value={qty}
                onChange={(e) => { setQty(e.target.value); setPct(null) }}
                placeholder="0.000"
                disabled={orderPending}
                className="flex-1 bg-gray-800 px-3 py-2 text-xs text-gray-100 placeholder-gray-600 focus:outline-none min-w-0 disabled:opacity-50 tabular-nums"
              />
              <div className="flex shrink-0 border-l border-gray-700">
                {['BTC', 'USDT'].map((unit) => (
                  <button
                    key={unit}
                    onClick={() => { setQtyUnit(unit); setQty(''); setPct(null) }}
                    disabled={orderPending}
                    className={[
                      'px-2.5 text-xs transition-colors font-medium',
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

          {/* Pct buttons */}
          <div className="flex gap-1">
            {PCT_OPTIONS.map((p) => (
              <button
                key={p}
                onClick={() => handlePctClick(p)}
                disabled={orderPending}
                className={[
                  'flex-1 py-1.5 text-xs rounded transition-colors border',
                  pct === p
                    ? 'bg-gray-700 border-gray-600 text-gray-100'
                    : 'border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-600',
                ].join(' ')}
              >
                {p}%
              </button>
            ))}
          </div>

          {/* Buy / Sell buttons side by side */}
          <div className="flex gap-2 mt-1">
            <button
              onClick={() => handleSubmit('BUY')}
              disabled={orderPending}
              className="flex-1 py-3 rounded text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
            >
              {orderPending ? (
                <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : 'Buy/Long'}
            </button>
            <button
              onClick={() => handleSubmit('SELL')}
              disabled={orderPending}
              className="flex-1 py-3 rounded text-xs font-semibold bg-red-600 hover:bg-red-500 text-white transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
            >
              {orderPending ? (
                <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : 'Sell/Short'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

// ─── Trade (root) ─────────────────────────────────────────────────────────────

export default function Trade() {
  return (
    <div className="bg-gray-950 text-gray-100 flex flex-col h-[calc(100vh-56px)] overflow-hidden mt-14">
      <TickerBar />

      {/* Main content — fills remaining height */}
      <div className="flex flex-1 min-h-0">

        {/* Left col — chart + bottom panel (fills remaining width) */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0 border-r border-gray-800">
          <ChartContainer />
          <BottomPanel />
        </div>

        {/* Middle col — order book + recent trades, fixed width */}
        <div className="flex flex-col min-h-0 shrink-0" style={{ width: '200px' }}>
          <OrderBook />
          <RecentTrades />
        </div>

        {/* Right col — order form, fixed width */}
        <div className="flex flex-col min-h-0 shrink-0" style={{ width: '260px' }}>
          <OrderForm />
        </div>

      </div>
    </div>
  )
}
