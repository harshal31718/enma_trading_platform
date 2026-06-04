import { cn } from '@/lib/utils'

const variantClasses = {
  default:     'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  info:        'bg-blue-500/15 text-blue-400 border-blue-500/20',
  warning:     'bg-yellow-500/15 text-yellow-400 border-yellow-500/20',
  danger:      'bg-red-500/15 text-red-400 border-red-500/20',
  secondary:   'bg-gray-700 text-gray-300 border-gray-600',
  destructive: 'bg-red-400/10 text-red-400 border-red-400/20',
  outline:     'bg-transparent text-gray-300 border-gray-700',
  profit:      'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  loss:        'bg-red-500/15 text-red-400 border-red-500/20',
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
