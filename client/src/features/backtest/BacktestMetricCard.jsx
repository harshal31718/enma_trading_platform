import { Card } from '../../components/ui/card'

export default function BacktestMetricCard({ title, value, subtext, icon: Icon, valueClassName = 'text-gray-100' }) {
  return (
    <Card className="p-4 flex flex-col justify-between">
      <div className="flex items-center justify-between text-gray-500 text-xs font-semibold uppercase tracking-wider">
        <span>{title}</span>
        {Icon && <Icon className="size-4" />}
      </div>
      <div className="mt-3">
        <div className={`text-xl font-bold ${valueClassName}`}>{value}</div>
        {subtext && <div className="text-xs text-gray-500 mt-0.5">{subtext}</div>}
      </div>
    </Card>
  )
}
