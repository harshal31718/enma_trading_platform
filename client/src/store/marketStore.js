import { create } from 'zustand'
import { useCallback } from 'react'
import useBinanceWS from '@/hooks/useBinanceWS'

// Plan 7 Step 7.5 (CLI-2/CLI-3): single owner for a symbol's live ticker
// price. Trade.jsx used to run 2 independent useBinanceWS('<sym>@ticker')
// subscriptions — TickerBar's header display and the order-entry panel's
// sizing calc — each parsing the same stream into its own local
// state/ref. binanceWS.js already ref-counts by stream name (one real
// WebSocket connection either way), but two independent parse-and-store
// call sites meant "this symbol's price" wasn't one documented value.
// `useMarketTicker` is that one value: one parse, one store slot, any
// number of components reading the same `tickers[symbol]` entry.
//
// Deliberately scoped to ticker/price only — OrderBook, RecentTrades, and
// the candle chart stay on their own dedicated useBinanceWS subscriptions
// (depth/aggTrade/kline are structurally different data, not "price", and
// client/CLAUDE.md's realtime rules already document per-sub-component
// isolation for those as a render-performance choice, not an accident).
const useMarketStore = create((set) => ({
  tickers: {}, // symbol -> { price, changePct, high, low, volume, quoteVolume }
  setTicker: (symbol, ticker) =>
    set((state) => ({ tickers: { ...state.tickers, [symbol]: ticker } })),
}))

export function useMarketTicker(streamPrefix) {
  const ticker = useMarketStore((s) => s.tickers[streamPrefix])
  const setTicker = useMarketStore((s) => s.setTicker)

  const onTicker = useCallback(
    (data) => {
      setTicker(streamPrefix, {
        price: parseFloat(data.c) || 0,
        changePct: parseFloat(data.P) || 0,
        high: parseFloat(data.h) || 0,
        low: parseFloat(data.l) || 0,
        volume: parseFloat(data.v) || 0,
        quoteVolume: parseFloat(data.q) || 0,
      })
    },
    [streamPrefix, setTicker]
  )

  useBinanceWS(`${streamPrefix}@ticker`, onTicker)

  return ticker
}

export default useMarketStore
