import { Code2 } from 'lucide-react'
import PageWrapper from '../components/layout/PageWrapper'
import PageHeader from '../components/ui/PageHeader'
import EmptyState from '../components/ui/EmptyState'
import StrategyCard from '../features/strategies/StrategyCard'
import { Skeleton } from '../components/ui/skeleton'
import { useStrategies } from '../hooks/useStrategies'

export default function Strategies() {
  const { data: strategies, isLoading, isError } = useStrategies()

  return (
    <PageWrapper>
      <PageHeader
        title="Strategies"
        description="Python trading strategies available for backtesting and live trading"
      />
      <div className="mt-6">
        {isLoading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-44 rounded-lg bg-gray-800" />
            ))}
          </div>
        )}
        {isError && (
          <p className="text-red-400 text-sm">Failed to load strategies.</p>
        )}
        {strategies?.length === 0 && (
          <EmptyState
            icon={Code2}
            title="No strategies found"
            description="Default strategies will appear here after engine startup."
          />
        )}
        {strategies?.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {strategies.map((strategy) => (
              <StrategyCard key={strategy.id} strategy={strategy} />
            ))}
          </div>
        )}
      </div>
    </PageWrapper>
  )
}
