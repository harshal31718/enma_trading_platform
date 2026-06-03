import { useQuery } from '@tanstack/react-query'
import api from '../lib/axios'

export function useDashboardStats() {
  return useQuery({
    queryKey: ['dashboard', 'stats'],
    queryFn: async () => {
      const res = await api.get('/api/v1/dashboard/stats')
      return res.data.data
    },
  })
}

export function useCachedCandles() {
  return useQuery({
    queryKey: ['candles', 'cached'],
    queryFn: async () => {
      const res = await api.get('/api/v1/candles/cached')
      return res.data.data
    },
  })
}
