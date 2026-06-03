import { TrendingUp, TrendingDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export default function StatCard({ title, value, subtitle, trend, trendValue, icon: Icon }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 relative">
      {Icon && (
        <div className="absolute top-4 right-4 text-gray-600">
          <Icon size={20} />
        </div>
      )}
      <p className="text-gray-400 text-sm">{title}</p>
      <p className="text-gray-100 text-2xl font-medium mt-1">{value}</p>
      {(subtitle || trend) && (
        <div className="flex items-center gap-1 mt-1">
          {trend === 'up' && (
            <span className="flex items-center gap-1 text-green-400 text-xs">
              <TrendingUp size={12} />
              {trendValue}
            </span>
          )}
          {trend === 'down' && (
            <span className="flex items-center gap-1 text-red-400 text-xs">
              <TrendingDown size={12} />
              {trendValue}
            </span>
          )}
          {trend === 'neutral' && (
            <span className="text-gray-400 text-xs">{trendValue}</span>
          )}
          {subtitle && (
            <span className={cn('text-xs', trend ? 'text-gray-400' : 'text-gray-400')}>
              {subtitle}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
