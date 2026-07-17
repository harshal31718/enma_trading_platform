import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/axios'
import socket from '@/lib/socket'

export function useTradeSettings() {
  return useQuery({
    queryKey: ['trade', 'settings', 'keys'],
    queryFn: async () => {
      const res = await api.get('/api/v1/trade/settings/keys')
      return res.data.data
    },
  })
}

export function useSaveTradeSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body) => {
      const res = await api.post('/api/v1/trade/settings/keys', body)
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trade', 'settings', 'keys'] })
    },
  })
}

function invalidateOrderState(queryClient) {
  queryClient.invalidateQueries({ queryKey: ['trade', 'positions'] })
  queryClient.invalidateQueries({ queryKey: ['trade', 'open-orders'] })
  queryClient.invalidateQueries({ queryKey: ['trade', 'account'] })
  queryClient.invalidateQueries({ queryKey: ['trade', 'symbol-config'] })
}

// Safety-net poll intervals only — real-time updates come from the manual
// trading WebSocket stream (see useTradeStream() below). These are
// deliberately long: they exist to reconcile against WS drops/reconnects,
// not to be the primary data source. See workspace/docs/features/live-trading/SPEC.md
// and workspace/docs/core/ARCHITECTURE.md rule 5 for why the old 3s/10s
// REST-polling intervals were a rate-limit risk shared across all users.
export function useTradeAccount(options = {}) {
  return useQuery({
    queryKey: ['trade', 'account'],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/account')
      return data.data
    },
    refetchInterval: 90000,
    staleTime: 60000,
    retry: false,
    ...options,
  })
}

// Combined testnet + mainnet balance snapshot for the Dashboard. Mainnet is
// read-only; both sides are polled server-side via GET /api/v1/trade/balances.
// Modest interval — this is a display, not the trading data source. When the
// manual-trade WebSocket is active (Trade page), useTradeStream() also
// invalidates this key on ACCOUNT_UPDATE so the testnet side stays push-fresh.
export function useAccountBalances(options = {}) {
  return useQuery({
    queryKey: ['trade', 'balances'],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/balances')
      return data.data
    },
    refetchInterval: 60000,
    staleTime: 45000,
    retry: false,
    ...options,
  })
}

export function useTradePositions(options = {}) {
  return useQuery({
    queryKey: ['trade', 'positions'],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/positions')
      return data.data
    },
    refetchInterval: 30000,
    staleTime: 20000,
    retry: false,
    ...options,
  })
}

export function useTradeOpenOrders(options = {}) {
  return useQuery({
    queryKey: ['trade', 'open-orders'],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/open-orders')
      return data.data
    },
    refetchInterval: 60000,
    staleTime: 45000,
    retry: false,
    ...options,
  })
}

// Statuses that mean an order is no longer "open" — removed from the
// open-orders cache rather than updated in place.
const _CLOSED_ORDER_STATUSES = new Set(['FILLED', 'CANCELED', 'EXPIRED', 'REJECTED'])

function _patchOpenOrdersCache(queryClient, orderEvent) {
  const orderId = orderEvent.i
  if (orderId == null) return

  queryClient.setQueryData(['trade', 'open-orders'], (prev) => {
    const list = Array.isArray(prev) ? prev : []
    const idx = list.findIndex((o) => o.orderId === orderId)

    if (_CLOSED_ORDER_STATUSES.has(orderEvent.X)) {
      if (idx === -1) return list
      return [...list.slice(0, idx), ...list.slice(idx + 1)]
    }

    const patched = {
      orderId,
      clientOrderId: orderEvent.c,
      symbol: orderEvent.s,
      status: orderEvent.X,
      side: orderEvent.S,
      type: orderEvent.o,
      timeInForce: orderEvent.f,
      price: orderEvent.p,
      origQty: orderEvent.q,
      executedQty: orderEvent.z,
      avgPrice: orderEvent.ap,
      stopPrice: orderEvent.sp,
      time: orderEvent.T,
      updateTime: orderEvent.T,
    }

    if (idx === -1) return [...list, patched]
    return [...list.slice(0, idx), { ...list[idx], ...patched }, ...list.slice(idx + 1)]
  })
}

/**
 * Starts this user's manual-trading Binance User Data Stream (real-time
 * order/account push over WebSocket) for the lifetime of the mounting
 * component — intended to be called once from the Trade page. Patches the
 * open-orders query cache directly on ORDER_TRADE_UPDATE (no REST round
 * trip); ACCOUNT_UPDATE (positions/balance) triggers a debounced
 * invalidation instead, since the event payload lacks markPrice/
 * liquidationPrice needed to render the Positions table, so those two
 * queries still need a real REST fetch — just event-driven instead of a
 * fixed short timer. The REST hooks above keep their own (now much longer)
 * refetchInterval as a safety net if the WebSocket drops.
 *
 * See workspace/docs/features/live-trading/SPEC.md and
 * engine/services/manual_trade_stream.py.
 */
const _HEARTBEAT_MS = 120000
const _ACCOUNT_UPDATE_DEBOUNCE_MS = 2000

export function useTradeStream() {
  const queryClient = useQueryClient()
  const debounceRef = useRef(null)

  useEffect(() => {
    let cancelled = false

    async function start() {
      try {
        await api.post('/api/v1/trade/stream/start')
      } catch {
        // Best-effort — REST safety-net polling still covers this user if
        // the stream can't start (e.g. no Binance credentials configured).
      }
    }

    start()
    const heartbeat = setInterval(start, _HEARTBEAT_MS)

    function handleStreamUpdate({ type, data }) {
      if (cancelled) return
      if (type === 'ORDER_TRADE_UPDATE') {
        _patchOpenOrdersCache(queryClient, data)
      } else if (type === 'ACCOUNT_UPDATE') {
        clearTimeout(debounceRef.current)
        debounceRef.current = setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: ['trade', 'positions'] })
          queryClient.invalidateQueries({ queryKey: ['trade', 'account'] })
          queryClient.invalidateQueries({ queryKey: ['trade', 'balances'] })
        }, _ACCOUNT_UPDATE_DEBOUNCE_MS)
      }
    }

    socket.connect()
    socket.on('trade:stream-update', handleStreamUpdate)

    return () => {
      cancelled = true
      clearInterval(heartbeat)
      clearTimeout(debounceRef.current)
      socket.off('trade:stream-update', handleStreamUpdate)
      api.post('/api/v1/trade/stream/stop').catch(() => {})
    }
  }, [queryClient])
}

export function useTradeSymbolConfig(symbol) {
  return useQuery({
    queryKey: ['trade', 'symbol-config', symbol],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/positions', { params: { symbol } })
      const positions = data.data || []
      return positions.find((p) => p.symbol === symbol) ?? null
    },
    enabled: !!symbol,
    refetchInterval: 15000,
    staleTime: 12000,
    retry: false,
  })
}

export function useChangeLeverage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, leverage }) =>
      api.post('/api/v1/trade/leverage', { symbol, leverage }),
    onSuccess: () => invalidateOrderState(queryClient),
  })
}

export function useChangeMarginType() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, marginType }) =>
      api.post('/api/v1/trade/margin-type', { symbol, marginType }),
    onSuccess: () => invalidateOrderState(queryClient),
  })
}

export function usePlaceOrder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, side, type, quantity, price }) =>
      api.post('/api/v1/trade/order', { symbol, side, type, quantity, price }),
    onSuccess: () => invalidateOrderState(queryClient),
  })
}

export function useClosePosition() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol }) =>
      api.post('/api/v1/trade/order/close', { symbol }).then((r) => r.data),
    onSuccess: () => invalidateOrderState(queryClient),
  })
}

export function useCancelOrder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, orderId }) =>
      api.delete('/api/v1/trade/order', { params: { symbol, orderId } }).then((r) => r.data),
    onSuccess: () => invalidateOrderState(queryClient),
  })
}

export function usePlaceOCOOrder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, side, quantity, stopPrice, takeProfitPrice }) =>
      api
        .post('/api/v1/trade/order/oco_futures', { symbol, side, quantity, stopPrice, takeProfitPrice })
        .then((r) => r.data.data),
    onSuccess: () => invalidateOrderState(queryClient),
  })
}

export function usePlaceOrderWithTpSl() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, side, type, quantity, price, stopLoss, takeProfit }) =>
      api
        .post('/api/v1/trade/order/with_tp_sl', { symbol, side, type, quantity, price, stopLoss, takeProfit })
        .then((r) => r.data.data),
    onSuccess: () => invalidateOrderState(queryClient),
  })
}

export function useTradeOrderStatus(symbol, orderId, options = {}) {
  return useQuery({
    queryKey: ['trade', 'order', symbol, orderId],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/order', { params: { symbol, orderId } })
      return data.data
    },
    enabled: !!symbol && !!orderId,
    retry: false,
    ...options,
  })
}

export function useCancelAllOrders() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol }) =>
      api.delete('/api/v1/trade/all-orders', { params: { symbol } }).then((r) => r.data.data),
    onSuccess: () => invalidateOrderState(queryClient),
  })
}

export function useTradeOrders(symbol, options = {}) {
  return useQuery({
    queryKey: ['trade', 'orders', symbol],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/order/history', { params: { symbol } })
      return data.data
    },
    enabled: !!symbol,
    retry: false,
    ...options,
  })
}

export function useTradeExecutions(symbol, options = {}) {
  return useQuery({
    queryKey: ['trade', 'executions', symbol],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/executions/history', { params: { symbol } })
      return data.data
    },
    enabled: !!symbol,
    retry: false,
    ...options,
  })
}

export function useTradeTransactions(symbol, options = {}) {
  return useQuery({
    queryKey: ['trade', 'transactions', symbol],
    queryFn: async () => {
      const params = symbol ? { symbol } : {}
      const { data } = await api.get('/api/v1/trade/transactions/history', { params })
      return data.data
    },
    retry: false,
    ...options,
  })
}
