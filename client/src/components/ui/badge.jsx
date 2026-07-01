import React from 'react'
import { cn } from '@/lib/utils'

const VARIANT_MAP = {
  default: 'bg-slate-800/50 text-slate-400 border border-slate-700/30',
  emerald: 'bg-emerald-400/10 text-emerald-400 border border-emerald-400/20',
  red: 'bg-red-400/10 text-red-400 border border-red-400/20',
  yellow: 'bg-yellow-400/10 text-yellow-400 border border-yellow-400/20',
  orange: 'bg-orange-400/10 text-orange-400 border border-orange-400/20',
  indigo: 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20',
  gray: 'bg-gray-700/50 text-gray-400 border border-gray-600/20',
}

const ALIAS_MAP = {
  long: 'emerald',
  buy: 'emerald',
  running: 'emerald',
  completed: 'emerald',
  short: 'red',
  sell: 'red',
  error: 'red',
  failed: 'red',
  starting: 'yellow',
  warning: 'orange',
  stopping: 'orange',
  cancelled: 'orange',
  bot: 'indigo',
  manual: 'default',
}

export function Badge({ children, variant = 'default', className, ...props }) {
  const resolvedVariant = ALIAS_MAP[variant] || variant
  const styleCls = VARIANT_MAP[resolvedVariant] || VARIANT_MAP.default

  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider',
        styleCls,
        className
      )}
      {...props}
    >
      {children}
    </span>
  )
}

export default Badge
