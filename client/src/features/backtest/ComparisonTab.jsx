// Plan 7 Step 7.4 (CLI-1): extracted out of Backtest.jsx.
import { AlertTriangle, Activity, Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import ComparisonTable from './ComparisonTable'

export default function ComparisonTab({ compareError, comparisonIds, comparisonLoading, comparisonResults }) {
  return (
    <>
      {compareError && (
        <div className="shrink-0 mb-3 flex items-center gap-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/25 text-amber-400 text-xs">
          <AlertTriangle className="size-3.5 shrink-0" />
          {compareError}
        </div>
      )}
      {comparisonIds.length < 2 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <div className="flex flex-col items-center gap-3">
              <div className="size-12 rounded-full bg-gray-800 flex items-center justify-center">
                <Activity className="size-5 text-gray-600" />
              </div>
              <p className="text-gray-400 font-medium text-sm">Select runs to compare</p>
              <p className="text-gray-600 text-xs max-w-xs">
                Tick the checkbox on at least 2 completed runs in History to see a side-by-side breakdown here.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : comparisonLoading ? (
        <Card className="h-full flex justify-center items-center py-32">
          <Loader2 className="size-8 animate-spin text-emerald-400" />
        </Card>
      ) : (
        <ComparisonTable results={comparisonResults} />
      )}
    </>
  )
}
