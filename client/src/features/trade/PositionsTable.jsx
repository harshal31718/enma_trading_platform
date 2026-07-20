// Plan 7 Step 7.4 (CLI-1): extracted out of Trade.jsx.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useClosePosition } from '@/hooks/useTrade'
import { useCurrentSymbol } from '@/context/SymbolContext'
import { fmtPriceForSymbol, fmtQtyForSymbol } from './formatters'
import { SkeletonRow, EmptyRow } from './TableHelpers'
import TpSlModal from './TpSlModal'

export default function PositionsTable({ data, isLoading, account }) {
  const cols = ['Symbol', 'Size', 'Entry Price', 'Mark Price', 'Liq Price', 'Margin Ratio', 'Unrealized PnL', '']
  const [closeError, setCloseError] = useState(null)
  const [tpslPosition, setTpslPosition] = useState(null) // position object for modal
  const [confirmCloseSymbol, setConfirmCloseSymbol] = useState(null)

  const navigate = useNavigate()
  const { symbol: activeSymbol } = useCurrentSymbol()

  // Clicking a position row loads that symbol's full terminal (chart, ticker, order book,
  // order form + per-symbol leverage/margin) via the route — same path SymbolSearchBar uses.
  function handleRowClick(symbol) {
    if (symbol === activeSymbol) return
    navigate(`/trade/${symbol}`)
  }

  const { mutate: execClose, isPending: closePending, variables: closeVars } = useClosePosition()

  function handleClose(symbol) {
    setCloseError(null)
    execClose(
      { symbol },
      {
        onError: (err) => {
          const detail =
            err.response?.data?.error?.message ||
            err.response?.data?.message ||
            err.response?.data?.detail ||
            err.message
          setCloseError(typeof detail === 'string' ? detail : 'Failed to close position')
        },
      }
    )
  }

  const activePositions = data?.filter((p) => parseFloat(p.positionAmt) !== 0) ?? []

  const maintMargin = parseFloat(account?.totalMaintMargin ?? 0)
  const marginBalance = parseFloat(account?.totalMarginBalance ?? 0)
  const accountMarginRatio = marginBalance > 0 ? (maintMargin / marginBalance * 100).toFixed(2) + '%' : '—'

  return (
    <>
      {tpslPosition && (
        <TpSlModal position={tpslPosition} onClose={() => setTpslPosition(null)} />
      )}
      <ConfirmDialog
        open={!!confirmCloseSymbol}
        onOpenChange={(v) => { if (!v) setConfirmCloseSymbol(null) }}
        title={`Close ${confirmCloseSymbol} position?`}
        description="This will send a market close order. This cannot be undone."
        confirmLabel="Close Position"
        onConfirm={() => { const s = confirmCloseSymbol; setConfirmCloseSymbol(null); handleClose(s) }}
      />

      <div className="w-full overflow-x-auto">
        <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 border-b border-slate-700/50 bg-title-bg title-fade">
            {cols.map((c, i) => (
              <th key={c} className={`text-left py-2 pr-6 font-medium whitespace-nowrap ${i === 0 ? 'pl-2' : ''}`}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody className="text-gray-400">
          {isLoading ? (
            <>
              <SkeletonRow cols={cols} />
              <SkeletonRow cols={cols} />
            </>
          ) : !activePositions.length ? (
            <EmptyRow message="No open positions" />
          ) : (
            <>
              {closeError && (
                <tr>
                  <td colSpan={cols.length} className="py-1">
                    <div className="bg-red-950/20 border border-red-800/40 rounded px-3 py-1.5 text-[10px] text-red-400">
                      {closeError}
                    </div>
                  </td>
                </tr>
              )}
              {activePositions.map((p) => {
                const size = parseFloat(p.positionAmt)
                const side = size > 0 ? 'Long' : 'Short'
                const pnl = parseFloat(p.unRealizedProfit)
                const isPnlPos = pnl >= 0
                const isClosing = closePending && closeVars?.symbol === p.symbol
                const posRatio = p.marginRatio && parseFloat(p.marginRatio) > 0
                  ? (parseFloat(p.marginRatio) * 100).toFixed(2) + '%'
                  : accountMarginRatio
                const marginRatio = posRatio
                const isActive = p.symbol === activeSymbol
                return (
                  <tr
                    key={p.symbol}
                    onClick={() => handleRowClick(p.symbol)}
                    title="View chart"
                    className={[
                      'border-b border-slate-700/30 cursor-pointer transition-colors',
                      isActive ? 'bg-slate-800/40 border-l-2 border-emerald-400' : 'hover:bg-slate-800/20',
                    ].join(' ')}
                  >
                    <td className="py-2 pr-6 whitespace-nowrap pl-2">
                      <div className="flex items-center gap-2">
                        <span className="text-gray-100">{p.symbol.replace('USDT', '-USDT')}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${side === 'Long' ? 'bg-emerald-400/10 text-emerald-400' : 'bg-red-400/10 text-red-400'}`}>{side}</span>
                      </div>
                    </td>
                    <td className="py-2 pr-6 tabular-nums">{fmtQtyForSymbol(Math.abs(size), p.symbol)}</td>
                    <td className="py-2 pr-6 tabular-nums">{fmtPriceForSymbol(p.entryPrice, p.symbol)}</td>
                    <td className="py-2 pr-6 tabular-nums">{fmtPriceForSymbol(p.markPrice, p.symbol)}</td>
                    <td className="py-2 pr-6 tabular-nums">{fmtPriceForSymbol(p.liquidationPrice, p.symbol)}</td>
                    <td className="py-2 pr-6 tabular-nums">{marginRatio}</td>
                    <td className={`py-2 pr-6 tabular-nums font-medium ${isPnlPos ? 'text-emerald-400' : 'text-red-400'}`}>
                      {isPnlPos ? '+' : ''}{pnl.toFixed(2)} USDT
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-1.5">
                        <button
                          disabled={isClosing}
                          onClick={(e) => { e.stopPropagation(); setConfirmCloseSymbol(p.symbol) }}
                          className={[
                            'px-3 py-1 text-[10px] rounded border transition-colors whitespace-nowrap',
                            isClosing
                              ? 'border-slate-700/50 text-slate-400 cursor-not-allowed'
                              : 'border-slate-600 text-gray-300 hover:bg-slate-700/50 cursor-pointer',
                          ].join(' ')}
                        >
                          {isClosing ? 'Closing…' : 'Close Position'}
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setTpslPosition(p) }}
                          className="px-3 py-1 text-[10px] rounded border border-slate-600 text-gray-400 hover:bg-slate-700/50 hover:border-yellow-600/40 hover:text-yellow-400 transition-colors whitespace-nowrap cursor-pointer"
                        >
                          TP/SL
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </>
          )}
        </tbody>
      </table>
      </div>
    </>
  )
}
