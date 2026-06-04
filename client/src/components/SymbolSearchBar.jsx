import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Star, ChevronDown, Search } from 'lucide-react'
import { useSymbols } from '@/hooks/useCandles'
import { useCurrentSymbol } from '@/context/SymbolContext'
import useBinanceWS from '@/hooks/useBinanceWS'

const WATCHLIST_KEY = 'watchlist'
const DEFAULT_WATCHLIST = ['BTCUSDT', 'ETHUSDT']

function loadWatchlist() {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY)
    return raw ? JSON.parse(raw) : DEFAULT_WATCHLIST
  } catch {
    return DEFAULT_WATCHLIST
  }
}

function saveWatchlist(list) {
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(list))
}

// Sub-component: mounts only when dropdown is open, connects the all-ticker stream
function MarketTickerStreamer({ onTickers }) {
  useBinanceWS('!ticker@arr', onTickers)
  return null
}

export default function SymbolSearchBar() {
  const navigate = useNavigate()
  const { symbol: activeSymbol } = useCurrentSymbol()
  const { data: symbols, isLoading } = useSymbols()

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeTab, setActiveTab] = useState('All')
  const [highlightIdx, setHighlightIdx] = useState(0)
  const [watchlist, setWatchlist] = useState(loadWatchlist)
  const [marketTickers, setMarketTickers] = useState({})

  const containerRef = useRef(null)
  const inputRef = useRef(null)
  const closeTimerRef = useRef(null)

  const futuresSymbols = symbols?.futures ?? []

  const symbolSet = useMemo(() => new Set(futuresSymbols), [futuresSymbols])

  const onTickers = useCallback((payload) => {
    if (!Array.isArray(payload)) return
    setMarketTickers((prev) => {
      const next = { ...prev }
      for (const item of payload) {
        if (symbolSet.has(item.s)) {
          next[item.s] = { price: item.c, changePct: item.P }
        }
      }
      return next
    })
  }, [symbolSet])

  // Filtered list based on tab + query
  const baseList = activeTab === 'Watchlist' ? watchlist : futuresSymbols
  const filtered = query.trim()
    ? baseList.filter((s) => s.toLowerCase().includes(query.trim().toLowerCase()))
    : baseList

  function openDropdown() {
    clearTimeout(closeTimerRef.current)
    setOpen(true)
  }

  function scheduleClose() {
    closeTimerRef.current = setTimeout(() => setOpen(false), 200)
  }

  // Focus input when dropdown opens
  useEffect(() => {
    if (open) {
      setHighlightIdx(0)
      setTimeout(() => inputRef.current?.focus(), 0)
    } else {
      setQuery('')
    }
  }, [open])

  // Cleanup timer on unmount
  useEffect(() => {
    return () => clearTimeout(closeTimerRef.current)
  }, [])

  function selectSymbol(sym) {
    setOpen(false)
    setQuery('')
    navigate(`/trade/${sym}`)
  }

  function toggleWatchlist(sym) {
    setWatchlist((prev) => {
      const next = prev.includes(sym) ? prev.filter((s) => s !== sym) : [...prev, sym]
      saveWatchlist(next)
      return next
    })
  }

  function handleKeyDown(e) {
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIdx((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (filtered[highlightIdx]) selectSymbol(filtered[highlightIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const isFavorited = watchlist.includes(activeSymbol)

  return (
    <div
      ref={containerRef}
      className="relative"
      onMouseEnter={openDropdown}
      onMouseLeave={scheduleClose}
    >
      {/* Trigger */}
      <div className="flex items-center gap-1.5 cursor-pointer select-none px-2 py-1 rounded hover:bg-gray-800 transition-colors">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); toggleWatchlist(activeSymbol) }}
          className="p-0.5 rounded hover:bg-gray-700 transition-colors"
          aria-label={isFavorited ? 'Remove from watchlist' : 'Add to watchlist'}
        >
          <Star
            size={13}
            className={isFavorited ? 'text-yellow-400 fill-yellow-400' : 'text-gray-500'}
          />
        </button>
        <span className="text-sm font-bold text-gray-100">{activeSymbol}</span>
        <ChevronDown
          size={13}
          className={`text-gray-400 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
        />
      </div>

      {/* Dropdown */}
      {open && (
        <div
          className="absolute top-[calc(100%+6px)] left-0 z-[100] w-[420px] bg-gray-950/95 border border-gray-800 backdrop-blur-md shadow-2xl rounded-lg p-3 flex flex-col gap-3 font-sans"
          onMouseEnter={openDropdown}
          onMouseLeave={scheduleClose}
        >
          {open && <MarketTickerStreamer onTickers={onTickers} />}

          {/* Filter header */}
          <div className="flex flex-col gap-2">
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setHighlightIdx(0) }}
                onKeyDown={handleKeyDown}
                placeholder="Search symbol…"
                className="w-full bg-gray-800 border border-gray-700 rounded pl-7 pr-3 py-1.5 text-xs text-gray-100 placeholder-gray-500 focus:outline-none focus:border-gray-500 transition-colors"
              />
            </div>
            <div className="flex rounded border border-gray-700 overflow-hidden text-xs">
              {['All', 'Watchlist'].map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => { setActiveTab(tab); setHighlightIdx(0) }}
                  className={`flex-1 py-1.5 transition-colors ${
                    activeTab === tab
                      ? 'bg-gray-700 text-gray-100'
                      : 'bg-gray-900 text-gray-400 hover:bg-gray-800 hover:text-gray-300'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>

          {/* Symbol table */}
          <div>
            {isLoading ? (
              <div className="px-3 py-4 text-xs text-gray-500 text-center">Loading…</div>
            ) : filtered.length === 0 ? (
              <div className="px-3 py-4 text-xs text-gray-500 text-center">No results</div>
            ) : (
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-800">
                    <th className="w-6 pb-1.5" />
                    <th className="text-left pb-1.5 pl-1">Symbol</th>
                    <th className="text-right pb-1.5">Price</th>
                    <th className="text-right pb-1.5 pr-1">24h</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((sym, idx) => {
                    const ticker = marketTickers[sym]
                    const pct = ticker ? parseFloat(ticker.changePct) : null
                    const isPos = pct !== null && pct >= 0
                    const isFav = watchlist.includes(sym)

                    return (
                      <tr
                        key={sym}
                        onClick={() => selectSymbol(sym)}
                        onMouseEnter={() => setHighlightIdx(idx)}
                        className={[
                          'cursor-pointer transition-colors',
                          idx === highlightIdx ? 'bg-gray-800' : 'hover:bg-gray-900/60',
                          sym === activeSymbol ? 'opacity-60' : '',
                        ].join(' ')}
                      >
                        <td className="py-1.5 pl-1 w-6">
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); toggleWatchlist(sym) }}
                            className="p-0.5 rounded hover:bg-gray-700 transition-colors"
                            aria-label={isFav ? 'Remove from watchlist' : 'Add to watchlist'}
                          >
                            <Star
                              size={11}
                              className={isFav ? 'text-yellow-400 fill-yellow-400' : 'text-gray-600 hover:text-gray-400'}
                            />
                          </button>
                        </td>
                        <td className="py-1.5 pl-1">
                          <span className={`font-semibold ${sym === activeSymbol ? 'text-gray-300' : 'text-gray-100'}`}>
                            {sym}
                          </span>
                        </td>
                        <td className="py-1.5 text-right text-gray-300">
                          {ticker ? `$${parseFloat(ticker.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}` : '—'}
                        </td>
                        <td className={`py-1.5 pr-1 text-right font-medium ${pct === null ? 'text-gray-500' : isPos ? 'text-emerald-400' : 'text-red-400'}`}>
                          {pct === null ? '—' : `${isPos ? '+' : ''}${pct.toFixed(2)}%`}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
