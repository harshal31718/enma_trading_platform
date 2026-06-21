import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Code2,
  FlaskConical,
  Activity,
  Settings,
  Bot,
  History,
} from 'lucide-react'
import { useAlgoSessions } from '../../hooks/useAlgoSessions'

const navItems = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
  { label: 'Strategies', icon: Code2, to: '/strategies' },
  { label: 'Backtest', icon: FlaskConical, to: '/backtest' },
  { label: 'Trade', icon: Activity, to: '/trade' },
  { label: 'AlgoTrading', icon: Bot, to: '/algo' },
  { label: 'Order History', icon: History, to: '/order-history' },
  { label: 'Settings', icon: Settings, to: '/settings' },
]

export default function Navbar() {
  const { data: algoSessions = [] } = useAlgoSessions()
  const runningCount = algoSessions.filter((s) => s.status === 'running').length

  return (
    <header className="fixed top-0 left-0 right-0 h-14 bg-gray-900 border-b border-gray-800 flex items-center z-50">
      <div className="pl-6 w-[180px] shrink-0">
        <span className="text-emerald-400 font-medium text-lg">Enma</span>
      </div>

      <nav className="flex items-center gap-1">
        {navItems.map(({ label, icon: Icon, to }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              [
                'inline-flex items-center gap-2 px-4 py-3 text-sm transition-colors rounded',
                isActive
                  ? 'text-emerald-400 bg-emerald-500/10 border-b-2 border-emerald-500'
                  : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800/50',
              ].join(' ')
            }
          >
            <Icon size={16} />
            {label}
            {label === 'AlgoTrading' && runningCount > 0 && (
              <span className="ml-1 text-xs bg-emerald-600 text-white px-1.5 py-0.5 rounded-full leading-none">
                {runningCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
    </header>
  )
}
