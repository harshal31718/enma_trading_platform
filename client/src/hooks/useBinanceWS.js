import { useEffect } from 'react'
import binanceWS from '@/lib/binanceWS'

/**
 * Subscribe to a Binance combined-stream channel.
 * callback must be stable (useCallback or defined outside render) to avoid
 * re-subscribing on every render — callers are responsible for stability.
 *
 * @param {string} streamName  e.g. "btcusdt@ticker"
 * @param {function} callback  called with the `data` payload on each message
 */
export default function useBinanceWS(streamName, callback) {
  useEffect(() => {
    const unsubscribe = binanceWS.subscribe(streamName, callback)
    return unsubscribe
  }, [streamName]) // eslint-disable-line react-hooks/exhaustive-deps
  // callback intentionally omitted — callers must pass a stable reference;
  // re-subscribing on every callback identity change would flood the WS.
}
