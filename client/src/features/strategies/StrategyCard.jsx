import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Code2 } from 'lucide-react'
import CodeViewer from './CodeViewer'

const STRATEGY_TYPES = {
  MicroScalper: { label: 'Scalper', variant: 'destructive' },
  BestSupertrend: { label: 'Trend Following', variant: 'default' },
  AdaptiveTrend: { label: 'Trend Following', variant: 'default' },
  MicroMacroRSIDivergence: { label: 'Divergence', variant: 'info' },
  MultiDivergence: { label: 'Divergence', variant: 'warning' },
}

export default function StrategyCard({ strategy, onClone }) {
  const [viewOpen, setViewOpen] = useState(false)
  const type = STRATEGY_TYPES[strategy.name] ?? { label: 'Custom', variant: 'default' }

  return (
    <>
      <div className="h-full bg-title-bg border border-slate-700/50 rounded-xl p-5 flex flex-col justify-between gap-3 overflow-hidden hover:border-slate-600/70 hover:shadow-2xl hover:shadow-black/20 transition-all duration-300">
        <div className="flex flex-col gap-3">
          <div className="flex items-start justify-between -mx-5 -mt-5 px-5 pt-5 pb-3 title-fade">
            <div className="flex items-center gap-2">
              <Code2 className="size-5 text-emerald-400" />
              <h3 className="text-gray-100 font-semibold tracking-tight">{strategy.name}</h3>
            </div>
            <Badge variant={type.variant}>{type.label}</Badge>
          </div>
          <p className="text-slate-300 text-sm leading-relaxed">{strategy.description}</p>
          
          {/* Subtle placeholder metrics */}
          <div className="text-[10px] font-mono text-slate-500 flex items-center gap-2 mt-1 select-none">
            <span>Win Rate: <span className="text-slate-400">--%</span></span>
            <span className="text-slate-700">|</span>
            <span>PnL: <span className="text-slate-400">--</span></span>
          </div>
        </div>

        <div className="flex items-center justify-between mt-1 gap-2 pt-3 border-t border-slate-800/60">
          <span className="text-slate-500 text-[10px] font-mono">
            {new Date(strategy.createdAt).toLocaleDateString('en-US', {
              year: 'numeric', month: 'short', day: 'numeric'
            })}
          </span>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setViewOpen(true)}
              className="h-8 text-xs px-3 font-semibold"
            >
              View Code
            </Button>
            <button
              onClick={() => onClone?.()}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors font-semibold px-1"
            >
              Clone
            </button>
          </div>
        </div>
      </div>
      <CodeViewer
        strategyId={strategy.id}
        strategyName={strategy.name}
        open={viewOpen}
        onClose={() => setViewOpen(false)}
      />
    </>
  )
}
