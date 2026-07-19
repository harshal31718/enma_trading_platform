import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/axios'

// Plan 10 Phase 2 — Strategy Lab (Monte Carlo robustness tab).
// Mirrors useBacktest.js's job-lifecycle pattern exactly: mutation to enqueue,
// query-by-id for status/results (staleTime Infinity once the job reaches a
// terminal state — labResults are immutable once completed/failed), query
// for the history rail.

export function useRunMonteCarlo() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ sourceJobId, ...config }) => {
      const res = await api.post('/api/v1/lab/simulations', { sourceJobId, ...config })
      return res.data.data
    },
    onSuccess: (_, { sourceJobId }) => {
      queryClient.invalidateQueries({ queryKey: ['lab', 'simulations', 'list', sourceJobId] })
    },
  })
}

export function useSimulation(labId) {
  return useQuery({
    queryKey: ['lab', 'simulations', labId],
    queryFn: async () => {
      const res = await api.get(`/api/v1/lab/simulations/${labId}`)
      return res.data.data
    },
    enabled: !!labId,
    staleTime: (query) =>
      ['completed', 'failed'].includes(query.state.data?.status) ? Infinity : 0,
  })
}

export function useSimulationsList(sourceJobId, limit = 20) {
  return useQuery({
    queryKey: ['lab', 'simulations', 'list', sourceJobId ?? 'all', limit],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (sourceJobId) params.set('sourceJobId', sourceJobId)
      params.set('limit', limit)
      const res = await api.get(`/api/v1/lab/simulations?${params.toString()}`)
      return res.data.data.simulations
    },
  })
}

// Plan 10 Phase 3a/3c — walk-forward optimization jobs. Same lifecycle shape
// as the MC hooks above, at /api/v1/lab/optimizations instead.
export function useRunOptimization() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (config) => {
      const res = await api.post('/api/v1/lab/optimizations', config)
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lab', 'optimizations', 'list'] })
    },
  })
}

export function useOptimization(labId) {
  return useQuery({
    queryKey: ['lab', 'optimizations', labId],
    queryFn: async () => {
      const res = await api.get(`/api/v1/lab/optimizations/${labId}`)
      return res.data.data
    },
    enabled: !!labId,
    staleTime: (query) =>
      ['completed', 'failed'].includes(query.state.data?.status) ? Infinity : 0,
  })
}

export function useObjectives() {
  return useQuery({
    queryKey: ['lab', 'objectives'],
    queryFn: async () => {
      const res = await api.get('/api/v1/lab/objectives')
      return res.data.data.objectives
    },
    staleTime: Infinity, // the objective registry is static engine code, not user data
  })
}

export function useOptimizationsList(limit = 20) {
  return useQuery({
    queryKey: ['lab', 'optimizations', 'list', limit],
    queryFn: async () => {
      const res = await api.get(`/api/v1/lab/optimizations?limit=${limit}`)
      return res.data.data.optimizations
    },
  })
}

// Plan 10 — PBO (Probability of Backtest Overfitting). Same lifecycle shape as the
// optimization hooks above, at /api/v1/lab/pbo instead.
export function useRunPBO() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (config) => {
      const res = await api.post('/api/v1/lab/pbo', config)
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lab', 'pbo', 'list'] })
    },
  })
}

export function usePBO(labId) {
  return useQuery({
    queryKey: ['lab', 'pbo', labId],
    queryFn: async () => {
      const res = await api.get(`/api/v1/lab/pbo/${labId}`)
      return res.data.data
    },
    enabled: !!labId,
    staleTime: (query) =>
      ['completed', 'failed'].includes(query.state.data?.status) ? Infinity : 0,
  })
}

export function usePBOList(limit = 20) {
  return useQuery({
    queryKey: ['lab', 'pbo', 'list', limit],
    queryFn: async () => {
      const res = await api.get(`/api/v1/lab/pbo?limit=${limit}`)
      return res.data.data.runs
    },
  })
}
