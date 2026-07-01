import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import ErrorBoundary from '@/components/ErrorBoundary'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import api from '@/lib/axios'
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
  usePlaceOCOOrder,
  useCancelAllOrders,
  useTradeOrders,
  useTradeExecutions,
  useTradeTransactions,
} from '@/hooks/useTrade'
import useOcoMonitor from '@/hooks/useOcoMonitor'
import { SymbolProvider, useCurrentSymbol } from '@/context/SymbolContext'
import SymbolSearchBar from '@/components/SymbolSearchBar'
import { SYMBOL_LIMITS } from '@/utils/symbolLimits'
import { useSymbols } from '@/hooks/useCandles'
import { formatDateTime } from '@/utils/formatters'

const BOTTOM_TABS = ['Positions', 'Open Orders', 'Order History', 'Trade History', 'Transaction History', 'Assets']

// ─── Formatters ──────────────────────────────────────────────────────────────

function fmtPrice(n) {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtPriceForSymbol(n, symbol) {
  const limits = SYMBOL_LIMITS[symbol]
  const dp = limits ? getPrecisionDecimalPlaces(limits.tickSize) : 2
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

function fmtQtyForSymbol(n, symbol) {
  const limits = SYMBOL_LIMITS[symbol]
  const dp = limits ? getPrecisionDecimalPlaces(limits.stepSize) : 4
  return Number(n).toFixed(Math.max(dp, 0))
}

function fmtQty(n, dp = 4) {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

function getPrecisionDecimalPlaces(step) {
  if (!step) return 4
  const stepStr = step.toString()
  if (stepStr.includes('e-')) {
    const parts = stepStr.split('e-')
    return parseInt(parts[1], 10)
  }
  if (stepStr.includes('.')) {
    return stepStr.split('.')[1].length
  }
  return 0
}

function roundToStep(value, step) {
  const decimals = getPrecisionDecimalPlaces(step)
  const factor = Math.pow(10, decimals)
  return Math.floor(value * factor) / factor
}

function fmtPct(n) {
  const v = parseFloat(n)
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}

// ─── TickerBar ────────────────────────────────────────────────────────────────

function TickerBar() {
  const { streamPrefix, base, quote } = useCurrentSymbol()
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

  useBinanceWS(`${streamPrefix}@ticker`, onTicker)

  const changePct = ticker?.changePct ?? 0
  const isPositive = changePct >= 0

  return (
    <div className="h-12 bg-title-bg title-fade border-b border-slate-700/50 flex items-center pl-2 pr-4 gap-6 shrink-0">
      <div className="flex items-center gap-2 shrink-0">
        <SymbolSearchBar />
        <span className="text-[10px] text-slate-400 border border-slate-700/50 px-1.5 py-0.5 rounded">Perp</span>
      </div>

      <div className="flex items-center gap-1 shrink-0">
        <span className={`text-xl font-bold tabular-nums ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
          {ticker ? fmtPrice(ticker.price) : '—'}
        </span>
        <span className={`text-xs ml-1 ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
          {ticker ? fmtPct(ticker.changePct) : ''}
        </span>
      </div>

      <div className="h-6 w-px bg-slate-700/50 shrink-0" />

      <div className="flex items-center gap-6 text-xs overflow-x-auto">
        {[
          { label: '24h High', value: ticker ? fmtPrice(ticker.high) : '—' },
          { label: '24h Low', value: ticker ? fmtPrice(ticker.low) : '—' },
          { label: `24h Vol(${base})`, value: ticker ? fmtQty(ticker.volume, 0) : '—' },
          { label: `24h Vol(${quote})`, value: ticker ? fmtQty(ticker.quoteVolume, 0) : '—' },
        ].map(({ label, value }) => (
          <div key={label} className="flex flex-col shrink-0">
            <span className="text-slate-400 text-[10px]">{label}</span>
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

function fetchKlines(symbol, timeframe, series, chart, signal) {
  return api
    .get('/api/v1/trade/klines', { params: { symbol, interval: timeframe, limit: 500 }, signal })
    .then((res) => {
      if (!res.data.success) throw new Error(res.data.error?.message || 'Failed to load candles')
      const raw = res.data.data
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

function ChartContainer({ timeframe, setTimeframe }) {
  const { symbol, streamPrefix } = useCurrentSymbol()
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const fetchingRef = useRef(false)
  const [chartError, setChartError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: '#0d1117' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.4)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.4)' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: 'rgba(30, 41, 59, 0.8)' },
      timeScale: {
        borderColor: 'rgba(30, 41, 59, 0.8)',
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

    if (seriesRef.current) seriesRef.current.setData([])
    fetchKlines(symbol, timeframe, seriesRef.current, chartRef.current, ac.signal)
      .catch((err) => { if (err.name !== 'AbortError') setChartError(err.message) })
      .finally(() => {
        fetchingRef.current = false
        setLoading(false)
      })

    return () => {
      ac.abort()
      fetchingRef.current = false
    }
  }, [timeframe, symbol])

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

  useBinanceWS(`${streamPrefix}@kline_${timeframe}`, onKline)

  return (
    <div className="bg-title-bg relative flex-1 min-h-0 overflow-hidden flex flex-col">
      {loading && (
        <div className="absolute top-2 left-3 z-10 flex items-center gap-1.5 pointer-events-none">
          <span className="inline-block w-3 h-3 border-2 border-slate-600 border-t-emerald-400 rounded-full animate-spin" />
        </div>
      )}

      {chartError && (
        <div className="absolute top-2 left-2 right-2 z-10 bg-red-900/20 text-red-400 p-2 rounded text-xs">
          {chartError}
        </div>
      )}

      <div ref={containerRef} className="flex-1 min-h-0" />

      {/* Timeframe buttons — absolute overlay, aligned with TradingView logo */}
      <div className="absolute bottom-8 left-12 z-10 flex items-center gap-0.5">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf.interval}
            onClick={() => setTimeframe(tf.interval)}
            className={[
              'px-2.5 py-1 text-xs rounded transition-colors font-medium',
              timeframe === tf.interval
                ? 'border border-yellow-500/70 bg-[#0d1117] text-yellow-400'
                : 'text-slate-400 hover:text-yellow-400 bg-transparent border border-transparent',
            ].join(' ')}
          >
            {tf.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── OrderBook ────────────────────────────────────────────────────────────────

const BOOK_ROWS = 14

const BookRow = memo(function BookRow({ price, qty, maxQty, side }) {
  const barPct = Math.min((qty / maxQty) * 100, 100)
  const isAsk = side === 'ask'
  return (
    <div className="relative flex items-center justify-between text-[11px] py-[3px] px-2 hover:bg-slate-800/40 cursor-default">
      <div
        className={`absolute inset-y-0 right-0 opacity-[0.08] ${isAsk ? 'bg-red-500' : 'bg-emerald-500'}`}
        style={{ width: `${barPct}%` }}
      />
      <span className={`tabular-nums z-10 ${isAsk ? 'text-red-400' : 'text-emerald-400'}`}>
        {price.toFixed(1)}
      </span>
      <span className="text-gray-400 tabular-nums z-10">{qty.toFixed(3)}</span>
    </div>
  )
})

function OrderBook() {
  const { streamPrefix } = useCurrentSymbol()
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

  useBinanceWS(`${streamPrefix}@depth20@100ms`, onDepth)

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

  return (
    <div className="bg-title-bg border-r border-slate-700/50 flex flex-col min-h-0 flex-1">
      <div className="px-3 h-10 flex items-center border-b border-slate-700/50 shrink-0 title-fade">
        <span className="text-xs font-semibold text-gray-200">Order Book</span>
      </div>

      <div className="flex justify-between px-2 py-1 shrink-0">
        <span className="text-[10px] text-slate-400">Price (USDT)</span>
        <span className="text-[10px] text-slate-400">Size (BTC)</span>
      </div>

      {/* Asks reversed — lowest ask closest to spread */}
      <div className="flex flex-col-reverse flex-1 min-h-0 overflow-hidden">
        {book.asks.length === 0
          ? Array.from({ length: BOOK_ROWS }).map((_, i) => (
              <div key={i} className="h-[22px] mx-2 my-px bg-slate-800/40 rounded animate-pulse" />
            ))
          : book.asks.slice(0, BOOK_ROWS).map((row, i) => (
              <BookRow key={i} price={row.price} qty={row.qty} maxQty={maxQty} side="ask" />
            ))}
      </div>

      {/* Mid price / spread row */}
      <div className="flex items-center justify-between px-2 py-1.5 border-y border-slate-700/50 shrink-0">
        <span className="text-sm font-bold text-gray-100 tabular-nums">{midPrice}</span>
        <span className="text-[10px] text-slate-400">Spread: {spread}</span>
      </div>

      {/* Bids */}
      <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
        {book.bids.length === 0
          ? Array.from({ length: BOOK_ROWS }).map((_, i) => (
              <div key={i} className="h-[22px] mx-2 my-px bg-slate-800/40 rounded animate-pulse" />
            ))
          : book.bids.slice(0, BOOK_ROWS).map((row, i) => (
              <BookRow key={i} price={row.price} qty={row.qty} maxQty={maxQty} side="bid" />
            ))}
      </div>
    </div>
  )
}

// ─── RecentTrades ─────────────────────────────────────────────────────────────

const MAX_TRADES = 60

function RecentTrades() {
  const { streamPrefix } = useCurrentSymbol()
  const [trades, setTrades] = useState([])

  const onTrade = useCallback((data) => {
    setTrades((prev) => {
      const entry = {
        id: data.a,
        price: parseFloat(data.p),
        qty: parseFloat(data.q),
        // Recent-trades blotter needs a compact HH:MM:SS — always UTC (see "Time (UTC)" header) to
        // match the rest of the page's timestamp convention (client/CLAUDE.md: dates/times default UTC).
        time: new Date(data.T).toLocaleTimeString('en-US', { hour12: false, timeZone: 'UTC' }),
        isBuyerMaker: data.m,
      }
      const next = [entry, ...prev]
      if (next.length > MAX_TRADES) next.length = MAX_TRADES
      return next
    })
  }, [])

  useBinanceWS(`${streamPrefix}@aggTrade`, onTrade)

  return (
    <div className="bg-title-bg border-r border-slate-700/50 flex flex-col min-h-0 h-[240px]">
      <div className="px-3 py-2 border-b border-slate-700/50 shrink-0 title-fade">
        <span className="text-xs font-semibold text-gray-200">Trades</span>
      </div>
      <div className="flex justify-between px-2 py-1 shrink-0">
        <span className="text-[10px] text-slate-400">Price (USDT)</span>
        <span className="text-[10px] text-slate-400">Amount (BTC)</span>
        <span className="text-[10px] text-slate-400">Time (UTC)</span>
      </div>
      <div className="flex-1 overflow-hidden min-h-0">
        {trades.length === 0 ? (
          <div className="flex flex-col gap-1 p-2">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-3 bg-slate-800/40 rounded animate-pulse" />
            ))}
          </div>
        ) : (
          trades.map((t) => (
            <div
              key={t.id}
              className="flex justify-between px-2 py-[2px] text-[11px] hover:bg-slate-800/20"
            >
              <span className={`tabular-nums ${t.isBuyerMaker ? 'text-red-400' : 'text-emerald-400'}`}>
                {t.price.toFixed(1)}
              </span>
              <span className="text-gray-400 tabular-nums">{t.qty.toFixed(3)}</span>
              <span className="text-slate-400 tabular-nums">{t.time}</span>
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
        <td key={i} className={`py-2 pr-4 ${i === 0 ? 'pl-2' : ''}`}>
          <div className="h-3 bg-slate-800/50 rounded w-full animate-pulse" />
        </td>
      ))}
    </tr>
  )
}

function EmptyRow({ message }) {
  return (
    <tr>
      <td colSpan={99} className="py-8 text-center text-slate-400 text-xs">
        {message}
      </td>
    </tr>
  )
}

// ─── TpSlModal ────────────────────────────────────────────────────────────────

function TpSlModal({ position, onClose }) {
  const [tpEnabled, setTpEnabled] = useState(false)
  const [slEnabled, setSlEnabled] = useState(false)
  const [tpPrice, setTpPrice] = useState('')
  const [slPrice, setSlPrice] = useState('')
  const [submitError, setSubmitError] = useState(null)

  const posSize = parseFloat(position.positionAmt)
  const isLong = posSize > 0
  const quantity = Math.abs(posSize)
  const markPrice = parseFloat(position.markPrice)
  const entryPrice = parseFloat(position.entryPrice)
  const entrySide = isLong ? 'BUY' : 'SELL'
  const displaySymbol = position.symbol.replace('USDT', '-USDT')

  const { mutate: execPlaceOCO, isPending } = usePlaceOCOOrder()

  // Per-field inline validation (derived, no state needed)
  const tpError = (() => {
    if (!tpEnabled || !tpPrice) return null
    const v = parseFloat(tpPrice)
    if (isNaN(v) || v <= 0) return 'Enter a valid price'
    if (isLong && v <= markPrice) return 'Trigger price should be higher than mark price'
    if (!isLong && v >= markPrice) return 'Trigger price should be lower than mark price'
    return null
  })()

  const slError = (() => {
    if (!slEnabled || !slPrice) return null
    const v = parseFloat(slPrice)
    if (isNaN(v) || v <= 0) return 'Enter a valid price'
    if (isLong && v >= markPrice) return 'Trigger price should be lower than mark price'
    if (!isLong && v <= markPrice) return 'Trigger price should be higher than mark price'
    return null
  })()

  const canConfirm =
    !isPending &&
    (tpEnabled || slEnabled) &&
    (!tpEnabled || (tpPrice !== '' && !tpError)) &&
    (!slEnabled || (slPrice !== '' && !slError))

  function handleConfirm() {
    setSubmitError(null)
    execPlaceOCO(
      {
        symbol: displaySymbol,
        side: entrySide,
        quantity,
        stopPrice: slEnabled ? parseFloat(slPrice) : undefined,
        takeProfitPrice: tpEnabled ? parseFloat(tpPrice) : undefined,
      },
      {
        onSuccess: onClose,
        onError: (err) => {
          const detail =
            err.response?.data?.error?.message ||
            err.response?.data?.message ||
            err.response?.data?.detail ||
            err.message
          setSubmitError(typeof detail === 'string' ? detail : 'Failed to place TP/SL')
        },
      }
    )
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="w-80 p-0 gap-0">
        <DialogHeader className="flex flex-row items-center justify-between px-4 py-3 border-b border-slate-700/50 space-y-0">
          <DialogTitle className="text-sm font-semibold text-gray-100">Take Profit / Stop Loss</DialogTitle>
        </DialogHeader>

        {/* Direction indicator (read-only, matches position) */}
        <div className="flex mx-4 mt-3 rounded-lg overflow-hidden text-xs font-semibold">
          <div className={`flex-1 py-2 text-center rounded-l-lg ${isLong ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
            Buy / Long
          </div>
          <div className={`flex-1 py-2 text-center rounded-r-lg ${!isLong ? 'bg-red-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
            Sell / Short
          </div>
        </div>

        <div className="flex flex-col px-4 pt-3 pb-1">
          <div className="text-[10px] text-slate-400 mb-2 tabular-nums">
            Mark: {fmtPriceForSymbol(markPrice, position.symbol)} · Entry: {fmtPriceForSymbol(entryPrice, position.symbol)} · Qty: {fmtQtyForSymbol(quantity, position.symbol)} {position.symbol.replace('USDT', '')}
          </div>

          {/* Take Profit section */}
          <div className="flex flex-col gap-2 py-3 border-b border-slate-700/50">
            <label
              className="flex items-center gap-2.5 cursor-pointer select-none"
              onClick={() => { setTpEnabled((v) => !v); setTpPrice('') }}
            >
              <div className={[
                'w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 transition-colors',
                tpEnabled ? 'bg-emerald-400 border-emerald-400' : 'border-slate-600 bg-transparent',
              ].join(' ')}>
                {tpEnabled && <span className="text-white text-[9px] font-bold leading-none">✓</span>}
              </div>
              <span className="text-sm text-gray-200 font-medium">Take Profit</span>
            </label>

            {tpEnabled && (
              <>
                <input
                  type="number"
                  value={tpPrice}
                  onChange={(e) => setTpPrice(e.target.value)}
                  placeholder="Trigger Price"
                  autoFocus
                  disabled={isPending}
                  className={[
                    'w-full bg-[#0a0d13] border rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-slate-600',
                    'focus:outline-none tabular-nums transition-colors disabled:opacity-50',
                    tpError ? 'border-red-500 focus:border-red-500' : 'border-slate-700/50 focus:border-emerald-400',
                  ].join(' ')}
                />
                {tpError && <span className="text-[11px] text-red-400">{tpError}</span>}
                {!tpError && tpPrice && (
                  <span className="text-[10px] text-slate-400">
                    When Mark Price reaches <span className="text-gray-300 tabular-nums">{fmtPrice(tpPrice)} USDT</span>, a Market order will be triggered to close the position.
                  </span>
                )}
              </>
            )}
          </div>

          {/* Stop Loss section */}
          <div className="flex flex-col gap-2 py-3">
            <label
              className="flex items-center gap-2.5 cursor-pointer select-none"
              onClick={() => { setSlEnabled((v) => !v); setSlPrice('') }}
            >
              <div className={[
                'w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 transition-colors',
                slEnabled ? 'bg-emerald-400 border-emerald-400' : 'border-slate-600 bg-transparent',
              ].join(' ')}>
                {slEnabled && <span className="text-white text-[9px] font-bold leading-none">✓</span>}
              </div>
              <span className="text-sm text-gray-200 font-medium">Stop Loss</span>
            </label>

            {slEnabled && (
              <>
                <input
                  type="number"
                  value={slPrice}
                  onChange={(e) => setSlPrice(e.target.value)}
                  placeholder="Trigger Price"
                  disabled={isPending}
                  className={[
                    'w-full bg-[#0a0d13] border rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-slate-600',
                    'focus:outline-none tabular-nums transition-colors disabled:opacity-50',
                    slError ? 'border-red-500 focus:border-red-500' : 'border-slate-700/50 focus:border-emerald-400',
                  ].join(' ')}
                />
                {slError && <span className="text-[11px] text-red-400">{slError}</span>}
                {!slError && slPrice && (
                  <span className="text-[10px] text-slate-400">
                    When Mark Price reaches <span className="text-gray-300 tabular-nums">{fmtPrice(slPrice)} USDT</span>, a Market order will be triggered to close the position.
                  </span>
                )}
              </>
            )}
          </div>

          {submitError && (
            <div className="mb-2 text-[11px] text-red-400 bg-red-950/20 border border-red-800/30 rounded-lg px-3 py-2">
              {submitError}
            </div>
          )}
        </div>

        {/* Confirm button */}
        <div className="px-4 pb-4">
          <button
            onClick={handleConfirm}
            disabled={!canConfirm}
            className={[
              'w-full py-3 rounded-lg text-sm font-semibold transition-colors',
              canConfirm
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white cursor-pointer'
                : 'bg-slate-800 text-slate-600 cursor-not-allowed',
            ].join(' ')}
          >
            {isPending ? 'Confirming…' : 'Confirm'}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ─── PositionsTable ───────────────────────────────────────────────────────────

function PositionsTable({ data, isLoading, account }) {
  const cols = ['Symbol', 'Size', 'Entry Price', 'Mark Price', 'Liq Price', 'Margin Ratio', 'Unrealized PnL', '']
  const [closeError, setCloseError] = useState(null)
  const [tpslPosition, setTpslPosition] = useState(null) // position object for modal
  const [confirmCloseSymbol, setConfirmCloseSymbol] = useState(null)

  const navigate = useNavigate()
  const { symbol: activeSymbol } = useCurrentSymbol()

  // Clicking a position row loads that symbol's full terminal (chart, ticker, order book,
  // order form + per-symbol leverage/margin) via the route — same path SymbolSearchBar uses.
  function handleRowClick(symbol) {
    if (symbol === activeSymbol) return
    navigate(`/trade/${symbol}`)
  }

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

  const activePositions = data?.filter((p) => parseFloat(p.positionAmt) !== 0) ?? []

  const maintMargin = parseFloat(account?.totalMaintMargin ?? 0)
  const marginBalance = parseFloat(account?.totalMarginBalance ?? 0)
  const accountMarginRatio = marginBalance > 0 ? (maintMargin / marginBalance * 100).toFixed(2) + '%' : '—'

  return (
    <>
      {tpslPosition && (
        <TpSlModal position={tpslPosition} onClose={() => setTpslPosition(null)} />
      )}
      <ConfirmDialog
        open={!!confirmCloseSymbol}
        onOpenChange={(v) => { if (!v) setConfirmCloseSymbol(null) }}
        title={`Close ${confirmCloseSymbol} position?`}
        description="This will send a market close order. This cannot be undone."
        confirmLabel="Close Position"
        onConfirm={() => { const s = confirmCloseSymbol; setConfirmCloseSymbol(null); handleClose(s) }}
      />

      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 border-b border-slate-700/50 bg-title-bg title-fade">
            {cols.map((c, i) => (
              <th key={c} className={`text-left py-2 pr-6 font-medium whitespace-nowrap ${i === 0 ? 'pl-2' : ''}`}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody className="text-gray-400">
          {isLoading ? (
            <>
              <SkeletonRow cols={cols} />
              <SkeletonRow cols={cols} />
            </>
          ) : !activePositions.length ? (
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
              {activePositions.map((p) => {
                const size = parseFloat(p.positionAmt)
                const side = size > 0 ? 'Long' : 'Short'
                const pnl = parseFloat(p.unRealizedProfit)
                const isPnlPos = pnl >= 0
                const isClosing = closePending && closeVars?.symbol === p.symbol
                const posRatio = p.marginRatio && parseFloat(p.marginRatio) > 0
                  ? (parseFloat(p.marginRatio) * 100).toFixed(2) + '%'
                  : accountMarginRatio
                const marginRatio = posRatio
                const isActive = p.symbol === activeSymbol
                return (
                  <tr
                    key={p.symbol}
                    onClick={() => handleRowClick(p.symbol)}
                    title="View chart"
                    className={[
                      'border-b border-slate-700/30 cursor-pointer transition-colors',
                      isActive ? 'bg-slate-800/40 border-l-2 border-emerald-400' : 'hover:bg-slate-800/20',
                    ].join(' ')}
                  >
                    <td className="py-2 pr-6 whitespace-nowrap pl-2">
                      <div className="flex items-center gap-2">
                        <span className="text-gray-100">{p.symbol.replace('USDT', '-USDT')}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${side === 'Long' ? 'bg-emerald-400/10 text-emerald-400' : 'bg-red-400/10 text-red-400'}`}>{side}</span>
                      </div>
                    </td>
                    <td className="py-2 pr-6 tabular-nums">{fmtQtyForSymbol(Math.abs(size), p.symbol)}</td>
                    <td className="py-2 pr-6 tabular-nums">{fmtPriceForSymbol(p.entryPrice, p.symbol)}</td>
                    <td className="py-2 pr-6 tabular-nums">{fmtPriceForSymbol(p.markPrice, p.symbol)}</td>
                    <td className="py-2 pr-6 tabular-nums">{fmtPriceForSymbol(p.liquidationPrice, p.symbol)}</td>
                    <td className="py-2 pr-6 tabular-nums">{marginRatio}</td>
                    <td className={`py-2 pr-6 tabular-nums font-medium ${isPnlPos ? 'text-emerald-400' : 'text-red-400'}`}>
                      {isPnlPos ? '+' : ''}{pnl.toFixed(2)} USDT
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-1.5">
                        <button
                          disabled={isClosing}
                          onClick={(e) => { e.stopPropagation(); setConfirmCloseSymbol(p.symbol) }}
                          className={[
                            'px-3 py-1 text-[10px] rounded border transition-colors whitespace-nowrap',
                            isClosing
                              ? 'border-slate-700/50 text-slate-400 cursor-not-allowed'
                              : 'border-slate-600 text-gray-300 hover:bg-slate-700/50 cursor-pointer',
                          ].join(' ')}
                        >
                          {isClosing ? 'Closing…' : 'Close Position'}
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setTpslPosition(p) }}
                          className="px-3 py-1 text-[10px] rounded border border-slate-600 text-gray-400 hover:bg-slate-700/50 hover:border-yellow-600/40 hover:text-yellow-400 transition-colors whitespace-nowrap cursor-pointer"
                        >
                          TP/SL
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </>
          )}
        </tbody>
      </table>
    </>
  )
}

function extractOcoId(clientOrderId) {
  if (!clientOrderId) return null
  const m = clientOrderId.match(/^((oco|tpsl)_[0-9a-f]{8}_)(?:sl|tp)$/)
  return m ? m[1] : null
}

function OpenOrdersTable({ data, isLoading, onOcoBannerEvent }) {
  const { symbol } = useCurrentSymbol()
  const cols = ['Symbol', 'Type', 'Side', 'Price', 'Amount', 'Filled', 'Status', 'OCO Group', '']
  const { mutate: execCancel, isPending: cancelPending, variables: cancelVars } = useCancelOrder()
  const { mutate: execCancelAll, isPending: cancelAllPending } = useCancelAllOrders()
  const [confirmCancelAllOpen, setConfirmCancelAllOpen] = useState(false)

  function handleCancelOco(ocoId) {
    // Cancel both legs by cancelling all orders for the symbol — the cleanest
    // approach since Binance Futures has no group-cancel endpoint.
    execCancelAll(
      { symbol },
      {
        onSuccess: () => onOcoBannerEvent?.('OCO group cancelled.'),
        onError: () => onOcoBannerEvent?.('Failed to cancel OCO group.'),
      }
    )
  }

  return (
    <div className="w-full">
      <ConfirmDialog
        open={confirmCancelAllOpen}
        onOpenChange={setConfirmCancelAllOpen}
        title="Cancel all open orders?"
        description={`This will cancel all open orders for ${symbol}. This cannot be undone.`}
        confirmLabel="Cancel All"
        onConfirm={() => { setConfirmCancelAllOpen(false); execCancelAll({ symbol }, { onSuccess: () => onOcoBannerEvent?.('All orders cancelled.') }) }}
      />
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 border-b border-slate-700/50 bg-title-bg title-fade">
            {cols.map((c, i) => {
              if (i === cols.length - 1) {
                return (
                  <th key="cancel-all" className="pr-2 text-right align-middle">
                    <button
                      disabled={cancelAllPending || !data?.length}
                      onClick={() => setConfirmCancelAllOpen(true)}
                      className="px-3 py-1 text-[10px] rounded border border-slate-600 text-gray-400 hover:bg-slate-700/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
                    >
                      {cancelAllPending ? 'Cancelling…' : 'Cancel All'}
                    </button>
                  </th>
                )
              }
              return (
                <th key={c} className={`text-left py-2 pr-6 font-medium whitespace-nowrap ${i === 0 ? 'pl-2' : ''}`}>{c}</th>
              )
            })}
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
              const ocoId = extractOcoId(o.clientOrderId)
              return (
                <tr key={o.orderId} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                  <td className="py-2 pr-6 text-gray-100 whitespace-nowrap pl-2">{o.symbol.replace('USDT', '-USDT')}</td>
                  <td className="py-2 pr-6">{o.type}</td>
                  <td className={`py-2 pr-6 font-medium ${o.side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>{o.side}</td>
                  <td className="py-2 pr-6 tabular-nums">{fmtPrice(o.price)}</td>
                  <td className="py-2 pr-6 tabular-nums">{fmtQty(o.origQty)}</td>
                  <td className="py-2 pr-6 tabular-nums">{fmtQty(o.executedQty)}</td>
                  <td className="py-2 pr-6">{o.status}</td>
                  <td className="py-2 pr-6">
                    {ocoId ? (
                      <span className="text-[10px] font-mono text-yellow-400 bg-yellow-400/10 px-1.5 py-0.5 rounded">
                        {ocoId}
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="py-2">
                    <div className="flex items-center gap-1">
                      <button
                        disabled={isCancelling}
                        onClick={() => execCancel({ symbol, orderId: o.orderId })}
                        className={[
                          'px-3 py-1 text-[10px] rounded border transition-colors',
                          isCancelling
                            ? 'border-slate-700/50 text-slate-400 cursor-not-allowed'
                            : 'border-slate-600 text-gray-400 hover:bg-slate-700/50 cursor-pointer',
                        ].join(' ')}
                      >
                        {isCancelling ? 'Cancelling…' : 'Cancel'}
                      </button>
                      {ocoId && (
                        <button
                          disabled={cancelAllPending}
                          onClick={() => handleCancelOco(ocoId)}
                          className="px-3 py-1 text-[10px] rounded border border-yellow-600/40 text-yellow-400 hover:bg-yellow-500/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                          Cancel OCO
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}

function AssetsTable({ data, isLoading }) {
  const cols = ['Asset', 'Wallet Balance', 'Available Balance', 'Unrealized PnL']
  const assets = data?.assets?.filter((a) => parseFloat(a.walletBalance) > 0) ?? []
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-gray-400 border-b border-slate-700/50 bg-title-bg title-fade">
          {cols.map((c, i) => (
            <th key={c} className={`text-left py-2 pr-6 font-medium ${i === 0 ? 'pl-2' : ''}`}>{c}</th>
          ))}
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
              <tr key={a.asset} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                <td className="py-2 pr-6 text-gray-100 font-medium pl-2">{a.asset}</td>
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

const SyncWarningBanner = () => (
  <div className="bg-yellow-950/20 border border-yellow-800/40 rounded px-3 py-1.5 text-[10px] text-yellow-400 mb-2 mt-1">
    Warning: Connection to the Strategy Engine failed. Displaying cached/offline data.
  </div>
)

function OrderHistoryTable({ data, isLoading, synced = true }) {
  const cols = ['Time', 'Symbol', 'Type', 'Side', 'Average', 'Price', 'Executed', 'Amount', 'Reduce Only', 'Post Only', 'Trigger Conditions', 'Status']
  return (
    <>
      {!synced && !isLoading && <SyncWarningBanner />}
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 border-b border-slate-700/50 bg-title-bg title-fade">
            {cols.map((c, i) => (
              <th key={c} className={`text-left py-2 pr-6 font-medium whitespace-nowrap ${i === 0 ? 'pl-2' : ''}`}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody className="text-gray-400">
          {isLoading ? (
            <>
              <SkeletonRow cols={cols} />
              <SkeletonRow cols={cols} />
            </>
          ) : !data?.length ? (
            <EmptyRow message="No order history" />
          ) : (
            data.map((o) => {
              const side = o.side.toUpperCase()
              const isFilled = o.status === 'FILLED'
              const isCanceled = o.status === 'CANCELED'
              const isNew = o.status === 'NEW'
              return (
                <tr key={o.orderId} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400 pl-2">{formatDateTime(o.time)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-gray-100">{o.symbol.replace('USDT', '-USDT')}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{o.type}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium ${side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>{side}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{o.avgPrice && parseFloat(o.avgPrice) > 0 ? fmtPrice(o.avgPrice) : '—'}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtPrice(o.price)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtQty(o.executedQty)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtQty(o.origQty)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{o.reduceOnly ? 'Yes' : 'No'}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{o.postOnly ? 'Yes' : 'No'}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{o.stopPrice && parseFloat(o.stopPrice) > 0 ? fmtPrice(o.stopPrice) : '—'}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium ${isFilled ? 'text-emerald-400' : isCanceled ? 'text-slate-400' : isNew ? 'text-yellow-400' : 'text-gray-300'}`}>{o.status}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </>
  )
}

function TradeHistoryTable({ data, isLoading, synced = true }) {
  const cols = ['Order No.', 'Time', 'Symbol', 'Side', 'Price', 'Quantity', 'Fee', 'Role', 'Realized Profit']
  return (
    <>
      {!synced && !isLoading && <SyncWarningBanner />}
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 border-b border-slate-700/50 bg-title-bg title-fade">
            {cols.map((c, i) => (
              <th key={c} className={`text-left py-2 pr-6 font-medium whitespace-nowrap ${i === 0 ? 'pl-2' : ''}`}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody className="text-gray-400">
          {isLoading ? (
            <>
              <SkeletonRow cols={cols} />
              <SkeletonRow cols={cols} />
            </>
          ) : !data?.length ? (
            <EmptyRow message="No trade history" />
          ) : (
            data.map((t) => {
              const side = t.side.toUpperCase()
              const pnl = parseFloat(t.realizedPnl || '0')
              return (
                <tr key={t.id} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400 tabular-nums pl-2">{t.orderId}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400">{formatDateTime(t.time)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-gray-100">{t.symbol.replace('USDT', '-USDT')}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium ${side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>{side}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtPrice(t.price)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtQty(t.qty)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400 tabular-nums">{t.commission ? `${fmtQty(t.commission)} ${t.commissionAsset || 'USDT'}` : '—'}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{t.maker ? 'Maker' : 'Taker'}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium tabular-nums ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pnl >= 0 ? '+' : ''}{pnl.toFixed(4)} USDT
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </>
  )
}

function TransactionHistoryTable({ data, isLoading, synced = true }) {
  const cols = ['Time', 'Type', 'Amount', 'Asset', 'Symbol']
  return (
    <>
      {!synced && !isLoading && <SyncWarningBanner />}
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 border-b border-slate-700/50 bg-title-bg title-fade">
            {cols.map((c, i) => (
              <th key={c} className={`text-left py-2 pr-6 font-medium whitespace-nowrap ${i === 0 ? 'pl-2' : ''}`}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody className="text-gray-400">
          {isLoading ? (
            <>
              <SkeletonRow cols={cols} />
              <SkeletonRow cols={cols} />
            </>
          ) : !data?.length ? (
            <EmptyRow message="No transaction history" />
          ) : (
            data.map((tx) => {
              const income = parseFloat(tx.income || '0')
              return (
                <tr key={tx.tranId} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400 pl-2">{formatDateTime(tx.time)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{tx.incomeType}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium tabular-nums ${income >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {income >= 0 ? '+' : ''}{parseFloat(tx.income).toFixed(4)}
                  </td>
                  <td className="py-2 pr-6 whitespace-nowrap">{tx.asset}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-gray-100">{tx.symbol ? tx.symbol.replace('USDT', '-USDT') : '—'}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </>
  )
}

function BottomPanel({ ocoToast, ocoBanner, onDismissBanner }) {
  const [activeTab, setActiveTab] = useState('Positions')

  const { symbol } = useCurrentSymbol()
  const { data: positions, isLoading: posLoading } = useTradePositions()
  const { data: openOrders, isLoading: ordLoading } = useTradeOpenOrders()
  const { data: account, isLoading: accLoading } = useTradeAccount()
  const { data: ordersRaw, isLoading: ordHistoryLoading } = useTradeOrders(symbol, {
    enabled: activeTab === 'Order History' && !!symbol,
    refetchInterval: 8000,
  })
  const { data: execRaw, isLoading: execLoading } = useTradeExecutions(symbol, {
    enabled: activeTab === 'Trade History' && !!symbol,
    refetchInterval: 8000,
  })
  const { data: txRaw, isLoading: txLoading } = useTradeTransactions(symbol, {
    enabled: activeTab === 'Transaction History',
    refetchInterval: 8000,
  })

  const ordersHistory = ordersRaw?.orders ?? ordersRaw
  const ordersSynced  = ordersRaw?.synced ?? true
  const executions    = execRaw?.executions ?? execRaw
  const execSynced    = execRaw?.synced ?? true
  const transactions  = txRaw?.transactions ?? txRaw
  const txSynced      = txRaw?.synced ?? true

  const [localBanner, setLocalBanner] = useState(null)
  const bannerTimerRef = useRef(null)

  const posCount = positions?.length ?? 0
  const ordCount = openOrders?.length ?? 0

  const activeBanner = ocoBanner || localBanner

  function handleOcoBannerEvent(msg) {
    clearTimeout(bannerTimerRef.current)
    setLocalBanner(msg)
    bannerTimerRef.current = setTimeout(() => setLocalBanner(null), 8000)
  }

  useEffect(() => {
    return () => clearTimeout(bannerTimerRef.current)
  }, [])

  return (
    <div className="bg-title-bg border-t border-slate-700/50 flex flex-col shrink-0 h-[200px]">
      <div className="flex border-b border-slate-700/50 shrink-0 title-fade bg-title-bg">
        {[
          { key: 'Positions', label: `Positions(${posCount})` },
          { key: 'Open Orders', label: `Open Orders(${ordCount})` },
          { key: 'Order History', label: 'Order History' },
          { key: 'Trade History', label: 'Trade History' },
          { key: 'Transaction History', label: 'Transaction History' },
          { key: 'Assets', label: 'Assets' },
        ].map(({ key, label }, i) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={[
              `${i === 0 ? 'pl-2 pr-4' : 'px-4'} py-2 text-xs font-medium transition-colors whitespace-nowrap`,
              activeTab === key
                ? 'text-gray-100 border-b-2 border-emerald-400 -mb-px'
                : 'text-slate-400 opacity-50 hover:opacity-100 hover:text-gray-300',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Persistent OCO event banner */}
      {activeBanner && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-yellow-400/10 border-b border-yellow-600/30 shrink-0">
          <span className="text-[11px] text-yellow-400">{activeBanner}</span>
          <button
            onClick={() => { clearTimeout(bannerTimerRef.current); setLocalBanner(null); onDismissBanner?.() }}
            className="text-yellow-600 hover:text-yellow-400 text-xs leading-none ml-2"
          >
            ✕
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto min-h-0">
        {activeTab === 'Positions' && (
          <PositionsTable data={positions} isLoading={posLoading} account={account} />
        )}
        {activeTab === 'Open Orders' && (
          <OpenOrdersTable
            data={openOrders}
            isLoading={ordLoading}
            onOcoBannerEvent={handleOcoBannerEvent}
          />
        )}
        {activeTab === 'Order History' && (
          <OrderHistoryTable data={ordersHistory} isLoading={ordHistoryLoading} synced={ordersSynced} />
        )}
        {activeTab === 'Trade History' && (
          <TradeHistoryTable data={executions} isLoading={execLoading} synced={execSynced} />
        )}
        {activeTab === 'Transaction History' && (
          <TransactionHistoryTable data={transactions} isLoading={txLoading} synced={txSynced} />
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
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="w-72 p-5 flex flex-col gap-4">
        <DialogHeader>
          <DialogTitle className="text-sm font-semibold text-gray-100">Adjust Leverage</DialogTitle>
        </DialogHeader>

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

        <div className="flex justify-between text-[10px] text-slate-400">
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
      </DialogContent>
    </Dialog>
  )
}

// ─── OrderForm ────────────────────────────────────────────────────────────────

function OrderForm() {
  const { symbol, streamPrefix, base, quote } = useCurrentSymbol()
  const [orderType, setOrderType] = useState('Limit')
  const [qtyUnit, setQtyUnit] = useState(base)
  const [price, setPrice] = useState('')
  const [qty, setQty] = useState('')
  const [pct, setPct] = useState(null)
  const [showLeverageModal, setShowLeverageModal] = useState(false)
  const [formError, setFormError] = useState(null)

  // Reset form fields whenever the traded symbol changes
  useEffect(() => {
    setQtyUnit(base)
    setQty('')
    setPrice('')
    setPct(null)
    setFormError(null)
  }, [base])

  const currentPriceRef = useRef(0)
  const onTicker = useCallback((data) => {
    currentPriceRef.current = parseFloat(data.c) || 0
  }, [])
  useBinanceWS(`${streamPrefix}@ticker`, onTicker)

  const { data: config, isLoading: configLoading } = useTradeSymbolConfig(symbol)
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
      execChangeMarginType({ symbol, marginType: 'ISOLATED' })
    }
  }, [config?.marginType, marginPending, execChangeMarginType, symbol])

  function handleLeverageConfirm(newLeverage) {
    setFormError(null)
    execChangeLeverage(
      { symbol, leverage: newLeverage },
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

  const { data: symbolsData } = useSymbols()

  const activeRules = symbolsData?.rules?.[symbol] || SYMBOL_LIMITS[symbol] || {
    tickSize: 0.001,
    stepSize: 0.01,
    minQty: 0.01,
    minNotional: 5.0,
  }

  function handlePctClick(p) {
    setPct(p)
    const leverage = typeof activeLeverage === 'number' ? activeLeverage : 1
    const targetUSDT = availableBalance * leverage * (p / 100)
    
    // Safety margin (99%) to prevent balance execution failures
    const maxUSDT = availableBalance * leverage * 0.99
    const safeUSDT = Math.min(targetUSDT, maxUSDT)

    const step = activeRules.stepSize
    if (qtyUnit === 'USDT') {
      setQty(roundToStep(safeUSDT, 0.01).toString())
    } else {
      const cp = currentPriceRef.current
      if (cp > 0) {
        const rawQty = safeUSDT / cp
        const roundedQty = roundToStep(rawQty, step)
        const minQty = activeRules.minQty
        setQty(roundedQty > 0 ? roundedQty.toString() : minQty.toString())
      } else {
        setQty('')
      }
    }
  }

  function handleSubmit(side) {
    setFormError(null)
    const cp = currentPriceRef.current
    let quantity = parseFloat(qty)
    if (isNaN(quantity) || quantity <= 0) {
      setFormError('Enter a valid quantity' + (orderType === 'Limit' ? ' and price' : ''))
      return
    }

    const step = activeRules.stepSize
    const minQty = activeRules.minQty
    const minNotional = activeRules.minNotional

    if (qtyUnit === 'USDT') {
      if (cp <= 0) { setFormError('Market price unavailable'); return }
      quantity = quantity / cp
    }

    // 1. Round quantity to stepSize precision
    quantity = roundToStep(quantity, step)

    // 2. Validate against minQty
    if (quantity < minQty) {
      setFormError(`Quantity must be no smaller than ${minQty} ${base}`)
      return
    }

    // 3. Round price (if Limit) and get execution price
    let executionPrice = cp
    let limitPriceVal = parseFloat(price)
    if (orderType === 'Limit') {
      if (isNaN(limitPriceVal) || limitPriceVal <= 0) {
        setFormError('Enter a valid limit price')
        return
      }
      limitPriceVal = roundToStep(limitPriceVal, activeRules.tickSize)
      executionPrice = limitPriceVal
    }

    // 4. Validate notional value
    const notional = quantity * executionPrice
    if (notional < minNotional) {
      setFormError(
        `Order's notional must be no smaller than ${minNotional} USDT (Current: ${notional.toFixed(2)} USDT). Please increase order size.`
      )
      return
    }

    const payload = { symbol, side, type: orderType.toUpperCase(), quantity }
    if (orderType === 'Limit') {
      payload.price = limitPriceVal
    }
    execPlaceOrder(payload, {
      onSuccess: () => { setQty(''); setPrice(''); setPct(null) },
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

      <div className="flex flex-col min-h-0 flex-1 bg-title-bg">
        {/* Margin type + Leverage row */}
        <div className="flex items-center justify-between px-3 h-10 border-b border-slate-700/50">
          <div className={`flex rounded overflow-hidden border text-xs ${isConfigBusy ? 'opacity-50' : 'border-slate-700/50'}`}>
            <span className="px-3 py-1.5 bg-slate-800 text-slate-300 text-xs font-medium">
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
        <div className="flex items-center border-b border-slate-700/50 px-3">
          {['Limit', 'Market'].map((type) => (
            <button
              key={type}
              onClick={() => { setOrderType(type); setPrice('') }}
              className={[
                'py-2 px-2 mr-2 text-xs font-medium transition-colors',
                orderType === type
                  ? 'text-gray-100 border-b-2 border-emerald-400 -mb-px'
                  : 'text-slate-400 hover:text-gray-300',
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
            <span className="text-slate-400">Available</span>
            <span className="text-gray-300 tabular-nums">
              {availableBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT
            </span>
          </div>

          {/* Symbol limits badge */}
          <div className="flex justify-between text-[10px] text-slate-400 border-t border-slate-700/40 pt-1.5 mt-0.5 shrink-0">
            <span>Min Size: <span className="text-gray-400 font-medium tabular-nums">{activeRules.minQty} {base}</span></span>
            <span>Min Value: <span className="text-gray-400 font-medium tabular-nums">{activeRules.minNotional} USDT</span></span>
          </div>

          {/* Price — only for Limit */}
          {orderType === 'Limit' && (
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-slate-400">Price (USDT)</label>
              <input
                type="number"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="0.00"
                disabled={orderPending}
                className="bg-[#0a0d13] border border-slate-600/50 rounded px-3 py-2 text-xs text-gray-100 placeholder-slate-600 focus:outline-none focus:border-emerald-400 disabled:opacity-50 tabular-nums"
              />
            </div>
          )}

          {/* Quantity */}
          <div className="flex flex-col gap-1">
            <label className="text-[11px] text-slate-400">Size</label>
            <div className="flex border border-slate-600/50 rounded overflow-hidden">
              <input
                type="number"
                value={qty}
                onChange={(e) => { setQty(e.target.value); setPct(null) }}
                placeholder="0.000"
                disabled={orderPending}
                className="flex-1 bg-[#0a0d13] px-3 py-2 text-xs text-gray-100 placeholder-slate-600 focus:outline-none min-w-0 disabled:opacity-50 tabular-nums"
              />
              <div className="flex shrink-0 border-l border-slate-600/50">
                {[base, quote].map((unit) => (
                  <button
                    key={unit}
                    onClick={() => { setQtyUnit(unit); setQty(''); setPct(null) }}
                    disabled={orderPending}
                    className={[
                      'px-2.5 text-xs transition-colors font-medium',
                      qtyUnit === unit
                        ? 'bg-slate-700 text-gray-100'
                        : 'bg-slate-800 text-slate-400 hover:text-gray-300',
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
                  'flex-1 h-7 text-xs rounded transition-colors border flex items-center justify-center py-0 leading-none',
                  pct === p
                    ? 'bg-slate-700 border-slate-600 text-gray-100'
                    : 'border-slate-600/50 text-slate-400 hover:text-gray-300 hover:border-slate-600',
                ].join(' ')}
              >
                {p}%
              </button>
            ))}
          </div>

          {/* Buy / Sell buttons */}
          <div className="flex gap-2 mt-1">
            <button
              onClick={() => handleSubmit('BUY')}
              disabled={orderPending}
              aria-busy={orderPending}
              aria-label={orderPending ? 'Placing buy order…' : 'Buy / Long'}
              className="flex-1 py-3 rounded text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
            >
              {orderPending
                ? <><span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" /><span>Placing…</span></>
                : 'Buy/Long'}
            </button>
            <button
              onClick={() => handleSubmit('SELL')}
              disabled={orderPending}
              aria-busy={orderPending}
              aria-label={orderPending ? 'Placing sell order…' : 'Sell / Short'}
              className="flex-1 py-3 rounded text-xs font-semibold bg-red-600 hover:bg-red-700 text-white transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
            >
              {orderPending
                ? <><span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" /><span>Placing…</span></>
                : 'Sell/Short'}
            </button>
          </div>

          <p className="text-[10px] text-slate-400 text-center mt-1">
            Set TP/SL on open positions in the Positions tab below
          </p>
        </div>
      </div>
    </>
  )
}

// ─── Trade (root) ─────────────────────────────────────────────────────────────

function TradeInner() {
  const { symbol } = useCurrentSymbol()
  const [timeframe, setTimeframe] = useState('1m')
  const [ocoToast, setOcoToast] = useState(null)
  const [ocoBanner, setOcoBanner] = useState(null)
  const toastTimerRef = useRef(null)

  useEffect(() => {
    return () => clearTimeout(toastTimerRef.current)
  }, [])

  const showToast = useCallback((msg) => {
    setOcoToast(msg)
    clearTimeout(toastTimerRef.current)
    toastTimerRef.current = setTimeout(() => setOcoToast(null), 4000)
  }, [])

  const handleTpSlEvent = useCallback((msg) => {
    showToast(msg)
    setOcoBanner(msg)
  }, [showToast])

  // Monitor open orders for TP/SL fills and auto-cancel the sibling leg
  useOcoMonitor({ symbol, onEvent: handleTpSlEvent })

  return (
    <div className="bg-[#060a0f] text-gray-100 flex flex-col h-[calc(100vh-56px)] overflow-hidden mt-14">
      <TickerBar />

      {/* Short-lived toast notification */}
      {ocoToast && (
        <div className="absolute top-20 r