import { Card } from '../../components/ui/card'

export default function StatCard({ title, value, subtext, icon: Icon }) {
  return (
    <Card className="p-4 flex flex-col justify-between min-h-[96px]">
      <div className="flex items-center justify-between text-slate-400 text-[11px] font-semibold uppercase tracking-wider">
        <span>{title}</span>
        {Icon && (
          <div className="bg-emerald-400/10 p-1.5">
            <Icon className="size-4 text-emerald-400" strokeWidth={2} />
          </div>
        )}
      </div>
      <div className="mt-3">
        <div className="text-xl font-bold tabular-nums text-gray-100">{value}</div>
        {subtext && <div className="text-xs text-slate-500 mt-0.5">{subtext}</div>}
      </div>
    </Card>
  )
}
