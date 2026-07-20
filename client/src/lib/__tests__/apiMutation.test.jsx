// Plan 7 Step 7.5 (CLI-2/CLI-3, "hooks share a factory"): unit tests for the
// shared invalidate/toast mutation wrapper extracted out of useAlgoSessions.js
// (5 near-identical mutations) and useAlgoAccess.js (2 invalidate-only ones).
import { describe, test, expect, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { useApiMutation } from '../apiMutation'

vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
}))

function wrapper({ children }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useApiMutation', () => {
  afterEach(() => vi.clearAllMocks())

  test('calls mutationFn with the given argument and resolves its return value', async () => {
    const mutationFn = vi.fn().mockResolvedValue({ ok: true })
    const { result } = renderHook(() => useApiMutation({ mutationFn }), { wrapper })

    result.current.mutate('payload')
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(mutationFn.mock.calls[0][0]).toBe('payload')
    expect(result.current.data).toEqual({ ok: true })
  })

  test('shows a success toast only when successMessage is given', async () => {
    const mutationFn = vi.fn().mockResolvedValue({})
    const { result } = renderHook(
      () => useApiMutation({ mutationFn, successMessage: 'Done!' }),
      { wrapper }
    )

    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(toast.success).toHaveBeenCalledWith('Done!')
  })

  test('does not toast on success when successMessage is omitted (invalidate-only mutations)', async () => {
    const mutationFn = vi.fn().mockResolvedValue({})
    const { result } = renderHook(() => useApiMutation({ mutationFn }), { wrapper })

    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(toast.success).not.toHaveBeenCalled()
  })

  test('shows an error toast using the server message when errorFallback is given', async () => {
    const mutationFn = vi.fn().mockRejectedValue({
      response: { data: { error: { message: 'Server said no' } } },
    })
    const { result } = renderHook(
      () => useApiMutation({ mutationFn, errorFallback: 'Fallback message' }),
      { wrapper }
    )

    result.current.mutate()
    await waitFor(() => expect(result.current.isError).toBe(true))

    expect(toast.error).toHaveBeenCalledWith('Server said no')
  })

  test('falls back to errorFallback when the error has no server message', async () => {
    const mutationFn = vi.fn().mockRejectedValue(new Error())
    const { result } = renderHook(
      () => useApiMutation({ mutationFn, errorFallback: 'Fallback message' }),
      { wrapper }
    )

    result.current.mutate()
    await waitFor(() => expect(result.current.isError).toBe(true))

    expect(toast.error).toHaveBeenCalledWith('Fallback message')
  })

  test('does not toast on error when errorFallback is omitted (caller handles it locally)', async () => {
    const mutationFn = vi.fn().mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useApiMutation({ mutationFn }), { wrapper })

    result.current.mutate()
    await waitFor(() => expect(result.current.isError).toBe(true))

    expect(toast.error).not.toHaveBeenCalled()
  })

  test('invalidates every key in invalidateKeys on success', async () => {
    const mutationFn = vi.fn().mockResolvedValue({})
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const spy = vi.spyOn(queryClient, 'invalidateQueries')
    const localWrapper = ({ children }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(
      () => useApiMutation({ mutationFn, invalidateKeys: [['a', 'b'], ['c']] }),
      { wrapper: localWrapper }
    )

    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(spy).toHaveBeenCalledWith({ queryKey: ['a', 'b'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['c'] })
  })
})
