import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Shield, Plus, Trash2, AlertTriangle } from 'lucide-react'
import api from '../lib/axios'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'

export default function AdminPanel() {
  const queryClient = useQueryClient()
  const [newEmail, setNewEmail] = useState('')
  const [confirmRemoveEmail, setConfirmRemoveEmail] = useState(null)

  const { data: emails = [], isLoading } = useQuery({
    queryKey: ['admin', 'allowed-emails'],
    queryFn: async () => {
      const res = await api.get('/api/v1/admin/allowed-emails')
      return res.data.data
    },
  })

  const addMutation = useMutation({
    mutationFn: async (email) => {
      const res = await api.post('/api/v1/admin/allowed-emails', { email })
      return res.data.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'allowed-emails'] })
      setNewEmail('')
    },
  })

  const removeMutation = useMutation({
    mutationFn: async (email) => {
      await api.delete(`/api/v1/admin/allowed-emails/${encodeURIComponent(email)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'allowed-emails'] })
    },
  })

  function handleAdd(e) {
    e.preventDefault()
    const trimmed = newEmail.trim()
    if (!trimmed) return
    addMutation.mutate(trimmed)
  }

  return (
    <PageWrapper>
      <PageHeader title="Admin Panel" />

      <div className="mx-auto max-w-2xl">
        <div className="bg-title-bg border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center gap-2 -mx-6 -mt-6 px-6 py-4 mb-6 rounded-t-xl title-fade border-b border-slate-700/50">
            <Shield size={15} className="text-emerald-400" />
            <h2 className="text-gray-100 text-sm font-medium">Email Whitelist</h2>
          </div>

          {addMutation.isError && (
            <div className="flex items-start gap-2 bg-red-950/20 border border-red-800/40 rounded-lg p-3 mb-4">
              <AlertTriangle size={14} className="text-red-400 mt-0.5 shrink-0" />
              <p className="text-red-400 text-xs">
                {addMutation.error?.response?.data?.message ?? addMutation.error?.message ?? 'Failed to add email.'}
              </p>
            </div>
          )}

          <form onSubmit={handleAdd} className="flex gap-2 mb-6">
            <input
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              placeholder="user@example.com"
              className="flex-1 h-10 rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 text-sm text-gray-100 focus:outline-none focus:border-emerald-500 transition-colors"
            />
            <button
              type="submit"
              disabled={addMutation.isPending || !newEmail.trim()}
              className="inline-flex items-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
            >
              <Plus size={14} />
              Add
            </button>
          </form>

          <ConfirmDialog
            open={!!confirmRemoveEmail}
            onOpenChange={(v) => { if (!v) setConfirmRemoveEmail(null) }}
            title="Remove from whitelist?"
            description={`${confirmRemoveEmail} will lose access immediately.`}
            confirmLabel="Remove"
            onConfirm={() => { const e = confirmRemoveEmail; setConfirmRemoveEmail(null); removeMutation.mutate(e) }}
          />

          {isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-10 bg-slate-800/50 rounded-lg animate-pulse" />
              ))}
            </div>
          ) : emails.length === 0 ? (
            <p className="text-slate-400 text-sm text-center py-4">No emails on the whitelist yet.</p>
          ) : (
            <ul className="space-y-2">
              {emails.map((item) => (
                <li
                  key={item.email}
                  className="flex items-center justify-between px-3 py-2.5 rounded-lg border border-slate-700/30 bg-slate-800/20"
                >
                  <span className="text-sm text-gray-200">{item.email}</span>
                  <button
                    onClick={() => setConfirmRemoveEmail(item.email)}
                    className="p-1.5 rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                    aria-label={`Remove ${item.email}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </PageWrapper>
  )
}
