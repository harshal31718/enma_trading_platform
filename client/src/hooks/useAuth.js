import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../lib/axios'

export function useAuth() {
  const { data, isLoading } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v1/auth/me')
        return res.data.data
      } catch (err) {
        if (err.response?.status === 401) return null
        throw err
      }
    },
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  const user = data ?? null
  return {
    user,
    isLoading,
    isAuthenticated: !!data,
    // Admins always have algo access; other users need an explicit grant.
    hasAlgoAccess: user?.role === 'admin' || user?.algoAccess === 'granted',
  }
}

export function useLogout() {
  const queryClient = useQueryClient()
  return async () => {
    try {
      await api.post('/api/v1/auth/logout')
    } finally {
      queryClient.clear()
      window.location.href = '/login'
    }
  }
}
