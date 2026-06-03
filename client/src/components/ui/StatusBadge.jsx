const config = {
  running: {
    label: 'Running',
    classes: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    dot: true,
  },
  stopped: {
    label: 'Stopped',
    classes: 'bg-gray-700 text-gray-400 border-gray-600',
    dot: false,
  },
  completed: {
    label: 'Completed',
    classes: 'bg-blue-400/10 text-blue-400 border-blue-400/20',
    dot: false,
  },
  failed: {
    label: 'Failed',
    classes: 'bg-red-400/10 text-red-400 border-red-400/20',
    dot: false,
  },
  queued: {
    label: 'Queued',
    classes: 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20',
    dot: false,
  },
  paper: {
    label: 'Paper',
    classes: 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20',
    dot: false,
  },
}

export default function StatusBadge({ status }) {
  const { label, classes, dot } = config[status] ?? config.stopped

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border ${classes}`}
    >
      {dot && (
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
      )}
      {label}
    </span>
  )
}
