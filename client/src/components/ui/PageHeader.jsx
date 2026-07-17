export default function PageHeader({ title, description, actions, children }) {
  return (
    <div className="sticky top-14 z-40 flex items-center justify-between px-6 h-11 border-b border-slate-700/50 bg-title-bg title-fade">
      <div className="flex items-center gap-6 flex-1 min-w-0">
        <div className="flex flex-col justify-center shrink-0">
          <h1 className="text-gray-100 text-base font-semibold tracking-tight">{title}</h1>
          {description && (
            <p className="text-slate-400 text-xs mt-0.5">{description}</p>
          )}
        </div>
        {children && <div className="flex-1 min-w-0 overflow-hidden">{children}</div>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0 ml-4">{actions}</div>}
    </div>
  )
}
