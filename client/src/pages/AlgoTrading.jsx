import { useState, useCallback } from 'react'
import { Plus, Trash2, Bot } from 'lucide-react'
import { useAlgoSessions, useStopSession, useDeleteAllStopped } from '../hooks/useAlgoSessions'
import { useSocket } from '../hooks/useSocket'
import { useQueryClient } from '@tanstack/react-query'
import SessionCard from '../components/algo/SessionCard'
import NewSessionWizard from '../components/algo/NewSessionWizard'
import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'

export default function AlgoTrading() {
  const [showWizard, setShowWizard] = useState(false)
  const { data: sessions = [], isLoading } = useAlgoSessions()
  const stopSession = useStopSession()
  const deleteAllStopped = useDeleteAllStopped()
  const qc = useQueryClient()

  const hasStopped = sessions.some(s => s.status === 'stopped' || s.status === 'error')

  // Real-time updates via Socket.IO
  const handleSessionUpdate = useCallback((data) => {
    qc.setQueryData(['algo', 'sessions'], (prev) => {
      if (!prev) return prev
      return prev.map((s) =>
        String(s._id) === data.sessionId
          ? { ...s, status: data.status, pnl: data.pnl, openPositions: data.openPositions }
          : s
      )
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

  if (showWizard) {
    return (
      <PageWrapper>
        <NewSessionWizard
          onCancel={() => setShowWizard(false)}
          onSuccess={() => {
            setShowWizard(false)
            qc.invalidateQueries({ queryKey: ['algo', 'sessions'] })
          }}
        />
      </PageWrapper>
    )
  }

  return (
    <PageWrapper>
      <PageHeader
        title="Algo Trading"
        description="Automated trading bots · Binance Testnet"
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
              onClick={() => setShowWizard(true)}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg transition-colors"
            >
              <Plus size={16} />
              New Bot
            </button>
          </div>
        }
      />

      {/* Sessions list */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-gray-900 border border-gray-800 rounded-lg p-4 animate-pulse h-24" />
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <Bot size={48} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">No bots created yet. Click "New Bot" to get started.</p>
        </div>
      ) : (
        <div className="space-y-3">
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
    </PageWrapper>
  )
}
