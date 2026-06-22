import { useState, useCallback } from 'react'
import { Plus, Trash2, Bot, Zap } from 'lucide-react'
import { useAlgoSessions, useStopSession, useDeleteAllStopped } from '../hooks/useAlgoSessions'
import { useSocket } from '../hooks/useSocket'
import { useQueryClient } from '@tanstack/react-query'
import SessionCard from '../components/algo/SessionCard'
import NewSessionWizard from '../components/algo/NewSessionWizard'
import ChaosWizard from '../components/algo/ChaosWizard'
import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import { Dialog, DialogContent } from '../components/ui/dialog'

export default function AlgoTrading() {
  const [showWizard, setShowWizard] = useState(false)
  const [showChaosWizard, setShowChaosWizard] = useState(false)
  const [chaosError, setChaosError] = useState(null)
  const { data: sessions = [], isLoading } = useAlgoSessions()
  const stopSession = useStopSession()
  const deleteAllStopped = useDeleteAllStopped()
  const qc = useQueryClient()

  const hasStopped = sessions.some(s => s.status === 'stopped' || s.status === 'error')

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
        title="Algo Trading"
        actions={
          <div className="flex items-center gap-2">
            {hasStopped && (
              <button
                onClick={() => deleteAllStopped.mutate()}
                disabled={deleteAllStopped.isPending}
                className="flex items-center gap-2 px-3 py-2 bg-transparent hover:bg-red-500/10 text-gray-500 hover:text-red-400 text-sm rounded-lg border border-gray-700 hover:border-red-500/30 disabled:opacity-40 transition-all"
                title="Clear all stopped sessions"
              >
                <Trash2 size={14} />
                Clear stopped
              </button>
            )}
            <button
              onClick={() => setShowChaosWizard(true)}
              className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-purple-600 via-red-500 to-blue-600 hover:from-purple-500 hover:via-red-400 hover:to-blue-500 text-white text-sm rounded-lg shadow-lg transition-all font-semibold"
              title="Launch all strategies in stress-test mode (Binance Testnet only)"
            >
              <Zap size={14} />
              Chaos Mode
            </button>
            <button
              onClick={() => setShowWizard(true)}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg transition-colors"
            >
              <Plus size={16} />
              New Bot
            </button>
          </div>
        }
      />

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
            <div key={i} className="bg-gray-900 border-b border-gray-800 p-4 animate-pulse h-24" />
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <Bot size={48} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">No bots created yet. Click "New Bot" to get started.</p>
        </div>
      ) : (
        <div className="bg-title-bg border border-slate-700/50 rounded-xl overflow-hidden divide-y divide-slate-700/40 shadow-2xl">
          {sessions.map((session) => (
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
        <DialogContent className="w-[720px] max-w-[95vw] max-h-[90vh] overflow-y-auto overflow-x-hidden bg-title-bg">
          <NewSessionWizard
            onCancel={() => setShowWizard(false)}
            onSuccess={() => {
              setShowWizard(false)
              qc.invalidateQueries({ queryKey: ['algo', 'sessions'] })
            }}
          />
        </DialogContent>
      </Dialog>

      <Dialog open={showChaosWizard} onOpenChange={(open) => { if (!open) setShowChaosWizard(false) }}>
        <DialogContent className="max-w-4xl w-[95vw] max-h-[90vh] overflow-y-auto overflow-x-hidden bg-title-bg border-slate-700/50">
          <ChaosWizard
            onCancel={() => setShowChaosWizard(false)}
            onSuccess={() => {
              setShowChaosWizard(false)
              qc.invalidateQueries({ queryKey: ['algo', 'sessions'] })
            }}
          />
        </DialogContent>
      </Dialog>
    </PageWrapper>
  )
}
