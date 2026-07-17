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

// Plan 14 / fixes-queue F3: one-shot delivery test against a URL that may not
// be saved yet — lets the Settings page's "Send Test" button verify
// connectivity before the user commits to "Save".
export function useTestWebhook() {
  return useMutation({
    mutationFn: async ({ url, format, timeoutMs }) => {
      const res = await api.post('/api/v1/settings/webhook/test', { url, format, timeoutMs })
      return res.data.data
    },
  })
}
