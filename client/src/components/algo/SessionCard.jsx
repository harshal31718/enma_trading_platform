import { useState } from 'react'
import { ChevronDown, ChevronUp, Square } from 'lucide-react'

const STATUS_STYLES = {
  starting: 'bg-yellow-400/10 text-yellow-400 border border-yellow-400/20',
  running: 'bg-emerald-400/10 text-emerald-400 border border-emerald-400/20',
  stopping: 'bg-orange-400/10 text-orange-400 border border-orange-400/20',
  stopped: 'bg-gray-700/50 text-gray-400 border border-gray-600/20',
  error: 'bg-red-400/10 text-red-400 border border-red-400/20',
}

export default function SessionCard({ session, onStop, stopping }) {
  const [expanded, setExpanded] = useState(false)
  const pnlNum = parseFloat(session.pnl || '0')
  const isPositive = pnlNum >= 0

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div className="p-4 flex items-center gap-4">
        {/* Strategy + info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-100 truncate">{session.strategyName}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_STYLES[session.status] || STATUS_STYLES.stopped}`}>
              {session.status}
            </span>
          </div>
          <div className="flex items-center gap-3 text-xs text-gray-400">
            <span>{session.timeframe}</span>
            <span>·</span>
            <span>{session.symbols?.join(', ')}</span>
            {session.openPositions?.length > 0 && (
              <>
                <span>·</span>
                <span className="text-yellow-400">{session.openPositions.length} open</span>
              </>
            )}
          </div>
        </div>

        {/* PnL */}
        <div className="text-right">
          <div className={`text-lg font-semibold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}{pnlNum.toFixed(2)}
          </div>
          <div className="text-xs text-gray-500">Paper P&L</div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {session.status === 'running' && (
            <button
              onClick={(e) => { e.stopPropagation(); onStop() }}
              disabled={stopping}
              className="flex items-center gap-1 px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 text-xs rounded border border-red-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Square size={12} />
              {stopping ? 'Stopping...' : 'Stop'}
            </button>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 text-gray-500 hover:text-gray-300 transition-colors"
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-800 p-4 bg-gray-950/50">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div>
              <div className="text-gray-500 mb-1">Capital</div>
              <div className="text-gray-200">${parseFloat(session.capital || 0).toLocaleString()}</div>
            </div>
            <div>
              <div className="text-gray-500 mb-1">Leverage</div>
              <div className="text-gray-200">{session.leverage}x</div>
            </div>
            <div>
              <div className="text-gray-500 mb-1">Mode</div>
              <div className="text-gray-200 capitalize">{session.mode}</div>
            </div>
            <div>
              <div className="text-gray-500 mb-1">Started</div>
              <div className="text-gray-200">{new Date(session.createdAt).toLocaleDateString()}</div>
            </div>
          </div>
          {session.openPositions?.length > 0 && (
            <div className="mt-3">
              <div className="text-xs text-gray-500 mb-1">Open Positions</div>
              <div className="flex flex-wrap gap-1">
                {session.openPositions.map((sym) => (
                  <span key={sym} className="text-xs bg-yellow-400/10 text-yellow-400 px-2 py-0.5 rounded border border-yellow-400/20">
                    {sym}
                  </span>
                ))}
              </div>
            </div>
          )}
          {session.errorMessage && (
            <div className="mt-3 text-xs text-red-400 bg-red-950/20 border border-red-800/40 rounded p-2">
              {session.errorMessage}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
