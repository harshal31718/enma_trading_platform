// Plan 7 Step 7.4 (CLI-1): extracted out of Settings.jsx.
import { Bot, CheckCircle2, Clock, Lock } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/hooks/useAuth'
import { useRequestAlgoAccess } from '@/hooks/useAlgoAccess'

export default function AlgoAccessCard() {
  const { user } = useAuth()
  const requestAccess = useRequestAlgoAccess()
  const algoStatus = user?.role === 'admin' ? 'granted' : (user?.algoAccess || 'none')

  function handleRequestAccess() {
    requestAccess.mutate(undefined, {
      onSuccess: () => toast.success('Access requested — an admin will review it'),
      onError: (err) => toast.error(err.response?.data?.message || err.message || 'Failed to request access'),
    })
  }

  return (
    <div className="mx-auto max-w-6xl w-full px-0 lg:px-0 mb-0">
      <div className="bg-title-bg border border-slate-700/50 rounded-xl p-6 mb-6">
        <div className="flex items-center justify-between -mx-6 -mt-6 px-6 py-4 mb-4 rounded-t-xl title-fade border-b border-slate-700/50">
          <div className="flex items-center gap-2">
            <Bot size={15} className="text-emerald-400" />
            <h2 className="text-gray-100 text-sm font-medium">Algo Trading Access</h2>
          </div>
          {algoStatus === 'granted' ? (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-emerald-400/10 text-emerald-400 border-emerald-500/20">
              <CheckCircle2 size={11} /> Allowed
            </span>
          ) : algoStatus === 'requested' ? (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-amber-400/10 text-amber-400 border-amber-500/20">
              <Clock size={11} /> Requested
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-slate-500/10 text-slate-400 border-slate-500/20">
              <Lock size={11} /> No access
            </span>
          )}
        </div>

        {algoStatus === 'granted' ? (
          <p className="text-sm text-slate-400">
            {user?.role === 'admin'
              ? 'As an admin you have full Algo Trading access — you can start bot sessions and Chaos Mode.'
              : 'You have Algo Trading access. You can start bot sessions and Chaos Mode from the Algo Trading page.'}
          </p>
        ) : algoStatus === 'requested' ? (
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-slate-400">
              Your access request is pending admin approval. You'll be able to start bots once approved.
            </p>
            <Button type="button" disabled variant="secondary" className="shrink-0 opacity-60">
              Request pending
            </Button>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-slate-400">
              Backtesting and manual trading are open to everyone. Starting automated bot sessions and Chaos Mode requires admin approval. Request access to get started.
            </p>
            <Button
              type="button"
              onClick={handleRequestAccess}
              disabled={requestAccess.isPending}
              className="shrink-0 bg-emerald-600 hover:bg-emerald-700"
            >
              {requestAccess.isPending ? 'Requesting…' : 'Request Access'}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
