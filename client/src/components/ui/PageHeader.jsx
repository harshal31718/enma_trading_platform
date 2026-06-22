export default function PageHeader({ title, description, actions }) {
  return (
    <div className="sticky top-14 z-40 flex items-center justify-between px-6 h-11 border-b border-slate-700/50 bg-title-bg title-fade">
      <div>
        <h1 className="text-gray-100 text-base font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="text-slate-400 text-xs mt-0.5">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
