import { useState, useCallback, useMemo, Suspense, lazy } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, Bot, Zap, Lock, Clock } from 'lucide-react'
import { useAlgoSessions, useStopSession, useDeleteAllStopped } from '../hooks/useAlgoSessions'
import { useAuth } from '../hooks/useAuth'
import { useSocket } from '../hooks/useSocket'
import { useQueryClient } from '@tanstack/react-query'
import SessionCard from '../components/algo/SessionCard'
import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import { Dialog, DialogContent } from '../components/ui/dialog'
import { ConfirmDialog } from '../components/ui/confirm-dialog'

const NewSessionWizard = lazy(() => import('../components/algo/NewSessionWizard'))
const ChaosWizard = lazy(() => import('../components/algo/ChaosWizard'))

export default function AlgoTrading() {
  const [showWizard, setShowWizard] = useState(false)
  const [showChaosWizard, setShowChaosWizard] = useState(false)
  const [chaosError, setChaosError] = useState(null)
  const [confirmClearOpen, setConfirmClearOpen] = useState(false)
  const { data: sessions = [], isLoading, isFetching } = useAlgoSessions()
  const { user, hasAlgoAccess } = useAuth()
  const stopSession = useStopSession()
  const deleteAllStopped = useDeleteAllStopped()
  const qc = useQueryClient()

  const accessPending = user?.algoAccess === 'requested'

  const hasStopped = sessions.some(s => s.status === 'stopped' || s.status === 'error')

  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      const aRunning = a.status === 'starting' || a.status === 'running' || a.status === 'stopping'
      const bRunning = b.status === 'starting' || b.status === 'running' || b.status === 'stopping'

      if (aRunning && !bRunning) return -1
      if (!aRunning && bRunning) return 1

      if (aRunning) {
        // Both running: last started first (newest createdAt first)
        const timeA = new Date(a.createdAt).getTime()
        const timeB = new Date(b.createdAt).getTime()
        return timeB - timeA
      } else {
        // Both stopped: last stopped first (newest stoppedAt / createdAt first)
        const timeA = new Date(a.stoppedAt || a.createdAt).getTime()
        const timeB = new Date(b.stoppedAt || b.createdAt).getTime()
        return timeB - timeA
      }
    })
  }, [sessions])

  // Real-time updates via Socket.IO
  const handleSessionUpdate = useCallback((data) => {
    qc.setQueryData(['algo', 'sessions'], (prev) => {
      if (!prev) return prev
      return prev.map((s) => {
        if (String(s._id) !== data.sessionId) return s
        // Merge only the fields present on this event — some updates carry just
        // symbolStats (per-symbol aggregation), others just status/pnl/positions.
        const next = { ...s }
        if (data.status !== undefined) next.status = data.status
        if (data.pnl !== undefined) next.pnl = data.pnl
        if (data.openPositions !== undefined) next.openPositions = data.openPositions
        if (data.symbolStats !== undefined) next.symbolStats = data.symbolStats
        return next
      })
    })
  }, [qc])

  useSocket('algo:session:update', handleSessionUpdate)

  const handleStop = async (id) => {
    try {
      await stopSession.mutateAsync(id)
    } catch (err) {
      console.error('Stop failed:', err)
    }
  }

  return (
    <PageWrapper>
      <PageHeader
        title={
          <div className="flex items-center gap-2">
            <span>Algo Trading</span>
            {isFetching && (
              <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-ping shrink-0" />
            )}
          </div>
        }
        actions={
          <div className="flex items-center gap-2">
            {hasStopped && (
              <>
                <button
                  onClick={() => setConfirmClearOpen(true)}
                  disabled={deleteAllStopped.isPending}
                  className="flex items-center gap-2 px-3 py-2 bg-transparent hover:bg-red-500/10 text-gray-500 hover:text-red-400 text-sm rounded-lg border border-gray-700 hover:border-red-500/30 disabled:opacity-40 transition-all"
                  title="Clear all stopped sessions"
                >
                  <Trash2 size={14} />
                  Clear stopped
                </button>
                <ConfirmDialog
                  open={confirmClearOpen}
                  onOpenChange={setConfirmClearOpen}
                  title="Clear all stopped sessions?"
                  description="This will permanently delete all stopped and errored sessions. This cannot be undone."
                  confirmLabel="Clear all"
                  onConfirm={() => { setConfirmClearOpen(false); deleteAllStopped.mutate() }}
                />
              </>
            )}
            <button
              onClick={() => setShowChaosWizard(true)}
              disabled={!hasAlgoAccess}
              aria-disabled={!hasAlgoAccess}
              className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-purple-600 via-red-500 to-blue-600 hover:from-purple-500 hover:via-red-400 hover:to-blue-500 text-white text-sm rounded-lg shadow-lg transition-all font-semibold disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:from-purple-600 disabled:hover:via-red-500 disabled:hover:to-blue-600"
              title={hasAlgoAccess ? 'Launch all strategies in stress-test mode (Binance Testnet only)' : 'Requires algo trading access'}
            >
              <Zap size={14} />
              Chaos Mode
            </button>
            <button
              onClick={() => setShowWizard(true)}
              disabled={!hasAlgoAccess}
              aria-disabled={!hasAlgoAccess}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-emerald-600"
              title={hasAlgoAccess ? 'Start a new bot session' : 'Requires algo trading access'}
            >
              <Plus size={16} />
              New Bot
            </button>
          </div>
        }
      />

      {/* Algo access banner — shown to users without granted access */}
      {!hasAlgoAccess && (
        accessPending ? (
          <div className="m-6 mb-0 bg-slate-800/30 border border-slate-600/40 rounded-lg px-4 py-3 flex items-start gap-2.5">
            <Clock size={16} className="text-slate-400 mt-0.5 shrink-0" />
            <p className="text-slate-300 text-sm">
              Your Algo Trading access request is <span className="text-slate-100 font-medium">pending admin approval</span>. You can explore the page, but starting bots is disabled until you're approved.
            </p>
          </div>
        ) : (
          <div className="m-6 mb-0 bg-amber-400/10 border border-amber-400/20 rounded-lg px-4 py-3 flex items-start gap-2.5">
            <Lock size={16} className="text-amber-400 mt-0.5 shrink-0" />
            <p className="text-amber-200 text-sm">
              Algo Trading requires access. You can view sessions here, but starting bots is admin-approved.{' '}
              <Link to="/settings" className="text-amber-400 font-medium underline underline-offset-2 hover:text-amber-300">
                Request access in Settings →
              </Link>
            </p>
          </div>
        )
      )}

      {/* Chaos error banner */}
      {chaosError && (
        <div className="mb-4 bg-red-950/20 border border-red-800/40 rounded-lg px-4 py-3 flex items-center justify-between">
          <span className="text-red-400 text-sm">{chaosError}</span>
          <button onClick={() => setChaosError(null)} className="text-red-400/60 hover:text-red-400 text-xs ml-4">✕</button>
        </div>
      )}

      {/* Sessions list */}
      {isLoading ? (
        <div className="border border-slate-700/50">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-slate-800/20 border-b border-slate-700/30 p-4 animate-pulse h-24" />
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <Bot size={48} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">No bots created yet. Click "New Bot" to get started.</p>
        </div>
      ) : (
        <div className="bg-title-bg border border-slate-700/50 rounded-xl overflow-hidden divide-y divide-slate-700/40 shadow-2xl">
          {sortedSessions.map((session) => (
            <SessionCard
              key={String(session._id)}
              session={session}
              onStop={() => handleStop(String(session._id))}
              stopping={
                stopSession.isPending &&
                stopSession.variables === String(session._id)
              }
            />
          ))}
        </div>
      )}

      <Dialog open={showWizard} onOpenChange={(open) => { if (!open) setShowWizard(false) }}>
        <DialogContent className="w-[920px] max-w-[95vw] max-h-[88vh] flex flex-col overflow-hidden gap-0 p-0 bg-title-bg">
          <Suspense fallback={<div className="p-8 text-center font-mono text-xs text-slate-400">Loading Wizard...</div>}>
            <NewSessionWizard
              onCancel={() => setShowWizard(false)}
              onSuccess={() => {
                setShowWizard(false)
                qc.invalidateQueries({ queryKey: ['algo', 'sessions'] })
              }}
            />
          </Suspense>
        </DialogContent>
      </Dialog>

      <Dialog open={showChaosWizard} onOpenChange={(open) => { if (!open) setShowChaosWizard(false) }}>
        <DialogContent className="w-[920px] max-w-[95vw] max-h-[88vh] flex flex-col overflow-hidden gap-0 p-0 bg-title-bg border-slate-700/50">
          <Suspense fallback={<div className="p-8 text-center font-mono text-xs text-slate-400">Loading Wizard...</div>}>
            <ChaosWizard
              onCancel={() => setShowChaosWizard(false)}
              onSuccess={() => {
                setShowChaosWizard(false)
                qc.invalidateQueries({ queryKey: ['algo', 'sessions'] })
              }}
            />
          </Suspense>
        </DialogContent>
      </Dialog>
    </PageWrapper>
  )
}
