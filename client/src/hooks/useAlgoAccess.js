import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/axios'

// User-side: request Algo Trading access. Refreshes the auth query so the new
// status ('requested') is reflected in the UI immediately.
export function useRequestAlgoAccess() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/v1/algo/access-request')
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
    },
  })
}

// Admin-side: list all users with their algo-access status.
export function useAdminUsers() {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: async () => {
      const res = await api.get('/api/v1/admin/users')
      return res.data.data
    },
  })
}

// Admin-side: grant ('granted') or revoke ('none') a user's algo access.
export function useSetUserAlgoAccess() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, status }) => {
      const res = await api.patch(`/api/v1/admin/users/${id}/algo-access`, { status })
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
  })
}
