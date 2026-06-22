export default function BacktestMetricCard({ title, value, subtext, icon: Icon, valueClassName = 'text-gray-100' }) {
  return (
    <div className="bg-title-bg p-4 flex flex-col justify-between min-h-[96px]">
      <div className="flex items-center justify-between text-gray-500 text-xs font-semibold uppercase tracking-wider">
        <span>{title}</span>
        {Icon && (
          <div className="bg-gray-800 rounded-md p-1.5">
            <Icon className="size-4 text-gray-400" />
          </div>
        )}
      </div>
      <div className="mt-3">
        <div className={`text-xl font-bold ${valueClassName}`}>{value}</div>
        {subtext && <div className="text-xs text-gray-500 mt-0.5">{subtext}</div>}
      </div>
    </div>
  )
}
