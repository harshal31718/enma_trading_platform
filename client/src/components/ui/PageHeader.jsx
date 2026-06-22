export default function PageHeader({ title, description, actions }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="text-gray-100 text-xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="text-slate-400 text-sm mt-0.5">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
