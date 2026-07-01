import { useState } from 'react'
import { Code2, Plus } from 'lucide-react'
import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import StrategyCard from '../features/strategies/StrategyCard'
import StrategyCreateDialog from '../features/strategies/StrategyCreateDialog'
import { Skeleton } from '../components/ui/skeleton'
import { useStrategies } from '../hooks/useStrategies'
import EmptyState from '../components/ui/empty-state'

export default function Strategies() {
  const { data: strategies, isLoading, isError } = useStrategies()
  const [createOpen, setCreateOpen] = useState(false)
  const [createDefaultMode, setCreateDefaultMode] = useState('blank')
  const [createDefaultSourceId, setCreateDefaultSourceId] = useState('')

  const openNewStrategy = () => {
    setCreateDefaultMode('blank')
    setCreateDefaultSourceId('')
    setCreateOpen(true)
  }

  const openCloneStrategy = (strategyId) => {
    setCreateDefaultMode('clone')
    setCreateDefaultSourceId(strategyId)
    setCreateOpen(true)
  }

  return (
    <PageWrapper>
      <div className="flex flex-col gap-0">
        <PageHeader
          title="Strategies"
          actions={
            <button
              onClick={openNewStrategy}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg transition-colors"
            >
              <Plus size={16} />
              New strategy
            </button>
          }
        />

        <div>
          {isLoading && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-0">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-44 bg-slate-800/50" />
              ))}
            </div>
          )}
          {isError && (
            <p className="text-red-400 text-sm">Failed to load strategies.</p>
          )}
          {strategies?.length === 0 && !isLoading && (
            <EmptyState
              icon={Code2}
              title="No strategies found"
              description="Default strategies will appear here after engine startup."
              action={{
                label: 'Create Strategy',
                onClick: openNewStrategy
              }}
            />
          )}
          {strategies?.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-0">
              {strategies.map((strategy) => (
                <StrategyCard
                  key={strategy.id}
                  strategy={strategy}
                  onClone={() => openCloneStrategy(strategy.id)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <StrategyCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        strategies={strategies || []}
        defaultMode={createDefaultMode}
        defaultSourceId={createDefaultSourceId}
      />
    </PageWrapper>
  )
}
