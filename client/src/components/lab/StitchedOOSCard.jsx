// Plan 10 Phase 3a's stitched-OOS aggregate — trade-level approximation
// (documented in walk_forward.py: concatenates each fold's OOS trades,
// pnl/capital-additive, scale_out excluded — NOT the candle-level Sharpe a
// single contiguous backtest reports, since folds have calendar gaps).
export default function StitchedOOSCard({ stitchedOOS, minTradesWarning }) {
  if (!stitchedOOS) return null

  const netProfitPct = parseFloat(stitchedOOS.netProfitPct)
  const winRate = parseFloat(stitchedOOS.winRate) * 100

  return (
    <div className="border border-slate-800 bg-slate-950 p-4">
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
        Stitched out-of-sample summary
      </h4>
      <p className="text-[9px] text-slate-600 mb-3 italic">
        Trade-level approximation across all folds' test windows — not a candle-level Sharpe
      </p>
      <div className="grid grid-cols-4 gap-3 text-center">
        <div>
          <div className="text-[9px] text-slate-500 uppercase">Trades</div>
          <div className="text-sm font-mono font-bold text-slate-200">{stitchedOOS.totalTrades}</div>
        </div>
        <div>
          <div className="text-[9px] text-slate-500 uppercase">Net profit</div>
          <div className={`text-sm font-mono font-bold ${netProfitPct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {netProfitPct >= 0 ? '+' : ''}{netProfitPct.toFixed(2)}%
          </div>
        </div>
        <div>
          <div className="text-[9px] text-slate-500 uppercase">Win rate</div>
          <div className="text-sm font-mono font-bold text-slate-200">{winRate.toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-[9px] text-slate-500 uppercase">Trade Sharpe (approx)</div>
          <div className="text-sm font-mono font-bold text-slate-200">{stitchedOOS.tradeSharpeApprox}</div>
        </div>
      </div>
      {minTradesWarning && (
        <p className="text-[10px] text-amber-400 font-mono mt-3">⚠ {minTradesWarning}</p>
      )}
    </div>
  )
}
