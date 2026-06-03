import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/axios'

export function useSymbols() {
  return useQuery({
    queryKey: ['candles', 'symbols'],
    queryFn: async () => {
      const res = await api.get('/api/v1/candles/symbols')
      return res.data.data
    },
  })
}

export function useAvailableImports() {
  return useQuery({
    queryKey: ['candles', 'available'],
    queryFn: async () => {
      const res = await api.get('/api/v1/candles/available')
      return res.data.data.imports
    },
  })
}

export function useImportCandles() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/v1/candles/import', payload)
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candles', 'available'] })
    },
  })
}
