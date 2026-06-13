import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Code2 } from 'lucide-react'
import CodeViewer from './CodeViewer'

const STRATEGY_TYPES = {
  SimpleEMACross: { label: 'Trend Following', variant: 'default' },
  RSIReversion: { label: 'Mean Reversion', variant: 'info' },
  DonchianBreakout: { label: 'Breakout', variant: 'warning' },
  MicroScalper: { label: 'Scalper', variant: 'destructive' },
}

export default function StrategyCard({ strategy }) {
  const [viewOpen, setViewOpen] = useState(false)
  const type = STRATEGY_TYPES[strategy.name] ?? { label: 'Custom', variant: 'default' }

  return (
    <>
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 flex flex-col gap-3 hover:border-gray-700 hover:shadow-lg hover:shadow-black/20 transition-all duration-200">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Code2 className="size-5 text-emerald-400" />
            <h3 className="text-gray-100 font-medium">{strategy.name}</h3>
          </div>
          <Badge variant={type.variant}>{type.label}</Badge>
        </div>
        <p className="text-gray-400 text-sm leading-relaxed">{strategy.description}</p>
        <div className="flex items-center justify-between mt-1">
          <span className="text-gray-600 text-xs">
            {new Date(strategy.createdAt).toLocaleDateString('en-US', {
              year: 'numeric', month: 'short', day: 'numeric'
            })}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setViewOpen(true)}
          >
            View Code
          </Button>
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
