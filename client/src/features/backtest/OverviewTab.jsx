// Plan 7 Step 7.4 (CLI-1): extracted out of Backtest.jsx.
import { lazy, Suspense } from 'react'
import { Loader2 } from 'lucide-react'
import ErrorBoundary from '@/components/ErrorBoundary'
import MCSummaryStrip from './MCSummaryStrip'
import { formatPrice, formatPct, formatSignedPct, formatPnl } from '@/utils/formatters'

const EquityCurve = lazy(() => import('@/components/charts/EquityCurve'))
const BacktestCalendar = lazy(() => import('./BacktestCalendar'))

function getPnlClass(val) {
  const n = parseFloat(val)
  if (n > 0) return 'text-emerald-400'
  if (n < 0) return 'text-red-400'
  return 'text-gray-300'
}

export default function OverviewTab({ activeResult, benchmarkData, allTradesData }) {
  return (
    <>
      {activeResult.metrics && (() => {
        const m = activeResult.metrics
        const metrics = [
          { label: 'Net Profit', value: formatPrice(m.netProfit), cls: getPnlClass(m.netProfit) },
          { label: 'Net P&L %', value: formatSignedPct(m.netProfitPct), cls: getPnlClass(m.netProfit) },
          { label: 'Max Drawdown', value: `${formatPct(m.maxDrawdown)} / ${formatPct((activeResult.riskParams?.max_session_dd ?? 0.20) * 100)}`, cls: 'text-red-400' },
          { label: 'Win Rate', value: formatPct(parseFloat(m.winRate) * 100), cls: 'text-gray-100' },
          { label: 'Total Trades', value: m.totalTrades ?? '-', cls: 'text-gray-100' },
          { label: 'Profit Factor', value: m.profitFactor ? parseFloat(m.profitFactor).toFixed(2) : '-', cls: m.profitFactor && parseFloat(m.profitFactor) >= 1 ? 'text-emerald-400' : 'text-red-400' },
          { label: 'Sharpe', value: parseFloat(m.sharpeRatio || 0).toFixed(2), cls: 'text-gray-100' },
          { label: 'Sortino', value: parseFloat(m.sortinoRatio || 0).toFixed(2), cls: 'text-gray-100' },
          { label: 'Calmar', value: parseFloat(m.calmarRatio || 0).toFixed(2), cls: 'text-gray-100' },
          { label: 'Expectancy', value: m.expectancy ? formatPnl(m.expectancy).value : '-', cls: m.expectancy ? getPnlClass(m.expectancy) : 'text-gray-300' },
          { label: 'Leverage', value: `${activeResult.leverage}x`, cls: 'text-gray-100' },
          { label: 'Fee Rate', value: `${((activeResult.feeRate || 0) * 100).toFixed(2)}%`, cls: 'text-gray-100' },
          { label: 'Total Fees', value: m.totalFees ? formatPrice(m.totalFees) : '-', cls: 'text-red-400' },
          { label: 'Liquidations', value: m.liquidations ?? 0, cls: (m.liquidations ?? 0) > 0 ? 'text-red-400' : 'text-gray-100' },
        ]
        return (
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 border-b border-slate-700/50 divide-x divide-y divide-slate-700/50">
            {metrics.map(({ label, value, cls }) => (
              <div key={label} className="flex flex-col justify-center px-3 h-11 bg-title-bg">
                <span className="text-[9px] uppercase tracking-wider text-gray-500 leading-none mb-1">{label}</span>
                <span className={`text-sm font-bold leading-none ${cls}`}>{value}</span>
              </div>
            ))}
          </div>
        )
      })()}

      <MCSummaryStrip sourceJobId={activeResult.jobId} enabled={activeResult.status === 'completed'} />

      {/* Performance Charts */}
      <div className="border-b border-slate-700/50">
        <div className="h-11 bg-title-bg title-fade flex items-center px-4 border-b border-slate-700/30">
          <span className="text-sm font-semibold text-gray-100">Performance Charts</span>
        </div>
        <div className="p-4">
          <ErrorBoundary label="Equity chart">
            <Suspense fallback={<div className="h-48 flex items-center justify-center"><Loader2 className="size-6 animate-spin text-emerald-400" /></div>}>
              <EquityCurve
                data={activeResult.equityCurve}
                startingCapital={activeResult.capital}
                buyHoldReturnPct={activeResult.metrics?.buyHoldReturnPct || 0}
                benchmark={benchmarkData ?? null}
              />
            </Suspense>
          </ErrorBoundary>
        </div>
      </div>

      {allTradesData && allTradesData.length > 0 && (
        <div className="border-b border-slate-700/50">
          <Suspense fallback={<div className="h-48 flex items-center justify-center"><Loader2 className="size-6 animate-spin text-emerald-400" /></div>}>
            <BacktestCalendar
              trades={allTradesData}
              onSelectPeriod={(trades) => { }}
            />
          </Suspense>
        </div>
      )}
    </>
  )
}
