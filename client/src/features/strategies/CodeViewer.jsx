import { useStrategyCode } from '../../hooks/useStrategies'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'

export default function CodeViewer({ strategyId, strategyName, open, onClose }) {
  const { data: code, isLoading, isError } = useStrategyCode(open ? strategyId : null)

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] bg-title-bg border-slate-700/50 flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-gray-100">{strategyName}</DialogTitle>
        </DialogHeader>
        <div className="overflow-auto flex-1 mt-2">
          {isLoading && (
            <div className="space-y-2 p-1">
              {Array.from({ length: 12 }).map((_, i) => (
                <Skeleton key={i} className="h-4 w-full bg-slate-800/50" />
              ))}
            </div>
          )}
          {isError && (
            <p className="text-red-400 text-sm p-2">Failed to load strategy code.</p>
          )}
          {code && (
            <pre className="text-gray-300 text-sm font-mono leading-relaxed whitespace-pre-wrap bg-[#060a0f] border border-slate-700/30 rounded-lg p-4">
              {code}
            </pre>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
