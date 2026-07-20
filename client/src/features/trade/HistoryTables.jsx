// Plan 7 Step 7.4 (CLI-1): extracted out of Trade.jsx. Order/Trade/
// Transaction History share the same shape (a synced-warning banner + a
// skeleton/empty/data table), grouped in one file rather than three
// near-identical single-table files.
import { formatDateTime } from '@/utils/formatters'
import { fmtPrice, fmtQty } from './formatters'
import { SkeletonRow, EmptyRow, SyncWarningBanner } from './TableHelpers'

export function OrderHistoryTable({ data, isLoading, synced = true }) {
  const cols = ['Time', 'Symbol', 'Type', 'Side', 'Average', 'Price', 'Executed', 'Amount', 'Reduce Only', 'Post Only', 'Trigger Conditions', 'Status']
  return (
    <>
      {!synced && !isLoading && <SyncWarningBanner />}
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
          ) : !data?.length ? (
            <EmptyRow message="No order history" />
          ) : (
            data.map((o) => {
              const side = o.side.toUpperCase()
              const isFilled = o.status === 'FILLED'
              const isCanceled = o.status === 'CANCELED'
              const isNew = o.status === 'NEW'
              return (
                <tr key={o.orderId} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400 pl-2">{formatDateTime(o.time)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-gray-100">{o.symbol.replace('USDT', '-USDT')}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{o.type}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium ${side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>{side}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{o.avgPrice && parseFloat(o.avgPrice) > 0 ? fmtPrice(o.avgPrice) : '—'}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtPrice(o.price)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtQty(o.executedQty)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtQty(o.origQty)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{o.reduceOnly ? 'Yes' : 'No'}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{o.postOnly ? 'Yes' : 'No'}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{o.stopPrice && parseFloat(o.stopPrice) > 0 ? fmtPrice(o.stopPrice) : '—'}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium ${isFilled ? 'text-emerald-400' : isCanceled ? 'text-slate-400' : isNew ? 'text-yellow-400' : 'text-gray-300'}`}>{o.status}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </>
  )
}

export function TradeHistoryTable({ data, isLoading, synced = true }) {
  const cols = ['Order No.', 'Time', 'Symbol', 'Side', 'Price', 'Quantity', 'Fee', 'Role', 'Realized Profit']
  return (
    <>
      {!synced && !isLoading && <SyncWarningBanner />}
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
          ) : !data?.length ? (
            <EmptyRow message="No trade history" />
          ) : (
            data.map((t) => {
              const side = t.side.toUpperCase()
              const pnl = parseFloat(t.realizedPnl || '0')
              return (
                <tr key={t.id} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400 tabular-nums pl-2">{t.orderId}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400">{formatDateTime(t.time)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-gray-100">{t.symbol.replace('USDT', '-USDT')}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium ${side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>{side}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtPrice(t.price)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap tabular-nums">{fmtQty(t.qty)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400 tabular-nums">{t.commission ? `${fmtQty(t.commission)} ${t.commissionAsset || 'USDT'}` : '—'}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{t.maker ? 'Maker' : 'Taker'}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium tabular-nums ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pnl >= 0 ? '+' : ''}{pnl.toFixed(4)} USDT
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </>
  )
}

export function TransactionHistoryTable({ data, isLoading, synced = true }) {
  const cols = ['Time', 'Type', 'Amount', 'Asset', 'Symbol']
  return (
    <>
      {!synced && !isLoading && <SyncWarningBanner />}
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
          ) : !data?.length ? (
            <EmptyRow message="No transaction history" />
          ) : (
            data.map((tx) => {
              const income = parseFloat(tx.income || '0')
              return (
                <tr key={tx.tranId} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                  <td className="py-2 pr-6 whitespace-nowrap text-slate-400 pl-2">{formatDateTime(tx.time)}</td>
                  <td className="py-2 pr-6 whitespace-nowrap">{tx.incomeType}</td>
                  <td className={`py-2 pr-6 whitespace-nowrap font-medium tabular-nums ${income >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {income >= 0 ? '+' : ''}{parseFloat(tx.income).toFixed(4)}
                  </td>
                  <td className="py-2 pr-6 whitespace-nowrap">{tx.asset}</td>
                  <td className="py-2 pr-6 whitespace-nowrap text-gray-100">{tx.symbol ? tx.symbol.replace('USDT', '-USDT') : '—'}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </>
  )
}
