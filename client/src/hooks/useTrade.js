import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/axios'

export function useTradeAccount(options = {}) {
  return useQuery({
    queryKey: ['trade', 'account'],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/account')
      return data.data
    },
    refetchInterval: 4000,
    staleTime: 3000,
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
    refetchInterval: 4000,
    staleTime: 3000,
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
    refetchInterval: 4000,
    staleTime: 3000,
    retry: false,
    ...options,
  })
}

export function useTradeSymbolConfig(symbol) {
  return useQuery({
    queryKey: ['trade', 'positions', symbol],
    queryFn: async () => {
      const { data } = await api.get('/api/v1/trade/positions', { params: { symbol } })
      return data.data?.[0] ?? null
    },
    enabled: !!symbol,
    retry: false,
  })
}

export function useChangeLeverage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, leverage }) =>
      api.post('/api/v1/trade/leverage', { symbol, leverage }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trade', 'positions'] })
      queryClient.invalidateQueries({ queryKey: ['trade', 'account'] })
    },
  })
}

export function useChangeMarginType() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, marginType }) =>
      api.post('/api/v1/trade/margin-type', { symbol, marginType }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trade', 'positions'] })
      queryClient.invalidateQueries({ queryKey: ['trade', 'account'] })
    },
  })
}

export function usePlaceOrder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, side, type, quantity, price }) =>
      api.post('/api/v1/trade/order', { symbol, side, type, quantity, price }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trade', 'positions'] })
      queryClient.invalidateQueries({ queryKey: ['trade', 'open-orders'] })
      queryClient.invalidateQueries({ queryKey: ['trade', 'account'] })
    },
  })
}

export function useCancelOrder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ symbol, orderId }) =>
      api.delete('/api/v1/trade/order', { params: { symbol, orderId } }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trade', 'open-orders'] })
      queryClient.invalidateQueries({ queryKey: ['trade', 'account'] })
    },
  })
}
