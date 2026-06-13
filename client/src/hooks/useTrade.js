import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/axios'

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
}

export function useTradeAccount(options = {}) {
  return useQuery({
    queryKey: ['trade', 'account'],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/account')
      return data.data
    },
    refetchInterval: 30000,
    staleTime: 25000,
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
    refetchInterval: 10000,
    staleTime: 8000,
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
    refetchInterval: 10000,
    staleTime: 8000,
    retry: false,
    ...options,
  })
}

export function useTradeSymbolConfig(symbol) {
  return useQuery({
    queryKey: ['trade', 'positions'],
    select: (positions) => positions?.find((p) => p.symbol === symbol) ?? null,
    enabled: !!symbol,
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
