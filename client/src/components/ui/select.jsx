import { cn } from '@/lib/utils'

export function Select({ className, children, ...props }) {
  return (
    <div className="relative w-full">
      <select
        className={cn(
          'flex h-10 w-full rounded-lg border border-slate-700/50 bg-[#0a0d13] px-3 py-2 text-sm text-gray-100 placeholder:text-slate-600 focus-visible:outline-none focus-visible:border-emerald-500 disabled:cursor-not-allowed disabled:opacity-50 transition-colors appearance-none cursor-pointer pr-10',
          className
        )}
        {...props}
      >
        {children}
      </select>
      <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-slate-400">
        <svg className="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/>
        </svg>
      </div>
    </div>
  )
}
