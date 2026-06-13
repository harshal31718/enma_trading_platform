import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/axios'

export function useExchangeSettings() {
  return useQuery({
    queryKey: ['settings', 'exchange'],
    queryFn: async () => {
      const res = await api.get('/api/v1/settings/exchange')
      return res.data.data
    },
    staleTime: 5 * 60 * 1000,
  })
}

export function useUpdateExchangeSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (data) => {
      const res = await api.put('/api/v1/settings/exchange', data)
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'exchange'] })
    },
  })
}
