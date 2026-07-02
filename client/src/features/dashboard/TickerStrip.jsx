import { useCallback, useMemo, useState } from 'react'
import useBinanceWS from '@/hooks/useBinanceWS'
import { formatPrice, formatSignedPct } from '@/utils/formatters'

// Anchor majors always shown; open-position symbols are appended.
const MAJORS = ['BTCUSDT', 'ETHUSDT']
// Cap concurrent @ticker streams — the browser holds one shared WS connection
// (binanceWS singleton, ref-counted) but we still bound the subscription count.
const MAX_STREAMS = 8

// A single live price cell. State is isolated per-symbol so one ticker frame
// does not re-render the whole strip. Mirrors Trade.jsx TickerBar.
function TickerItem({ symbol }) {
  const [ticker, setTicker] = useState(null)

  const onTicker = useCallback((data) => {
    setTicker({ price: parseFloat(data.c), changePct: parseFloat(data.P) })
  }, [])

  useBinanceWS(`${symbol.toLowerCase()}@ticker`, onTicker)

  const isPositive = (ticker?.changePct ?? 0) >= 0

  return (
    <div className="flex items-center gap-2 pr-4 pl-4 first:pl-0 border-r border-slate-700/50 shrink-0">
      <span className="text-[11px] uppercase tracking-wider text-slate-400 font-medium">{symbol}</span>
      <span className="text-sm font-mono tabular-nums text-gray-100">
        {ticker ? formatPrice(ticker.price) : '—'}
      </span>
      <span className={`text-xs font-mono tabular-nums ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
        {ticker ? formatSignedPct(ticker.changePct) : ''}
      </span>
    </div>
  )
}

export default function TickerStrip({ positionSymbols = [] }) {
  // Majors first, then position symbols, deduped and capped. Memoized on a
  // stable key so the 30s position poll does not churn WS subscriptions.
  const symbols = useMemo(() => {
    const seen = new Set()
    const out = []
    for (const s of [...MAJORS, ...positionSymbols]) {
      const sym = String(s || '').toUpperCase()
      if (!sym || seen.has(sym)) continue
      seen.add(sym)
      out.push(sym)
      if (out.length >= MAX_STREAMS) break
    }
    return out
  }, [positionSymbols.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="h-8 flex items-stretch overflow-x-auto [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
      {symbols.map((sym) => (
        <TickerItem key={sym} symbol={sym} />
      ))}
    </div>
  )
}
