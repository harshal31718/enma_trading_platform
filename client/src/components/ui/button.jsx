import { cn } from '@/lib/utils'

const variantClasses = {
  default:   'bg-emerald-600 text-white hover:bg-emerald-500',
  secondary: 'bg-gray-800 text-gray-100 hover:bg-gray-700',
  outline:   'border border-gray-700 bg-transparent text-gray-300 hover:bg-gray-800 hover:text-gray-100',
  ghost:     'bg-transparent text-gray-300 hover:bg-gray-800 hover:text-gray-100',
  danger:    'bg-red-600 text-white hover:bg-red-500',
  warning:   'bg-yellow-500 text-gray-950 hover:bg-yellow-400',
}

const sizeClasses = {
  default: 'h-9 px-4 py-2 text-sm',
  sm:      'h-7 px-3 py-1 text-xs',
  lg:      'h-11 px-6 py-2 text-base',
  icon:    'h-9 w-9',
}

export function Button({ className, variant = 'default', size = 'default', children, ...props }) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500',
        'disabled:pointer-events-none disabled:opacity-50',
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {children}
    </button>
  )
}
