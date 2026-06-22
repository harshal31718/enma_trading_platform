import { cn } from '@/lib/utils'

export function Table({ className, wrapperClassName, ...props }) {
  return (
    <div className={cn("relative w-full overflow-auto", wrapperClassName)}>
      <table
        className={cn('w-full caption-bottom text-sm text-gray-100', className)}
        {...props}
      />
    </div>
  )
}

export function TableHeader({ className, ...props }) {
  return <thead className={cn('[&_tr]:border-b border-slate-700/50', className)} {...props} />
}

export function TableBody({ className, ...props }) {
  return (
    <tbody
      className={cn('[&_tr:last-child]:border-0', className)}
      {...props}
    />
  )
}

export function TableRow({ className, ...props }) {
  return (
    <tr
      className={cn(
        'h-11 border-b border-slate-700/30 transition-colors hover:bg-slate-800/20 data-[state=selected]:bg-slate-800/40',
        className
      )}
      {...props}
    />
  )
}

export function TableHead({ className, ...props }) {
  return (
    <th
      className={cn(
        'h-11 px-4 text-left align-middle text-[10px] font-semibold uppercase tracking-wider text-gray-400 [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]',
        className
      )}
      {...props}
    />
  )
}

export function TableCell({ className, ...props }) {
  return (
    <td
      className={cn(
        'px-4 py-2 align-middle [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]',
        className
      )}
      {...props}
    />
  )
}
