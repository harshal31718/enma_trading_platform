// Plan 7 Step 7.5 (CLI-2/CLI-3): unit tests for the single-owner ticker
// store. `useMarketTicker` itself (the hook wrapping useBinanceWS) is
// exercised indirectly by the Trade.jsx render smoke test — this file
// covers the store's own contract: multiple symbols don't clobber each
// other, and updates are additive (setTicker for one symbol never drops
// another symbol's cached entry).
import { describe, test, expect, beforeEach } from 'vitest'
import useMarketStore from '../marketStore'

function resetStore() {
  useMarketStore.setState({ tickers: {} })
}

describe('marketStore', () => {
  beforeEach(resetStore)

  test('starts with no cached tickers', () => {
    expect(useMarketStore.getState().tickers).toEqual({})
  })

  test('setTicker stores a ticker keyed by symbol', () => {
    useMarketStore.getState().setTicker('BTCUSDT', { price: 65000, changePct: 1.2 })
    expect(useMarketStore.getState().tickers.BTCUSDT).toEqual({ price: 65000, changePct: 1.2 })
  })

  test('setTicker for one symbol does not affect another symbol already cached', () => {
    useMarketStore.getState().setTicker('BTCUSDT', { price: 65000 })
    useMarketStore.getState().setTicker('ETHUSDT', { price: 3200 })
    expect(useMarketStore.getState().tickers.BTCUSDT).toEqual({ price: 65000 })
    expect(useMarketStore.getState().tickers.ETHUSDT).toEqual({ price: 3200 })
  })

  test('a later setTicker for the same symbol replaces (not merges with) the prior entry', () => {
    useMarketStore.getState().setTicker('BTCUSDT', { price: 65000, changePct: 1.2 })
    useMarketStore.getState().setTicker('BTCUSDT', { price: 65100 })
    expect(useMarketStore.getState().tickers.BTCUSDT).toEqual({ price: 65100 })
  })
})
