import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/axios'

export function useStrategies() {
  return useQuery({
    queryKey: ['strategies'],
    queryFn: async () => {
      const res = await api.get('/api/v1/strategies')
      return res.data.data.strategies
    },
    staleTime: 1000 * 60 * 5,
    gcTime: 1000 * 60 * 15,
  })
}

export function useStrategyCode(id) {
  return useQuery({
    queryKey: ['strategies', id, 'code'],
    queryFn: async () => {
      const res = await api.get(`/api/v1/strategies/${id}/code`)
      return res.data.data.code
    },
    enabled: !!id,
    staleTime: 1000 * 60 * 5,
    gcTime: 1000 * 60 * 15,
  })
}

export function useCreateStrategy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/v1/strategies', payload)
      return res.data.data.strategy
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['strategies'] })
    },
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
    staleTime: 1000 * 60 * 5,
    gcTime: 1000 * 60 * 15,
  })
}
