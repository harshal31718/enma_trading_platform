import { useEffect, useRef } from 'react'
import binanceWS from '@/lib/binanceWS'

/**
 * Subscribe to a Binance individual stream.
 * callback must be stable (useCallback or defined outside render).
 *
 * Uses a deferred unsubscribe (via ref swap) so React Strict Mode's
 * immediate unmount→remount cycle does not tear down and re-open the
 * WebSocket on every mount in development.
 */
export default function useBinanceWS(streamName, callback) {
  const unsubRef = useRef(null)

  useEffect(() => {
    unsubRef.current = binanceWS.subscribe(streamName, callback)
    return () => {
      const fn = unsubRef.current
      unsubRef.current = null
      if (fn) fn()
    }
  }, [streamName]) // eslint-disable-line react-hooks/exhaustive-deps
}
