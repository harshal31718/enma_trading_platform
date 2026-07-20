import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'

// Plan 7 Step 7.5 (CLI-2/CLI-3, "hooks share a factory"): collapses the
// invalidate-on-success(+toast) / extract-and-toast-on-error pattern that was
// duplicated across useAlgoSessions.js's 5 mutations verbatim (and, minus the
// toasts, useAlgoAccess.js's 2). Surveyed before writing this: the toast
// pattern specifically (`toast.success`/`toast.error(err.response?.data...)`)
// is concentrated in exactly these two files, not spread across all ~15
// hooks — other hook files' mutations either have genuinely different
// per-call side effects or deliberately push error handling to the calling
// component's local `errorMessage` state (client/CLAUDE.md's documented
// error-banner convention, e.g. useTrade.js) — this factory does not force a
// toast onto those, since `errorFallback`/`successMessage` are both optional.
export function useApiMutation({ mutationFn, invalidateKeys = [], successMessage, errorFallback }) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      invalidateKeys.forEach((key) => queryClient.invalidateQueries({ queryKey: key }))
      if (successMessage) toast.success(successMessage)
    },
    onError: errorFallback
      ? (err) => toast.error(err.response?.data?.error?.message || err.message || errorFallback)
      : undefined,
  })
}
