import React, { useState } from 'react'
import { useBacktestsList } from '../../hooks/useBacktest'
import { useBacktestSimulation } from '../../hooks/useRiskSettings'

export default function SimulationResults() {
  const [selectedJobId, setSelectedJobId] = useState('')
  
  // Fetch up to 50 completed backtests to populate the selector dropdown
  const { data: backtestData, isLoading: listLoading } = useBacktestsList(1, 50, { status: 'completed' })
  const backtests = backtestData?.backtests || []

  // Fetch simulation results for the selected backtest
  const { data: simData, isLoading: simLoading, error: simError } = useBacktestSimulation(selectedJobId)

  const handleSelectChange = (e) => {
    setSelectedJobId(e.target.value)
  }

  const sensitivity = simData?.leverageSensitivity || []
  const monteCarlo = simData?.monteCarlo || {}
  const dist = monteCarlo.drawdownDistribution || []

  return (
    <div className="bg-slate-950 border border-slate-800 p-5 shadow-2xl h-full flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-1">
              Backtest & Historical Risk Profiler
            </h3>
            <p className="text-xs text-slate-400">Analyze leverage sensitivity and Monte Carlo bootstrap resamples</p>
          </div>
          
          <select
            className="bg-slate-900 border border-slate-700 text-xs font-mono text-slate-300 px-2 py-1 outline-none focus:border-emerald-500 max-w-[200px]"
            value={selectedJobId}
            onChange={handleSelectChange}
            disabled={listLoading}
          >
            <option value="">-- Select Backtest --</option>
            {backtests.map((b) => (
              <option key={b.jobId} value={b.jobId}>
                {b.strategyName} - {b.symbol} ({new Date(b.createdAt).toLocaleDateString()})
              </option>
            ))}
          </select>
        </div>

        {listLoading && <p className="text-xs text-slate-400 italic text-center py-4">Loading backtests...</p>}

        {!selectedJobId && !listLoading && (
          <div className="border border-dashed border-slate-800 p-8 text-center text-xs text-slate-400 font-mono italic">
            Please select a completed backtest from the dropdown to run leverage sensitivity and Monte Carlo resampling simulations.
          </div>
        )}

        {selectedJobId && simLoading && (
          <p className="text-xs text-emerald-400 font-mono italic text-center py-8 animate-pulse">
            ⚡ Running simulations on engine... this may take a few seconds
          </p>
        )}

        {selectedJobId && simError && (
          <p className="text-xs text-red-400 font-mono text-center py-8">
            ❌ Simulation failed: {simError.message || 'Check engine logs.'}
          </p>
        )}

        {selectedJobId && !simLoading && !simError && simData && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
            {/* Leverage Sensitivity Panel */}
            <div className="border border-slate-800 p-4">
              <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-3">
                Leverage Sensitivity Analysis
              </h4>
              <div className="overflow-x-auto">
                <table className="w-full text-xs font-mono text-left">
                  <thead>
                    <tr className="border-b border-slate-800 text-[10px] text-slate-400 uppercase tracking-wider">
                      <th className="pb-2">Leverage</th>
                      <th className="pb-2 text-right">Net Profit %</th>
                      <th className="pb-2 text-right">Max Drawdown %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sensitivity.map((s) => {
                      const netProfit = parseFloat(s.netProfitPct) || 0.0
                      const maxDD = parseFloat(s.maxDrawdownPct) || 0.0
                      return (
                        <tr key={s.leverage} className="border-b border-slate-900/60 hover:bg-slate-900/40">
                          <td className="py-2 text-slate-300 font-bold">{s.leverage}x</td>
                          <td className={`py-2 text-right font-semibold ${netProfit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {netProfit >= 0 ? '+' : ''}{netProfit.toFixed(2)}%
                          </td>
                          <td className="py-2 text-right text-red-400 font-semibold">
                            {maxDD.toFixed(2)}%
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Monte Carlo Bootstrap Resampler Panel */}
            <div className="border border-slate-800 p-4 flex flex-col justify-between">
              <div>
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-3">
                  Monte Carlo Resampling (N={monteCarlo.meta?.nRuns ?? 2000})
                </h4>
                <div className="flex items-center justify-between mb-4 bg-slate-900/50 p-2.5 border border-slate-850">
                  <span className="text-xs text-slate-400">Probability of Ruin (30% Drawdown)</span>
                  <span className={`text-base font-mono font-bold ${(parseFloat(monteCarlo.ruinProbability) || 0) > 0.1 ? 'text-red-400' : 'text-emerald-400'}`}>
                    {((parseFloat(monteCarlo.ruinProbability) || 0.0) * 100).toFixed(1)}%
                  </span>
                </div>
                
                <h5 className="text-[9px] uppercase tracking-wider text-slate-400 font-bold mb-2">
                  Drawdown Excursion Probability
                </h5>
                <div className="flex flex-col gap-1.5 font-mono text-xs">
                  {dist.map((d) => {
                    const prob = (parseFloat(d.probability) || 0.0) * 100
                    return (
                      <div key={d.drawdownPct} className="flex justify-between items-center">
                        <span className="text-slate-400">Exceeding {parseFloat(d.drawdownPct).toFixed(0)}% Drawdown</span>
                        <span className="text-slate-200 font-bold">{prob.toFixed(1)}%</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
