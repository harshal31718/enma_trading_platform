import { cn } from '@/lib/utils'

const variantClasses = {
  default:     'bg-emerald-400/10 text-emerald-400 border-emerald-400/20',
  info:        'bg-blue-400/10 text-blue-400 border-blue-400/20',
  warning:     'bg-amber-400/10 text-amber-400 border-amber-400/20',
  danger:      'bg-red-400/10 text-red-400 border-red-400/20',
  secondary:   'bg-gray-700/50 text-gray-400 border-gray-600/20',
  destructive: 'bg-red-400/10 text-red-400 border-red-400/20',
  outline:     'bg-transparent text-slate-300 border-slate-700',
  profit:      'bg-emerald-400/10 text-emerald-400 border-emerald-400/20',
  loss:        'bg-red-400/10 text-red-400 border-red-400/20',
}

export function Badge({ className, variant = 'default', children, ...props }) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border',
        variantClasses[variant],
        className
      )}
      {...props}
    >
      {children}
    </span>
  )
}
