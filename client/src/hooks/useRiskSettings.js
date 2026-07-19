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

// useBacktestSimulation removed (Plan 10 Phase 2) — its endpoint
// (GET /api/v1/risk/backtest/:id/simulation) is retired (410); use
// useRunMonteCarlo/useSimulation from hooks/useLab.js instead.
