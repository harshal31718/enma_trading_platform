import { useState, useEffect, useMemo, useCallback } from 'react'
import { ChevronDown, ChevronUp, Square, ArrowUpCircle, ArrowDownCircle, CheckCircle2, Info, AlertTriangle, Activity, Trash2, TrendingUp, BarChart2, ScrollText } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, ReferenceLine, Tooltip } from 'recharts'
import { useSocket } from '../../hooks/useSocket'
import { useDeleteSession } from '../../hooks/useAlgoSessions'
import useBinanceWS from '../../hooks/useBinanceWS'
import api from '../../lib/axios'

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

const formatTime = (t) =>
  new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })

const fmtPnl = (v) => `${v >= 0 ? '+' : '-'}$${Math.abs(v).toFixed(2)}`
const pnlColor = (v) => (v > 0 ? 'text-emerald-400' : v < 0 ? 'text-red-400' : 'text-gray-200')

// Compact number: thousands grouped, fewer decimals as magnitude grows.
const fmtNum = (v) => {
  const n = Number(v)
  if (!Number.isFinite(n)) return '0'
  const abs = Math.abs(n)
  const maximumFractionDigits = abs >= 1000 ? 0 : abs >= 1 ? 2 : 4
  return n.toLocaleString(undefined, { maximumFractionDigits })
}

const StatTile = ({ label, value, color = 'text-gray-100' }) => (
  <div className="bg-[#0d1117] border border-slate-700/40 rounded-lg px-2.5 py-2">
    <div className="text-[10px] text-slate-400 mb-0.5 truncate">{label}</div>
    <div className={`text-sm font-bold tabular-nums ${color}`}>{value}</div>
  </div>
)

const EquityTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const { t, balance } = payload[0].payload
  return (
    <div className="bg-gray-950 border border-gray-800 rounded-md px-2.5 py-1.5 text-xs shadow-xl">
      <div className="text-gray-500 font-mono mb-0.5">{new Date(t).toLocaleString([], { hour12: false })}</div>
      <div className="font-mono font-semibold text-gray-100">
        ${balance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </div>
    </div>
  )
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
  const isStopped = session.status === 'stopped' || session.status === 'error'
  const baselineVal = parseFloat(session.capital || 0)
  const currentVal = baselineVal + pnlNum

  // Fetch realized-equity history (tradeHistory) on expand — for running and stopped alike
  useEffect(() => {
    if (!expanded) return
    let cancelled = false
    api.get(`/api/v1/algo/sessions/${session._id}/equity`)
      .then(res => { if (!cancelled) setEquity(res.data.data?.equity || []) })
      .catch(console.error)
    return () => { cancelled = true }
  }, [expanded, session._id])

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

  const handlePositionOpen = useCallback((data) => {
    if (String(data.sessionId) === String(session._id)) {
      setPositionDetails(prev => ({
        ...prev,
        [data.symbol]: { side: data.side, qty: data.qty, price: data.price, leverage: data.leverage },
      }))
    }
  }, [session._id])

  useSocket('algo:position:open', handlePositionOpen)

  // On close: drop the open-position detail AND extend the live equity curve so
  // the chart and session stats update without a full re-fetch (Bug 3).
  const handlePositionClose = useCallback((data) => {
    if (String(data.sessionId) !== String(session._id)) return
    setPositionDetails(prev => {
      const next = { ...prev }
      delete next[data.symbol]
      return next
    })
    const tradePnl = parseFloat(data.pnl)
    if (!Number.isNaN(tradePnl)) {
      setEquity(prev => {
        const last = prev.length ? parseFloat(prev[prev.length - 1].balance) : baselineVal
        return [...prev, { timestamp: new Date().toISOString(), balance: String(last + tradePnl) }]
      })
    }
  }, [session._id, baselineVal])

  useSocket('algo:position:close', handlePositionClose)

  const formatStarted = (dateString) => {
    if (!dateString) return ''
    const d = new Date(dateString)
    return `${d.toLocaleTimeString([], { hour12: false })} ${d.toLocaleDateString()}`
  }

  // Build a timeline-aware equity series: baseline → each realized point → live value.
  // balance is coerced to a number so Recharts can actually plot it (Bug 1).
  const chartData = useMemo(() => {
    const points = [{
      t: new Date(session.createdAt).getTime(),
      balance: baselineVal,
    }]
    for (const d of equity) {
      const balance = parseFloat(d.balance)
      const t = new Date(d.timestamp).getTime()
      if (!Number.isNaN(balance) && !Number.isNaN(t)) points.push({ t, balance })
    }
    // Live endpoint (includes unrealized PnL) only while the bot is active
    if (!isStopped) points.push({ t: Date.now(), balance: currentVal })
    return points
  }, [equity, baselineVal, currentVal, isStopped, session.createdAt])

  const balances = chartData.map(d => d.balance)
  const minBalance = Math.min(...balances) * 0.999
  const maxBalance = Math.max(...balances) * 1.001

  // Derive session stats from the realized-equity deltas (Bug 5).
  const stats = useMemo(() => {
    const realized = equity
      .map(d => parseFloat(d.balance))
      .filter(n => !Number.isNaN(n))
    if (realized.length === 0) {
      return { winRate: null, avgPnl: null, maxDrawdown: 0, realisedPnl: 0, peak: baselineVal, closedTrades: 0 }
    }
    const deltas = []
    let prev = baselineVal
    for (const b of realized) { deltas.push(b - prev); prev = b }
    const wins = deltas.filter(d => d > 0).length
    const losses = deltas.filter(d => d < 0).length
    const decided = wins + losses
    const winRate = decided > 0 ? (wins / decided) * 100 : null
    const avgPnl = deltas.reduce((a, b) => a + b, 0) / deltas.length
    const realisedPnl = realized[realized.length - 1] - baselineVal
    // Peak + max drawdown across baseline + realized series
    const series = [baselineVal, ...realized]
    let peak = series[0]
    let maxDD = 0
    for (const v of series) {
      if (v > peak) peak = v
      const dd = peak > 0 ? ((peak - v) / peak) * 100 : 0
      if (dd > maxDD) maxDD = dd
    }
    return { winRate, avgPnl, maxDrawdown: maxDD, realisedPnl, peak, closedTrades: deltas.length }
  }, [equity, baselineVal])

  const totalTrades = session.totalTrades || 0

  // Live (unrealized) PnL across currently-open positions — recomputes as
  // ticker prices stream in. null when positions are open but we lack the
  // entry details/price to value them yet.
  const livePnl = useMemo(() => {
    const open = session.openPositions || []
    if (open.length === 0) return 0
    let sum = 0, counted = 0
    for (const sym of open) {
      const d = positionDetails[sym]
      const cur = prices[sym]
      if (d && cur) {
        const entry = parseFloat(d.price)
        const qty = parseFloat(d.qty)
        sum += d.side === 'short' ? (entry - cur) * qty : (cur - entry) * qty
        counted++
      }
    }
    return counted > 0 ? sum : null
  }, [session.openPositions, positionDetails, prices])

  // Drawdown vs the running equity peak (includes the live value). Max
  // drawdown extends the realized max if the current dip runs deeper.
  const peak = Math.max(stats.peak, currentVal)
  const currentDrawdown = peak > 0 ? Math.max(0, ((peak - currentVal) / peak) * 100) : 0
  const maxDrawdown = Math.max(stats.maxDrawdown, currentDrawdown)

  const openTrades = session.openPositions?.length || 0

  // Header (collapsed bar) figures — live where it matters:
  // closed-trade count and realised PnL come from the live-updating
  // symbolStats; total bar PnL = realised + live (unrealized) of open trades,
  // falling back to the engine's session.pnl when we can't value open
  // positions client-side yet.
  const symbolStatsArr = Object.values(session.symbolStats || {})
  const realisedTotal = symbolStatsArr.reduce((a, s) => a + (s.realisedPnl || 0), 0)
  const closedTrades = symbolStatsArr.reduce((a, s) => a + (s.trades || 0), 0)
    || stats.closedTrades || totalTrades
  const barPnl = livePnl == null ? pnlNum : realisedTotal + livePnl
  const barPnlPct = baselineVal > 0 ? (barPnl / baselineVal) * 100 : 0
  const barPositive = barPnl >= 0

  // Per-symbol rows for the Open Positions panel. Bucketed Open → Traded →
  // Remaining, then by traded notional. Live PnL streams from ticker prices;
  // the cumulative columns come from server-side symbolStats.
  const positionRows = useMemo(() => {
    const symbolStats = session.symbolStats || {}
    const rows = (session.symbols || []).map(sym => {
      const isOpen = session.openPositions?.includes(sym)
      const details = positionDetails[sym]
      const stat = symbolStats[sym] || {}
      const trades = stat.trades || 0
      const notional = stat.notional || 0
      // Active leverage: live open-event > last recorded trade > session default
      const leverage = details?.leverage ?? stat.leverage ?? session.leverage ?? null
      const margin = notional && leverage ? notional / leverage : null

      let livePnl = null
      if (isOpen && details) {
        const cur = prices[sym]
        if (cur) {
          const entry = parseFloat(details.price)
          const qty = parseFloat(details.qty)
          livePnl = details.side === 'short' ? (entry - cur) * qty : (cur - entry) * qty
        }
      }

      const bucket = isOpen ? 0 : trades > 0 ? 1 : 2
      return {
        sym, isOpen, side: details?.side, leverage, bucket,
        trades, qty: stat.qty || 0, notional, margin,
        realisedPnl: stat.realisedPnl ?? null, livePnl,
      }
    })
    rows.sort((a, b) => a.bucket - b.bucket || b.notional - a.notional || a.sym.localeCompare(b.sym))
    return rows
  }, [session.symbols, session.openPositions, session.leverage, session.symbolStats, positionDetails, prices])
  const maxAllowedDrawdown = (session.riskParams?.max_session_dd ?? 0.20) * 100

  return (
    <div className="bg-[#0d1117] border border-slate-700/50 rounded-xl overflow-hidden shadow-2xl hover:border-slate-600/70 transition-all duration-300">

      {/* ── Header row ── */}
      <div
        className="px-5 py-4 flex items-center gap-4 cursor-pointer bg-gradient-to-r from-slate-800/30 via-transparent to-transparent hover:from-slate-800/40 transition-all"
        onClick={() => setExpanded(!expanded)}
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
          <div className="text-xs text-slate-400 truncate">
            {session.timeframe} · {session.symbols?.join(', ')}
          </div>
        </div>

        {/* Inline stats — order: Started · Capital · Leverage · Trades */}
        <div className="hidden md:flex items-center gap-6 shrink-0">
          <div className="text-center">
            <div className="text-xs text-slate-400 mb-0.5">{isStopped ? 'Stopped' : 'Started'}</div>
            <div className="text-sm font-semibold text-gray-200 whitespace-nowrap">
              {formatStarted(isStopped ? (session.stoppedAt || session.updatedAt) : session.createdAt)}
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs text-slate-400 mb-0.5">Capital</div>
            <div className="text-sm font-semibold text-gray-100">${parseFloat(session.capital || 0).toLocaleString()}</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-slate-400 mb-0.5">Leverage</div>
            <div className="text-sm font-semibold text-gray-100">{session.leverage}x</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-slate-400 mb-0.5">Trades</div>
            <div className="text-sm font-semibold whitespace-nowrap">
              <span className={openTrades > 0 ? 'text-emerald-400' : 'text-gray-100'}>{openTrades}</span>
              <span className="text-slate-600"> / </span>
              <span className="text-gray-100">{closedTrades}</span>
            </div>
            <div className="text-[9px] text-slate-500 uppercase tracking-wider -mt-0.5">open / closed</div>
          </div>
        </div>

        {/* P&L + actions — PnL: realised + live (unrealized) of open trades */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="text-right">
            <div className={`text-lg font-bold tracking-tight ${barPositive ? 'text-emerald-400' : 'text-red-400'}`}>
              {barPositive ? '+' : '-'}${Math.abs(barPnl).toFixed(2)}
              <span className="text-xs font-semibold ml-1 opacity-80">
                ({barPositive ? '+' : '-'}{Math.abs(barPnlPct).toFixed(2)}%)
              </span>
            </div>
            <div className="text-[10px] text-slate-400 uppercase tracking-wider">P&L</div>
          </div>

          {session.status === 'running' && (
            <button
              onClick={(e) => { e.stopPropagation(); onStop() }}
              disabled={stopping}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all"
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
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
            className="p-1.5 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white rounded-lg transition-colors"
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      {/* ── Expanded body ── */}
      {expanded && (
        <div className="border-t border-slate-700/50">

          {/* ROW 1: Equity Curve + Session Stats */}
          <div className="grid grid-cols-1 lg:grid-cols-[1.5fr_1fr] divide-y lg:divide-y-0 lg:divide-x divide-slate-700/40 bg-[#080b10]">

            {/* Equity Curve */}
            <div className="p-5">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-4">
                <TrendingUp size={13} className="text-gray-400" /> Equity Curve
              </div>
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                    <XAxis
                      dataKey="t"
                      type="number"
                      scale="time"
                      domain={['dataMin', 'dataMax']}
                      tickFormatter={formatTime}
                      tick={{ fill: '#94a3b8', fontSize: 10 }}
                      stroke="#1e293b"
                      minTickGap={40}
                    />
                    <YAxis
                      domain={[minBalance, maxBalance]}
                      tick={{ fill: '#94a3b8', fontSize: 10 }}
                      stroke="#1e293b"
                      width={52}
                      tickFormatter={(v) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                    />
                    <Tooltip content={<EquityTooltip />} />
                    <ReferenceLine y={baselineVal} stroke="#4B5563" strokeDasharray="3 3" />
                    <Line
                      type="monotone"
                      dataKey="balance"
                      stroke={currentVal >= baselineVal ? '#34d399' : '#f87171'}
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="flex justify-between text-[11px] text-slate-400 font-mono mt-2 px-0.5">
                <span>${baselineVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} baseline</span>
                <span className={pnlNum > 0 ? 'text-emerald-400 font-semibold' : pnlNum < 0 ? 'text-red-400 font-semibold' : 'text-gray-400 font-semibold'}>
                  ${currentVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  {pnlNum > 0 && ' ▲'}{pnlNum < 0 && ' ▼'}
                </span>
              </div>
            </div>

            {/* Session Stats */}
            <div className="p-5">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-4">
                <BarChart2 size={13} className="text-gray-400" /> Session Stats
              </div>
              <div className="space-y-2">
                {/* Row 1 — trade counts & rates */}
                <div className="grid grid-cols-4 gap-2">
                  <StatTile label="Open trades" value={openTrades} />
                  <StatTile label="Closed trades" value={closedTrades} />
                  <StatTile
                    label="Win rate"
                    value={stats.winRate == null ? '—' : `${stats.winRate.toFixed(1)}%`}
                  />
                  <StatTile
                    label="Avg PnL"
                    value={stats.avgPnl == null ? '—' : fmtPnl(stats.avgPnl)}
                    color={stats.avgPnl == null ? 'text-gray-200' : pnlColor(stats.avgPnl)}
                  />
                </div>
                {/* Row 2 — live / realised pnl & drawdown */}
                <div className="grid grid-cols-3 gap-2">
                  <StatTile
                    label="Live PnL"
                    value={livePnl == null ? '—' : fmtPnl(livePnl)}
                    color={livePnl == null ? 'text-gray-200' : pnlColor(livePnl)}
                  />
                  <StatTile
                    label="Realised PnL"
                    value={fmtPnl(stats.realisedPnl)}
                    color={pnlColor(stats.realisedPnl)}
                  />
                  <StatTile
                    label="Drawdown / Limit"
                    value={(
                      <span>
                        <span className={currentDrawdown >= maxAllowedDrawdown * 0.8 ? 'text-amber-400' : 'text-red-400'}>
                          -{currentDrawdown.toFixed(2)}%
                        </span>
                        <span className="text-gray-600"> / -{maxAllowedDrawdown.toFixed(0)}%</span>
                      </span>
                    )}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* ROW 2: Activity Log + Positions */}
          <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-slate-700/40 border-t border-slate-700/50 bg-[#0a0d13]">

            {/* Activity Log */}
            <div className="p-5">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-4">
                <ScrollText size={13} className="text-gray-400" /> Activity Log
              </div>
              <div className="bg-[#060a0f] border border-slate-700/30 rounded-lg p-3 overflow-y-auto max-h-52 space-y-2 [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
                {logs.length === 0 ? (
                  <div className="text-center text-xs text-slate-500 py-6">No activity yet</div>
                ) : (
                  logs.map((log, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <span className="text-gray-500 font-mono shrink-0 tabular-nums pt-px">
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

            {/* Positions */}
            <div className="p-5">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-4">
                <Activity size={13} className="text-gray-400" /> Positions
              </div>
              <div className="overflow-y-auto max-h-52 [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-slate-700/50">
                      <th className="text-left pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Symbol</th>
                      <th className="text-left pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Status</th>
                      <th className="text-right pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Live PnL</th>
                      <th className="text-right pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Lev</th>
                      <th className="text-right pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Trades</th>
                      <th className="text-right pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Qty</th>
                      <th className="text-right pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Notional</th>
                      <th className="text-right pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Realised</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positionRows.map(row => {
                      const statusBadge = row.isOpen
                        ? row.side === 'short'
                          ? <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-red-400/10 text-red-400 uppercase tracking-wider">SHORT</span>
                          : <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-400/10 text-emerald-400 uppercase tracking-wider">LONG</span>
                        : isStopped
                          ? <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-700/50 text-gray-400 uppercase tracking-wider">CLOSED</span>
                          : <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-yellow-400/10 text-yellow-400 uppercase tracking-wider">WATCHING</span>
                      return (
                        <tr key={row.sym} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                          <td className="py-2.5 pr-3 font-semibold text-gray-100 tracking-tight">{row.sym}</td>
                          <td className="py-2.5 pr-3">{statusBadge}</td>
                          <td className={`py-2.5 pr-3 text-right font-mono ${!row.isOpen || row.livePnl == null ? 'text-gray-100' : pnlColor(row.livePnl)}`}>
                            {!row.isOpen || row.livePnl == null ? '—' : fmtPnl(row.livePnl)}
                          </td>
                          <td className="py-2.5 pr-3 text-right font-mono text-gray-100">{row.leverage != null ? `${row.leverage}x` : '—'}</td>
                          <td className="py-2.5 pr-3 text-right font-mono text-gray-100">{row.trades || '—'}</td>
                          <td className="py-2.5 pr-3 text-right font-mono text-gray-100">{row.qty ? fmtNum(row.qty) : '—'}</td>
                          <td className="py-2.5 pr-3 text-right font-mono text-gray-100">{row.notional ? `$${fmtNum(row.notional)}` : '—'}</td>
                          <td className={`py-2.5 text-right font-mono ${row.realisedPnl == null ? 'text-gray-100' : pnlColor(row.realisedPnl)}`}>
                            {row.realisedPnl == null ? '—' : fmtPnl(row.realisedPnl)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

        </div>
      )}
    </div>
  )
}
