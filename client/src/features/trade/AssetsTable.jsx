// Plan 7 Step 7.4 (CLI-1): extracted out of Trade.jsx.
import { SkeletonRow, EmptyRow } from './TableHelpers'

export default function AssetsTable({ data, isLoading }) {
  const cols = ['Asset', 'Wallet Balance', 'Available Balance', 'Unrealized PnL']
  const assets = data?.assets?.filter((a) => parseFloat(a.walletBalance) > 0) ?? []
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-gray-400 border-b border-slate-700/50 bg-title-bg title-fade">
          {cols.map((c, i) => (
            <th key={c} className={`text-left py-2 pr-6 font-medium ${i === 0 ? 'pl-2' : ''}`}>{c}</th>
          ))}
        </tr>
      </thead>
      <tbody className="text-gray-400">
        {isLoading ? (
          <>
            <SkeletonRow cols={cols} />
            <SkeletonRow cols={cols} />
          </>
        ) : !assets.length ? (
          <EmptyRow message="No assets" />
        ) : (
          assets.map((a) => {
            const pnl = parseFloat(a.unrealizedProfit)
            return (
              <tr key={a.asset} className="border-b border-slate-700/30 hover:bg-slate-800/20">
                <td className="py-2 pr-6 text-gray-100 font-medium pl-2">{a.asset}</td>
                <td className="py-2 pr-6 tabular-nums">{parseFloat(a.walletBalance).toFixed(4)}</td>
                <td className="py-2 pr-6 tabular-nums">{parseFloat(a.availableBalance).toFixed(4)}</td>
                <td className={`py-2 pr-6 tabular-nums ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {pnl >= 0 ? '+' : ''}{pnl.toFixed(4)}
                </td>
              </tr>
            )
          })
        )}
      </tbody>
    </table>
  )
}
