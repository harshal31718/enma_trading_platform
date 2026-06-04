import { useState, useEffect, useCallback } from 'react'
import { ChevronDown, ChevronUp, Square, ArrowUpCircle, ArrowDownCircle, CheckCircle2, Info, AlertTriangle, Activity, Trash2, TrendingUp, BarChart2, ScrollText } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, YAxis, ReferenceLine } from 'recharts'
import { useSocket } from '../../hooks/useSocket'
import { useDeleteSession } from '../../hooks/useAlgoSessions'
import useBinanceWS from '../../hooks/useBinanceWS'

const STATUS_STYLES = {
  starting: 'bg-yellow-400/10 text-yellow-400 border border-yellow-400/20',
  running: 'bg-emerald-400/10 text-emerald-400 border border-emerald-400/20',
  stopping: 'bg-orange-400/10 text-orange-400 border border-orange-400/20',
  stopped: 'bg-gray-700/50 text-gray-400 border border-gray-600/20',
  error: 'bg-red-400/10 text-red-400 border border-red-400/20',
}

const LogIcon = ({ type }) => {
  switch (type) {
    case 'long': return <ArrowUpCircle size={13} className="text-emerald-400 shrink-0 mt-px" />
    case 'short': return <ArrowDownCircle size={13} className="text-red-400 shrink-0 mt-px" />
    case 'closed': return <CheckCircle2 size={13} className="text-gray-500 shrink-0 mt-px" />
    case 'error': return <AlertTriangle size={13} className="text-amber-400 shrink-0 mt-px" />
    default: return <Info size={13} className="text-gray-500 shrink-0 mt-px" />
  }
}

export default function SessionCard({ session, onStop, stopping }) {
  const [expanded, setExpanded] = useState(false)
  const [equity, setEquity] = useState([])
  const [logs, setLogs] = useState(() => [...(session.logs || [])].reverse())
  const [positionDetails, setPositionDetails] = useState({})
  const [prices, setPrices] = useState({})
  const deleteSession = useDeleteSession()

  const onTickers = useCallback((payload) => {
    if (!Array.isArray(payload)) return
    setPrices(prev => {
      const next = { ...prev }
      for (const item of payload) next[item.s] = parseFloat(item.c)
      return next
    })
  }, [])

  useBinanceWS('!ticker@arr', onTickers)

  const pnlNum = parseFloat(session.pnl || '0')
  const isPositive = pnlNum >= 0
  const isStopped = session.status === 'stopped'
  const baselineVal = parseFloat(session.capital || 0)
  const currentVal = baselineVal + pnlNum

  useEffect(() => {
    if (expanded && !isStopped) {
      fetch(`/api/v1/algo/sessions/${session._id}/equity`)
        .then(res => res.json())
        .then(data => setEquity(data.data?.equity || []))
        .catch(console.error)
    }
  }, [expanded, isStopped, session._id])

  const handleLog = useCallback((data) => {
    if (String(data.sessionId) === String(session._id)) {
      setLogs(prev => {
        const next = [data, ...prev]
        if (next.length > 50) next.length = 50
        return next
      })
    }
  }, [session._id])

  useSocket('algo:session:log', handleLog)

  useSocket('algo:position:open', (data) => {
    if (String(data.sessionId) === String(session._id)) {
      setPositionDetails(prev => ({
        ...prev,
        [data.symbol]: { side: data.side, qty: data.qty, price: data.price }
      }))
    }
  })

  useSocket('algo:position:close', (data) => {
    if (String(data.sessionId) === String(session._id)) {
      setPositionDetails(prev => {
        const next = { ...prev }
        delete next[data.symbol]
        return next
      })
    }
  })

  const formatStarted = (dateString) => {
    if (!dateString) return ''
    const d = new Date(dateString)
    return `${d.toLocaleTimeString([], { hour12: false })} ${d.toLocaleDateString()}`
  }

  const chartData = equity.length > 0
    ? equity
    : [{ timestamp: new Date().toISOString(), balance: session.capital }, { timestamp: new Date().toISOString(), balance: session.capital }]
  const minBalance = Math.min(...chartData.map(d => parseFloat(d.balance))) * 0.99
  const maxBalance = Math.max(...chartData.map(d => parseFloat(d.balance))) * 1.01

  const totalTrades = session.totalTrades || 0

  return (
    <div className="bg-[#1C1C1C] border border-[#2E2E2E] rounded-xl overflow-hidden shadow-lg transition-all duration-300">

      {/* ── Header row ── */}
      <div
        className="px-5 py-3.5 flex items-center gap-4 cursor-pointer hover:bg-white/[0.02] transition-colors"
        onClick={() => !isStopped && setExpanded(!expanded)}
      >
        {/* Strategy name + badges + symbols */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="font-semibold text-gray-100 text-base tracking-tight truncate">{session.strategyName}</span>
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium shrink-0 ${STATUS_STYLES[session.status] || STATUS_STYLES.stopped}`}>
              • {session.status}
            </span>
            {session.mode === 'mainnet' ? (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-red-400/10 text-red-400 border border-red-400/20 shrink-0">MAINNET</span>
            ) : (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-yellow-400/10 text-yellow-400 border border-yellow-400/20 shrink-0">TESTNET</span>
            )}
          </div>
          <div className="text-xs text-gray-500 truncate">
            {session.timeframe} · {session.symbols?.join(', ')}
          </div>
        </div>

        {/* Inline stats */}
        <div className="hidden md:flex items-center gap-6 shrink-0">
          <div className="text-center">
            <div className="text-xs text-gray-500 mb-0.5">Capital</div>
            <div className="text-sm font-semibold text-gray-200">${parseFloat(session.capital || 0).toLocaleString()}</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-gray-500 mb-0.5">Leverage</div>
            <div className="text-sm font-semibold text-gray-200">{session.leverage}x</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-gray-500 mb-0.5">Total trades</div>
            <div className="text-sm font-semibold text-gray-200">{totalTrades}</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-gray-500 mb-0.5">{isStopped ? 'Stopped' : 'Started'}</div>
            <div className="text-sm font-semibold text-gray-200 whitespace-nowrap">
              {formatStarted(isStopped ? (session.stoppedAt || session.updatedAt) : session.createdAt)}
            </div>
          </div>
        </div>

        {/* P&L + actions */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="text-right">
            <div className={`text-lg font-bold tracking-tight ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
              {isPositive ? '+' : ''}${Math.abs(pnlNum).toFixed(2)}
            </div>
            <div className="text-[10px] text-gray-500 uppercase tracking-wider">Live P&L</div>
          </div>

          {session.status === 'running' && (
            <button
              onClick={(e) => { e.stopPropagation(); onStop() }}
              disabled={stopping}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-transparent hover:bg-white/5 text-gray-300 hover:text-white text-xs font-medium rounded-lg border border-gray-600 hover:border-gray-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            >
              <Square size={12} className={stopping ? 'animate-pulse' : ''} />
              {stopping ? 'Stopping' : 'Stop'}
            </button>
          )}
          {isStopped && (
            <button
              onClick={(e) => { e.stopPropagation(); deleteSession.mutate(String(session._id)) }}
              disabled={deleteSession.isPending}
              className="p-1.5 hover:bg-red-500/10 text-gray-600 hover:text-red-400 rounded-lg border border-transparent hover:border-red-500/20 disabled:opacity-40 transition-all"
              title="Delete session"
            >
              <Trash2 size={14} />
            </button>
          )}
          {!isStopped && (
            <button
              onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
              className="p-1.5 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white rounded-lg transition-colors"
            >
              {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          )}
        </div>
      </div>

      {/* ── Expanded body ── */}
      {expanded && !isStopped && (
        <div className="border-t border-[#2E2E2E]">

          {/* ROW 1: Equity Curve + Session Stats */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] divide-y lg:divide-y-0 lg:divide-x divide-[#2E2E2E] bg-[#181818]">

            {/* Equity Curve */}
            <div className="p-5">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">
                <TrendingUp size={12} /> Equity Curve
              </div>
              <div className="h-36">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData}>
                    <YAxis domain={[minBalance, maxBalance]} hide />
                    <ReferenceLine y={baselineVal} stroke="#2E2E2E" strokeDasharray="3 3" />
                    <Line type="monotone" dataKey="balance" stroke="#34d399" strokeWidth={2} dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="flex justify-between text-[11px] text-gray-500 font-mono mt-2 px-0.5">
                <span>${baselineVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} baseline</span>
                <span>current</span>
                <span className={pnlNum > 0 ? 'text-emerald-400 font-semibold' : pnlNum < 0 ? 'text-red-400 font-semibold' : 'text-gray-400 font-semibold'}>
                  ${currentVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  {pnlNum > 0 && ' ▲'}{pnlNum < 0 && ' ▼'}
                </span>
              </div>
            </div>

            {/* Session Stats */}
            <div className="p-5">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">
                <BarChart2 size={12} /> Session Stats
              </div>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: 'Win rate', value: 'N/A', color: 'text-gray-200' },
                  { label: 'Avg PnL', value: 'N/A', color: 'text-emerald-400' },
                  { label: 'Max drawdown', value: 'N/A', color: 'text-red-400' },
                  { label: 'Trades today', value: totalTrades, color: 'text-gray-200' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-[#1C1C1C] rounded-lg p-3">
                    <div className="text-[10px] text-gray-500 mb-1">{label}</div>
                    <div className={`text-base font-bold ${color}`}>{value}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ROW 2: Activity Log + Open Positions */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] divide-y lg:divide-y-0 lg:divide-x divide-[#2E2E2E] border-t border-[#2E2E2E]">

            {/* Activity Log */}
            <div className="p-5">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">
                <ScrollText size={12} /> Activity Log
              </div>
              <div className="bg-[#141414] rounded-lg p-3 overflow-y-auto max-h-52 space-y-2 [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
                {logs.length === 0 ? (
                  <div className="text-center text-xs text-gray-600 py-6">No activity yet</div>
                ) : (
                  logs.map((log, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <span className="text-gray-600 font-mono shrink-0 tabular-nums pt-px">
                        {new Date(log.timestamp).toLocaleTimeString([], { hour12: false })}
                      </span>
                      <LogIcon type={log.type} />
                      <span
                        className="text-gray-300 font-mono flex-1 break-words leading-relaxed"
                        dangerouslySetInnerHTML={{
                          __html: log.message
                            .replace(/(\+\$[\d.]+)/g, '<span class="text-emerald-400 font-semibold">$1</span>')
                            .replace(/(-\$[\d.]+)/g, '<span class="text-red-400 font-semibold">$1</span>')
                        }}
                      />
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Open Positions */}
            <div className="p-5">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3">
                <Activity size={12} /> Open Positions
              </div>
              <div className="overflow-y-auto max-h-52 space-y-1 [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
                {session.symbols.map(sym => {
                  const isOpen = session.openPositions?.includes(sym)
                  const details = positionDetails[sym]

                  let pnlText = null
                  let pnlColor = 'text-gray-500'
                  if (isOpen && details) {
                    const cur = prices[sym]
                    if (cur) {
                      const entry = parseFloat(details.price)
                      const qty = parseFloat(details.qty)
                      const pnl = details.side === 'short' ? (entry - cur) * qty : (cur - entry) * qty
                      pnlText = (pnl >= 0 ? '+' : '') + pnl.toFixed(2)
                      pnlColor = pnl > 0 ? 'text-emerald-400' : pnl < 0 ? 'text-red-400' : 'text-gray-400'
                    }
                  }

                  return (
                    <div key={sym} className={`flex items-center gap-2 py-1.5 text-xs transition-opacity ${!isOpen ? 'opacity-40' : ''}`}>
                      <span className="font-semibold text-gray-200 tracking-tight w-24 shrink-0">{sym}</span>
                      <div className="shrink-0">
                        {isOpen ? (
                          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wider ${details?.side === 'short' ? 'bg-red-400/10 text-red-400' : 'bg-emerald-400/10 text-emerald-400'}`}>
                            {details?.side?.toUpperCase() || 'LONG'}
                          </span>
                        ) : (
                          <span className="text-[10px] text-gray-600 lowercase">watching</span>
                        )}
                      </div>
                      {isOpen && details && (
                        <span className="font-mono text-gray-400 text-[11px] ml-auto">${details.price}</span>
                      )}
                      {pnlText && (
                        <span className={`font-mono text-[11px] ${pnlColor} shrink-0`}>{pnlText}</span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

        </div>
      )}
    </div>
  )
}
