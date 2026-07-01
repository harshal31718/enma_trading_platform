import { useQuery } from '@tanstack/react-query'
import api from '../lib/axios'

export function useOrderHistory({ page = 1, limit = 50, filters = {}, sort, order } = {}) {
  return useQuery({
    queryKey: ['order-history', page, limit, filters, sort, order],
    queryFn: async () => {
      const params = new URLSearchParams()
      params.set('page', page)
      params.set('limit', limit)
      if (sort) params.set('sort', sort)
      if (order) params.set('order', order)

      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          params.set(key, value)
        }
      })

      con