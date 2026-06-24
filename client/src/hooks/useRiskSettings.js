import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/axios'

export function useRiskSettings() {
  return useQuery({
    queryKey: ['risk', 'settings'],
    queryFn: async () => {
      const res = await api.get('/api/v1/risk/settings')
      return res.data.data
    },
    staleTime: 1 * 60 * 1000,
  })
}

export function useUpdateRiskSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (data) => {
      const res = await api.put('/api/v1/risk/settings', data)
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['risk', 'settings'] })
    },
  })
}

export function useLiveRiskMetrics() {
  return useQuery({
    queryKey: ['risk', 'live-metrics'],
    queryFn: async () => {
      const res = await api.get('/api/v1/risk/live-metrics')
      return res.data.data
    },
    refetchInterval: 10000, // Refresh every 10s to match Redis cache expiry
    refetchIntervalInBackground: false,
    staleTime: 9000,
  })
}

export function useBacktestSimulation(jobId) {
  return useQuery({
    queryKey: ['risk', 'backtest-simulation', jobId],
    queryFn: async () => {
      if (!jobId) return null
      const res = await api.get(`/api/v1/risk/backtest/${jobId}/simulation`)
      return res.data.data
    },
    enabled: !!jobId,
    staleTime: Infinity, // Benchmark/backtest simulations are immutable once computed
  })
}
