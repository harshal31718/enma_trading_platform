import { useState } from 'react'
import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import ImportForm from '@/features/candles/ImportForm'
import ImportProgress from '@/features/candles/ImportProgress'
import ImportHistory from '@/features/candles/ImportHistory'

export default function ImportCandles() {
  const [activeJobId, setActiveJobId] = useState(null)

  return (
    <PageWrapper>
      <PageHeader
        title="Import Candles"
        description="Fetch historical OHLCV data from Binance and store it locally"
      />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
        <div className="lg:col-span-1">
          <ImportForm onJobStarted={(jobId) => setActiveJobId(jobId)} />
          {activeJobId && (
            <div className="mt-4">
              <ImportProgress
                jobId={activeJobId}
                onComplete={() => setActiveJobId(null)}
              />
            </div>
          )}
        </div>
        <div className="lg:col-span-2">
          <ImportHistory />
        </div>
      </div>
    </PageWrapper>
  )
}
