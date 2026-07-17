import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/axios'

export function useRunBacktest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (data) => {
      const res = await api.post('/api/v1/backtest', data)
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backtests'] })
    },
  })
}

export function useBacktestsList(page = 1, limit = 20, filters = {}) {
  return useQuery({
    queryKey: ['backtests', page, limit, filters],
    queryFn: async () => {
      const params = new URLSearchParams()
      params.set('page', page)
      params.set('limit', limit)

      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          params.set(key, value)
        }
      })

      const res = await api.get(`/api/v1/backtest?${params.toString()}`)
      return res.data.data
    },
  })
}

export function useBacktestResult(id) {
  return useQuery({
    queryKey: ['backtests', id],
    queryFn: async () => {
      const res = await api.get(`/api/v1/backtest/${id}`)
      return res.data.data
    },
    enabled: !!id,
    staleTime: (query) =>
      ['completed', 'failed', 'cancelled'].includes(query.state.data?.status) ? Infinity : 0,
  })
}

export function useBacktestTrades(id, page = 1, limit = 50) {
  return useQuery({
    queryKey: ['backtests', id, 'trades', page, limit],
    queryFn: async () => {
      const res = await api.get(`/api/v1/backtest/${id}/trades?page=${page}&limit=${limit}`)
      return res.data.data
    },
    enabled: !!id,
  })
}

export function useAllBacktestTrades(id) {
  return useQuery({
    queryKey: ['backtests', id, 'trades', 'all'],
    queryFn: async () => {
      // Use the newly increased limit to get up to 5000 trades
      const res = await api.get(`/api/v1/backtest/${id}/trades?page=1&limit=5000`)
      return res.data.data.trades
    },
    enabled: !!id,
  })
}

// Normalized Buy & Hold series (capital × close/firstClose) aligned 1:1 with the
// equity curve. Derived from immutable saved candle data → cache indefinitely.
export function useBacktestBenchmark(id) {
  return useQuery({
    queryKey: ['backtests', id, 'benchmark'],
    queryFn: async () => {
      const res = await api.get(`/api/v1/backtest/${id}/benchmark`)
      return res.data.data.benchmark
    },
    enabled: !!id,
    staleTime: Infinity,
  })
}

export function useCancelBacktest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id) => {
      const res = await api.post(`/api/v1/backtest/${id}/cancel`)
      return res.data.data
    },
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ['backtests'] })
      queryClient.invalidateQueries({ queryKey: ['backtests', id] })
    },
  })
}
