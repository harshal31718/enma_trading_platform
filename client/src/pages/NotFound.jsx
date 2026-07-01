import { Link } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-[#060a0f] text-gray-100 gap-4">
      <AlertTriangle className="h-10 w-10 text-slate-600" />
      <div className="text-center">
        <p className="text-4xl font-bold text-slate-400 font-mono">404</p>
        <p className="mt-2 text-sm text-slate-400">Page not found</p>
      </div>
      <Link
        to="/"
        className="mt-2 rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-2 text-sm text-slate-300 transition-colors hover:bg-slate-700"
      >
        Go to Dashboard
      </Link>
    </div>
  )
}
