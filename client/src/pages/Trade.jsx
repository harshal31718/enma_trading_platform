import { memo, useCallback, useEffect, useRef, useState } from 'react'
import ErrorBoundary from '@/components/ErrorBoundary'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import axios from 'axios'
import api from '@/lib/axios'
import { createChart, CandlestickSeries } from 'lightweight-charts'
import useBinanceWS from '@/hooks/useBinanceWS'
import useMarketStore, { useMarketTicker } from '@/store/marketStore'
import {
  useTradeAccount,
  useTradeStream,
  useTradeSymbolConfig,
  useChangeLeverage,
  useChangeMarginType,
  usePlaceOrder,
} from '@/hooks/useTrade'
import useOcoMonitor from '@/hooks/useOcoMonitor'
import { SymbolProvider, useCurrentSymbol } from '@/context/SymbolContext'
import SymbolSearchBar from '@/components/SymbolSearchBar'
import { SYMBOL_LIMITS } from '@/utils/symbolLimits'
import { useSymbols } from '@/hooks/useCandles'
import BottomPanel from '@/features/trade/BottomPanel'
import { fmtPrice, fmtPriceForSymbol, fmtQtyForSymbol, fmtQty, fmtPct, roundToStep } from '@/features/trade/formatters'

// ─── TickerBar ────────────────────────────────────────────────────────────────

function TickerBar() {
  const { streamPrefix, base, quote } = useCurrentSymbol()
  const ticker = useMarketTicker(streamPrefix)

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
      .catch((err) => {
        if (err.name !== 'AbortError' && !axios.isCancel(err)) {
          setChartError(err.message)
        }
      })
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

      <div ref={containerRef} className="flex-1 min-h-[300px] lg:min-h-0" />

      {/* Timeframe buttons — absolute overlay, aligned with TradingView logo */}
      <div className="absolute bottom-8 left-12 z-10 flex items-center gap-0.5">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf.interval}
            onClick={() => setTimeframe(tf.interval)}
            aria-pressed={timeframe === tf.interval}
            aria-label={`Timeframe ${tf.label}`}
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

  // Reads the single shared ticker store (TickerBar's useMarketTicker call
  // keeps it fresh — both are always co-mounted in this page's layout).
  // Deliberately NOT subscribed reactively here (no useMarketTicker call):
  // sizing math only needs the current price at click time, not a live
  // re-render on every tick — same non-reactive-read intent the old
  // ref-based version had, just reading from the documented single owner
  // instead of a second, independent subscription+parse of its own.
  const getCurrentPrice = useCallback(
    () => useMarketStore.getState().tickers[streamPrefix]?.price ?? 0,
    [streamPrefix]
  )

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
      const cp = getCurrentPrice()
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
    const cp = getCurrentPrice()
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
  const [activeTab, setActiveTab] = useState('chart')
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

  // Real-time account/order push over WebSocket — starts on mount, stops on
  // unmount. Lets the REST polling hooks above use long safety-net intervals
  // instead of hammering Binance's shared per-IP rate limit. See
  // workspace/docs/features/live-trading/SPEC.md.
  useTradeStream()

  return (
    <div className="bg-[#060a0f] text-gray-100 flex flex-col h-[calc(100vh-56px)] overflow-hidden mt-14">
      <TickerBar />

      {/* Mobile Tab Bar */}
      <div className="flex border-b border-slate-700/50 bg-[#0a0d13] lg:hidden select-none">
        <button
          onClick={() => setActiveTab('chart')}
          className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 transition-colors ${activeTab === 'chart' ? 'border-emerald-400 text-emerald-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
        >
          Chart
        </button>
        <button
          onClick={() => setActiveTab('book')}
          className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 transition-colors ${activeTab === 'book' ? 'border-emerald-400 text-emerald-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
        >
          Order Book
        </button>
        <button
          onClick={() => setActiveTab('trades')}
          className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 transition-colors ${activeTab === 'trades' ? 'border-emerald-400 text-emerald-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
        >
          Recent Trades
        </button>
        <button
          onClick={() => setActiveTab('form')}
          className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 transition-colors ${activeTab === 'form' ? 'border-emerald-400 text-emerald-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
        >
          Trade
        </button>
      </div>

      {/* Short-lived toast notification */}
      {ocoToast && (
        <div className="absolute top-20 right-4 z-50 bg-title-bg border border-slate-700/50 rounded-lg px-4 py-2.5 text-xs text-gray-100 shadow-2xl max-w-xs animate-fade-in">
          {ocoToast}
        </div>
      )}

      {/* Main content — fills remaining height */}
      <div className="flex flex-col lg:flex-row flex-1 min-h-0 overflow-y-auto lg:overflow-hidden">

        {/* Left col — chart + bottom panel (fills remaining width) */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0 border-b lg:border-b-0 lg:border-r border-slate-700/50">
          <div className={`${activeTab === 'chart' ? 'flex' : 'hidden'} lg:flex flex-col flex-1 min-h-0`}>
            <ChartContainer timeframe={timeframe} setTimeframe={setTimeframe} />
          </div>
          <div className="flex flex-col min-h-0">
            <BottomPanel
              ocoBanner={ocoBanner}
              onDismissBanner={() => setOcoBanner(null)}
            />
          </div>
        </div>

        {/* Middle col — order book + recent trades, fixed width */}
        <div className={`${activeTab === 'book' || activeTab === 'trades' ? 'flex' : 'hidden'} lg:flex flex-col min-h-0 shrink-0 w-full lg:w-[200px] border-b lg:border-b-0 lg:border-r border-slate-700/50`}>
          <div className={`${activeTab === 'book' ? 'flex' : 'hidden'} lg:flex flex-col min-h-0 flex-1 border-b border-slate-700/50`}>
            <OrderBook />
          </div>
          <div className={`${activeTab === 'trades' ? 'flex' : 'hidden'} lg:flex flex-col min-h-0 flex-1`}>
            <RecentTrades />
          </div>
        </div>

        {/* Right col — order form, fixed width */}
        <div className={`${activeTab === 'form' ? 'flex' : 'hidden'} lg:flex flex-col min-h-0 shrink-0 w-full lg:w-[260px]`}>
          <OrderForm />
        </div>

      </div>
    </div>
  )
}

export default function Trade() {
  return (
    <SymbolProvider>
      <TradeInner />
    </SymbolProvider>
  )
}