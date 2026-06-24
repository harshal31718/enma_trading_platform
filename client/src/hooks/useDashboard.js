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

export function useDashboardCalendar() {
  return useQuery({
    queryKey: ['dashboard', 'performance-calendar'],
    queryFn: async () => {
      const res = await api.get('/api/v1/dashboard/performance-calendar')
      return res.data.data
    },
    staleTime: 60_000,
  })
}
