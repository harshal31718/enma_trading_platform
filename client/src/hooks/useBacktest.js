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

export function useBacktestsList(page = 1, limit = 20) {
  return useQuery({
    queryKey: ['backtests', page, limit],
    queryFn: async () => {
      const res = await api.get(`/api/v1/backtest?page=${page}&limit=${limit}`)
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
