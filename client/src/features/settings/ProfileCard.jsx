// Plan 7 Step 7.4 (CLI-1): extracted out of Settings.jsx.
import { CheckCircle2, Clock, Lock, UserCircle2 } from 'lucide-react'
import Avatar from '@/components/ui/Avatar'
import { useAuth } from '@/hooks/useAuth'

export default function ProfileCard() {
  const { user, hasAlgoAccess } = useAuth()
  const algoStatus = user?.role === 'admin' ? 'granted' : (user?.algoAccess || 'none')

  return (
    <div className="mx-auto max-w-6xl w-full px-0 lg:px-0 mb-0">
      <div className="bg-title-bg border border-slate-700/50 rounded-xl p-6 mb-6">
        <div className="flex items-center gap-2 -mx-6 -mt-6 px-6 py-4 mb-4 rounded-t-xl title-fade border-b border-slate-700/50">
          <UserCircle2 size={15} className="text-emerald-400" />
          <h2 className="text-gray-100 text-sm font-medium">Profile</h2>
        </div>

        <div className="flex items-center gap-4">
          <Avatar src={user?.avatar} name={user?.name} className="w-16 h-16" textClassName="text-xl" />
          <div className="min-w-0">
            <p className="text-gray-100 text-base font-medium truncate">{user?.name}</p>
            <p className="text-slate-400 font-mono text-xs truncate">{user?.email}</p>
            <div className="flex items-center gap-2 mt-2">
              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                user?.role === 'admin'
                  ? 'bg-emerald-400/10 text-emerald-400 border-emerald-500/20'
                  : 'bg-slate-500/10 text-slate-400 border-slate-500/20'
              }`}>
                {user?.role === 'admin' ? 'Admin' : 'User'}
              </span>
              {algoStatus === 'granted' ? (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-emerald-400/10 text-emerald-400 border-emerald-500/20">
                  <CheckCircle2 size={11} /> Algo Allowed
                </span>
              ) : algoStatus === 'requested' ? (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-amber-400/10 text-amber-400 border-amber-500/20">
                  <Clock size={11} /> Algo Requested
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-slate-500/10 text-slate-400 border-slate-500/20">
                  <Lock size={11} /> No Algo Access
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
