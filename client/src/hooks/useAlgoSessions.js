import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/axios'

export function useAlgoSessions() {
  return useQuery({
    queryKey: ['algo', 'sessions'],
    queryFn: async () => {
      const res = await api.get('/api/v1/algo/sessions')
      return res.data.data.sessions
    },
    refetchInterval: 10000,
  })
}

export function useAlgoSession(id) {
  return useQuery({
    queryKey: ['algo', 'sessions', id],
    queryFn: async () => {
      const res = await api.get(`/api/v1/algo/sessions/${id}`)
      return res.data.data.session
    },
    enabled: !!id,
  })
}

export function useStartSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/v1/algo/sessions', payload)
      return res.data.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['algo', 'sessions'] })
    },
  })
}

export function useStopSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id) => {
      const res = await api.post(`/api/v1/algo/sessions/${id}/stop`)
      return res.data.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['algo', 'sessions'] })
    },
  })
}

export function useDeleteSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id) => {
      const res = await api.delete(`/api/v1/algo/sessions/${id}`)
      return res.data.data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['algo', 'sessions'] }),
  })
}

export function useDeleteAllStopped() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const res = await api.delete('/api/v1/algo/sessions')
      return res.data.data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['algo', 'sessions'] }),
  })
}

export function useStartChaos() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (config = {}) => {
      const res = await api.post('/api/v1/algo/chaos', config)
      return res.data.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['algo', 'sessions'] })
    },
  })
}

export function useLockedSymbols() {
  return useQuery({
    queryKey: ['algo', 'symbols', 'locked'],
    queryFn: async () => {
      const res = await api.get('/api/v1/algo/symbols/locked')
      return res.data.data.locked
    },
    staleTime: 5000,
  })
}

export function useChaosSymbols() {
  return useQuery({
    queryKey: ['algo', 'symbols', 'chaos'],
    queryFn: async () => {
      const res = await api.get('/api/v1/algo/chaos/symbols')
      return res.data.data.tieredSymbols
    },
    staleTime: 1000 * 60 * 60, // 1 hour (curated list)
  })
}

export function useStrategyParams(id) {
  return useQuery({
    queryKey: ['strategies', id, 'params'],
    queryFn: async () => {
      const res = await api.get(`/api/v1/strategies/${id}/params`)
      return res.data.data.params
    },
    enabled: !!id,
    staleTime: 60000,
  })
}
