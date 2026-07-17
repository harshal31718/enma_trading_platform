import { Component } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

/**
 * ErrorBoundary — catches render-time exceptions thrown by descendant components.
 *
 * Usage:
 *   <ErrorBoundary>                         — wraps the full app
 *   <ErrorBoundary label="Equity chart">    — wraps a single chart panel
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
    this.reset = this.reset.bind(this)
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    // Only log component stack in dev to avoid leaking internals in prod
    if (import.meta.env.DEV) {
      console.error('[ErrorBoundary]', error, info.componentStack)
    }
  }

  reset() {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (!this.state.hasError) return this.props.children

    const label = this.props.label ?? 'This section'
    const isDev = import.meta.env.DEV

    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-red-800/30 bg-red-950/10 p-6 text-center">
        <AlertTriangle className="h-6 w-6 text-red-400" />
        <div>
          <p className="text-sm font-medium text-slate-200">{label} crashed</p>
          <p className="mt-1 text-xs text-slate-400">
            An unexpected error occurred while rendering this component.
          </p>
          {isDev && this.state.error && (
            <pre className="mt-2 max-h-32 overflow-auto rounded bg-slate-900 p-2 text-left text-[10px] text-red-300">
              {this.state.error.message}
            </pre>
          )}
        </div>
        <button
          onClick={this.reset}
          className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-slate-700"
        >
          <RefreshCw className="h-3 w-3" />
          Try again
        </button>
      </div>
    )
  }
}
