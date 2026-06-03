import { useQuery } from '@tanstack/react-query'
import api from '../lib/axios'

export function useStrategies() {
  return useQuery({
    queryKey: ['strategies'],
    queryFn: async () => {
      const res = await api.get('/api/v1/strategies')
      return res.data.data.strategies
    },
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
  })
}
