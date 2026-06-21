import { useQuery } from '@tanstack/react-query'
import api from '../lib/axios'

export function useOrderHistory({ page = 1, limit = 50, filters = {} } = {}) {
  return useQuery({
    queryKey: ['order-history', page, limit, filters],
    queryFn: async () => {
      const params = new URLSearchParams()
      params.set('page', page)
      params.set('limit', limit)

      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          params.set(key, value)
        }
      })

      const res = await api.get(`/api/v1/order-history?${params.toString()}`)
      return res.data.data
    },
  })
}