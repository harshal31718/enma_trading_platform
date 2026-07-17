import { useState, useMemo } from 'react'
import { Shield, Check, X, AlertTriangle } from 'lucide-react'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import EmptyState from '@/components/ui/empty-state'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, SortableHeader } from '@/components/ui/table'
import { useTableSort } from '@/hooks/useTableSort'
import { useAdminUsers, useSetUserAlgoAccess } from '@/hooks/useAlgoAccess'
import { formatDate } from '@/utils/formatters'

const FILTERS = [
  { value: 'all', label: 'All Users' },
  { value: 'granted', label: 'Allowed' },
  { value: 'requested', label: 'Requested' },
  { value: 'none', label: 'No access' },
]

function StatusPill({ status }) {
  if (status === 'granted') {
    return <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-emerald-400/10 text-emerald-400 border border-emerald-500/20">Allowed</span>
  }
  if (status === 'requested') {
    return <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-amber-400/10 text-amber-400 border border-amber-500/20">Requested</span>
  }
  return <span className="text-slate-500 text-xs">—</span>
}

export default function AdminPanel() {
  const [filter, setFilter] = useState('all')
  const [confirmRevoke, setConfirmRevoke] = useState(null) // user row pending revoke

  const { data: users = [], isLoading, isError, error } = useAdminUsers()
  const setAccess = useSetUserAlgoAccess()

  const filtered = useMemo(() => {
    if (filter === 'all') return users
    return users.filter((u) => (u.algoAccess || 'none') === filter)
  }, [users, filter])

  const { sortedRows, sortState, onSort } = useTableSort(filtered)

  const requestedCount = useMemo(
    () => users.filter((u) => u.algoAccess === 'requested').length,
    [users]
  )

  function grant(id) {
    setAccess.mutate({ id, status: 'granted' })
  }

  return (
    <PageWrapper>
      <PageHeader title="Admin Panel" />

      <Card className="m-6">
        <CardHeader className="flex flex-row items-center justify-between gap-2 border-b border-slate-700/50">
          <div className="flex items-center gap-2">
            <Shield size={15} className="text-emerald-400" />
            <CardTitle className="text-sm font-medium">
              Users
              {requestedCount > 0 && (
                <span className="ml-2 inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium bg-amber-400/10 text-amber-400 border border-amber-500/20">
                  {requestedCount} awaiting
                </span>
              )}
            </CardTitle>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-400">
            Filter
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="h-8 border border-slate-700/50 bg-[#0a0d13] px-2 text-sm text-gray-100 focus:outline-none focus:border-emerald-500 transition-colors"
            >
              {FILTERS.map((f) => (
                <option key={f.value} value={f.value}>{f.label}</option>
              ))}
            </select>
          </label>
        </CardHeader>
        <CardContent className="p-0">
          {isError ? (
            <div className="flex items-start gap-2 bg-red-950/20 border border-red-800/40 p-4 m-4">
              <AlertTriangle size={14} className="text-red-400 mt-0.5 shrink-0" />
              <p className="text-red-400 text-xs">
                {error?.response?.data?.message ?? error?.message ?? 'Failed to load users.'}
              </p>
            </div>
          ) : isLoading ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-11 bg-slate-800/50 animate-pulse" />
              ))}
            </div>
          ) : sortedRows.length === 0 ? (
            <EmptyState
              title="No users"
              description="No users match the selected filter."
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHeader sortKey="name" sortState={sortState} onSort={onSort}>Name</SortableHeader>
                  <SortableHeader sortKey="email" sortState={sortState} onSort={onSort}>Email</SortableHeader>
                  <SortableHeader sortKey="role" sortState={sortState} onSort={onSort}>Role</SortableHeader>
                  <SortableHeader sortKey="algoAccess" sortState={sortState} onSort={onSort}>Status</SortableHeader>
                  <SortableHeader sortKey="createdAt" sortState={sortState} onSort={onSort}>Joined</SortableHeader>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedRows.map((u) => {
                  const isAdmin = u.role === 'admin'
                  const granted = u.algoAccess === 'granted'
                  return (
                    <TableRow key={u.id}>
                      <TableCell className="text-gray-200">{u.name}</TableCell>
                      <TableCell className="text-slate-400 font-mono text-xs">{u.email}</TableCell>
                      <TableCell>
                        <span className={isAdmin ? 'text-emerald-400 text-xs font-medium' : 'text-slate-400 text-xs'}>
                          {u.role}
                        </span>
                      </TableCell>
                      <TableCell>{isAdmin ? <span className="text-emerald-400 text-xs">Allowed</span> : <StatusPill status={u.algoAccess} />}</TableCell>
                      <TableCell className="text-slate-400 font-mono text-xs tabular-nums">{u.createdAt ? formatDate(u.createdAt) : '—'}</TableCell>
                      <TableCell className="text-right">
                        {isAdmin ? (
                          <span className="text-slate-500 text-xs">—</span>
                        ) : granted ? (
                          <button
                            onClick={() => setConfirmRevoke(u)}
                            disabled={setAccess.isPending}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-red-400 border border-red-800/40 hover:bg-red-500/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                          >
                            <X size={12} /> Revoke
                          </button>
                        ) : (
                          <button
                            onClick={() => grant(u.id)}
                            disabled={setAccess.isPending}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-emerald-400 border border-emerald-800/40 hover:bg-emerald-500/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                          >
                            <Check size={12} /> Grant
                          </button>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!confirmRevoke}
        onOpenChange={(v) => { if (!v) setConfirmRevoke(null) }}
        title="Revoke algo access?"
        description={`${confirmRevoke?.name ?? confirmRevoke?.email ?? 'This user'} will no longer be able to start bot sessions or Chaos Mode. Running sessions are unaffected.`}
        confirmLabel="Revoke"
        onConfirm={() => {
          const u = confirmRevoke
          setConfirmRevoke(null)
          if (u) setAccess.mutate({ id: u.id, status: 'none' })
        }}
      />
    </PageWrapper>
  )
}
