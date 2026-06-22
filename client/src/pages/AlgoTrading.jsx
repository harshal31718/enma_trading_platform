import { useState, useCallback } from 'react'
import { Plus, Trash2, Bot, Zap } from 'lucide-react'
import { useAlgoSessions, useStopSession, useDeleteAllStopped, useStartChaos } from '../hooks/useAlgoSessions'
import { useSocket } from '../hooks/useSocket'
import { useQueryClient } from '@tanstack/react-query'
import SessionCard from '../components/algo/SessionCard'
import NewSessionWizard from '../components/algo/NewSessionWizard'
import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'

export default function AlgoTrading() {
  const [showWizard, setShowWizard] = useState(false)
  const [chaosError, setChaosError] = useState(null)
  const [showChaosConfirm, setShowChaosConfirm] = useState(false)
  const { data: sessions = [], isLoading } = useAlgoSessions()
  const stopSession = useStopSession()
  const deleteAllStopped = useDeleteAllStopped()
  const startChaos = useStartChaos()
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

  const handleChaosConfirm = async () => {
    setShowChaosConfirm(false)
    setChaosError(null)
    try {
      const result = await startChaos.mutateAsync()
      if (result.errors?.length && !result.launched?.length) {
        setChaosError(`Chaos launch failed: ${result.errors.map(e => e.error).join('; ')}`)
      }
    } catch (err) {
      setChaosError(err?.response?.data?.message || err.message || 'Chaos launch failed')
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
              onClick={() => setShowChaosConfirm(true)}
              disabled={startChaos.isPending || showChaosConfirm}
              className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-purple-600 via-red-500 to-blue-600 hover:from-purple-500 hover:via-red-400 hover:to-blue-500 text-white text-sm rounded-lg shadow-lg disabled:opacity-40 transition-all"
              title="Launch all strategies in stress-test mode (Binance Testnet only)"
            >
              <Zap size={14} />
              {startChaos.isPending ? 'Launching…' : 'Chaos Mode'}
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

      {/* Chaos Mode confirm panel — inline, non-blocking */}
      {showChaosConfirm && (
        <div className="mb-4 bg-amber-950/20 border border-amber-500/30 rounded-lg px-4 py-3">
          <p className="text-amber-300 text-sm font-medium mb-1">⚡ Chaos Mode — Binance Testnet Only</p>
          <p className="text-gray-400 text-xs mb-3">
            Launches all 5 strategies with high-volatility params on 1m timeframe.
            Symbols BTC, ETH, SOL, BNB, XRP, DOGE, ADA will be locked for manual trading until stopped.
          </p>
          <div className="flex gap-2">
            <button
              onClick={handleChaosConfirm}
              className="px-3 py-1.5 bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 text-xs rounded border border-amber-500/40 transition-colors"
            >
              Launch
            </button>
            <button
              onClick={() => setShowChaosConfirm(false)}
              className="px-3 py-1.5 text-gray-400 hover:text-gray-200 text-xs rounded border border-gray-700 hover:border-gray-600 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
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
