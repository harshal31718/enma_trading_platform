import { useQuery } from '@tanstack/react-query'
import api from '../lib/axios'

export function useSymbols() {
  return useQuery({
    queryKey: ['candles', 'symbols'],
    queryFn: async () => {
      const res = await api.get('/api/v1/candles/symbols')
      return res.data.data
    },
    staleTime: 1000 * 60 * 10,
    gcTime: 1000 * 60 * 30,
  })
}
