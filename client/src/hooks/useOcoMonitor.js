import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import api from '@/lib/axios'
import { useTradeOpenOrders } from './useTrade'

/**
 * Watches open orders for OCO leg disappearances.
 *
 * When a leg identified by clientOrderId starting with "oco_" vanishes from
 * the open-orders list, this hook fetches its final status.  If the final
 * status is FILLED it means the leg was triggered — the sibling must be
 * cancelled.  The sibling is found by swapping the "sl"/"tp" suffix and
 * looking it up in the most recent orders snapshot.
 *
 * onEvent(message: string) is called with a human-readable description so
 * the Trade page can show both a toast and a persistent banner.
 */
export default function useOcoMonitor({ symbol, onEvent }) {
  const queryClient = useQueryClient()
  const { data: openOrders } = useTradeOpenOrders()

  // Track the previous set of OCO clientOrderIds so we detect removals.
  const prevOcoMapRef = useRef({})   // clientOrderId → orderId

  useEffect(() => {
    if (!openOrders) return

    const currentOcoMap = {}
    for (const o of openOrders) {
      if (o.clientOrderId?.startsWith('oco_') || o.clientOrderId?.startsWith('tpsl_')) {
        currentOcoMap[o.clientOrderId] = o.orderId
      }
    }

    const prev = prevOcoMapRef.current
    const disappeared = Object.keys(prev).filter((cid) => !(cid in currentOcoMap))

    if (disappeared.length === 0) {
      prevOcoMapRef.current = currentOcoMap
      return
    }

    // For each disappeared OCO leg, fetch its final status asynchronously.
    for (const cid of disappeared) {
      const orderId = prev[cid]
      fetchAndHandleDisappeared(cid, orderId, symbol, currentOcoMap, queryClient, onEvent)
    }

    prevOcoMapRef.current = currentOcoMap
  }, [openOrders, symbol, queryClient, onEvent])
}

async function fetchAndHandleDisappeared(cid, orderId, symbol, currentOcoMap, queryClient, onEvent) {
  try {
    const { data: resp } = await api.get('/api/v1/trade/order', {
      params: { symbol, orderId },
    })
    const order = resp?.data
    if (!order || order.status !== 'FILLED') return

    // Determine leg type and find sibling clientOrderId
    const isSl = cid.endsWith('sl')
    const siblingCid = isSl ? cid.replace(/sl$/, 'tp') : cid.replace(/tp$/, 'sl')
    const siblingOrderId = currentOcoMap[siblingCid]

    const legLabel = isSl ? 'Stop-loss' : 'Take-profit'
    const siblingLabel = isSl ? 'take-profit' : 'stop-loss'

    if (siblingOrderId) {
      // Cancel the sibling leg
      try {
        await api.delete('/api/v1/trade/order', { params: { symbol, orderId: siblingOrderId } })
        onEvent?.(`${legLabel} triggered — ${siblingLabel} order cancelled.`)
      } catch {
        onEvent?.(`${legLabel} triggered — failed to cancel ${siblingLabel} order. Please cancel it manually.`)
      }
    } else {
      onEvent?.(`${legLabel} triggered.`)
    }

    // Refresh open orders and positions after handling
    queryClient.invalidateQueries({ queryKey: ['trade', 'open-orders'] })
    queryClient.invalidateQueries({ queryKey: ['trade', 'positions'] })
    queryClient.invalidateQueries({ queryKey: ['trade', 'account'] })
  } catch {
    // Silently ignore fetch errors — the order list will refresh on next poll
  }
}
