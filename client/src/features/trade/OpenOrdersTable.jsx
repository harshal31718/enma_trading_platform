// Plan 7 Step 7.4 (CLI-1): extracted out of Trade.jsx.
import { useState } from 'react'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useCancelOrder, useCancelAllOrders } from '@/hooks/useTrade'
import { useCurrentSymbol } from '@/context/SymbolContext'
import { fmtPrice, fmtQty } from './formatters'
import { SkeletonRow, EmptyRow } from './TableHelpers'

export function extractOcoId(clientOrderId) {
  if (!clientOrderId) return null
  const m = clientOrderId.match(/^((oco|tpsl)_[0-9a-f]{8}_)(?:sl|tp)$/)
  return m ? m[1] : null
}

export default function OpenOrdersTable({ data, isLoading, onOcoBannerEvent }) {
  const { symbol } = useCurrentSymbol()
  const cols = ['Symbol', 'Type', 'Side', 'Price', 'Amount', 'Filled', 'Status', 'OCO Group', '']
  const { mutate: execCancel, isPending: cancelPending, variables: cancelVars } = useCancelOrder()
  const { mutate: execCancelAll, isPending: cancelAllPending } = useCancelAllOrders()
  const [confirmCancelAllOpen, setConfirmCancelAllOpen] = useState(false)

  function handleCancelOco(ocoId) {
    // Cancel both legs by cancelling all orders for the symbol — the cleanest
    // approach since Binance Futures has no group-cancel endpoint.
    execCancelAll(
      { symbol },
      {
        onSuccess: () => onOcoBannerEvent?.('OCO group cancelled.'),
        onError: () => onOcoBannerEvent?.('Failed to cancel OCO group.'),
      }
    )
  }

  return (
    <div className="w-full overflow-x-auto">
      <ConfirmDialog
        open={confirmCancelAllOpen}
        onOpenChange={setConfirmCancelAllOpen}
        title="Cancel all open orders?"
        description={`This will cancel all open orders for ${symbol}. This cannot be undone.`}
        confirmLabel="Cancel All"
        onConfirm={() => { setConfirmCancelAllOpen(false); execCancelAll({ symbol }, { onSuccess: () => onOcoBannerEvent?.('All orders cancelled.') }) }}
      />
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 border-b border-slate-700/50 bg-title-bg title-fade">
            {cols.map((c, i) => {
              if (i === cols.length - 1) {
                return (
                  <th key="cancel-all" className="pr-2 text-right align-middle">
                    <button
                      disabled={cancelAllPending || !data?.length}
                      onClick={() => setConfirmCancelAllOpen(true)}
                      className="px-3 py-1 text-[10px] rounded border border-slate-600 text-gray-400 hover:bg-slate-700/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
                    >
                      {cancelAllPending ? 'Cancelling…' : 'Cancel All'}
                    </button>
                  </th>
                )
              }
              return (
                <th key={c} className={`text-left py-2 pr-6 font-medium whitespace-nowrap ${i === 0 ? 'pl-2' : ''}`}>{c}</th>
              )
            })}
          </tr>
        </thead>
        <tbody className="text-gray-400">
          {isLoading ? (
            <>
              <SkeletonRow cols={cols} />
              <SkeletonRow cols={cols} />
            </>
          ) : !data?.length ? (
            <EmptyRow message="No open orders" />
          ) : (
            data.map((o) => {
              const isCancelling = cancelPending && cancelVars?.orderId === o.orderId
              const ocoId = extractOcoId(o.clientOrderId)
              return (
                <tr key={o.orderId} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                  <td className="py-2 pr-6 text-gray-100 whitespace-nowrap pl-2">{o.symbol.replace('USDT', '-USDT')}</td>
                  <td className="py-2 pr-6">{o.type}</td>
                  <td className={`py-2 pr-6 font-medium ${o.side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>{o.side}</td>
                  <td className="py-2 pr-6 tabular-nums">{fmtPrice(o.price)}</td>
                  <td className="py-2 pr-6 tabular-nums">{fmtQty(o.origQty)}</td>
                  <td className="py-2 pr-6 tabular-nums">{fmtQty(o.executedQty)}</td>
                  <td className="py-2 pr-6">{o.status}</td>
                  <td className="py-2 pr-6">
                    {ocoId ? (
                      <span className="text-[10px] font-mono text-yellow-400 bg-yellow-400/10 px-1.5 py-0.5 rounded">
                        {ocoId}
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="py-2">
                    <div className="flex items-center gap-1">
                      <button
                        disabled={isCancelling}
                        onClick={() => execCancel({ symbol, orderId: o.orderId })}
                        className={[
                          'px-3 py-1 text-[10px] rounded border transition-colors',
                          isCancelling
                            ? 'border-slate-700/50 text-slate-400 cursor-not-allowed'
                            : 'border-slate-600 text-gray-400 hover:bg-slate-700/50 cursor-pointer',
                        ].join(' ')}
                      >
                        {isCancelling ? 'Cancelling…' : 'Cancel'}
                      </button>
                      {ocoId && (
                        <button
                          disabled={cancelAllPending}
                          onClick={() => handleCancelOco(ocoId)}
                          className="px-3 py-1 text-[10px] rounded border border-yellow-600/40 text-yellow-400 hover:bg-yellow-500/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                          Cancel OCO
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
