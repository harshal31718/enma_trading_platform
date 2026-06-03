import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Code2,
  Download,
  FlaskConical,
  Activity,
  Settings,
} from 'lucide-react'

const navItems = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
  { label: 'Strategies', icon: Code2, to: '/strategies' },
  { label: 'Import Candles', icon: Download, to: '/import' },
  { label: 'Backtest', icon: FlaskConical, to: '/backtest' },
  { label: 'Live Trading', icon: Activity, to: '/live' },
  { label: 'Settings', icon: Settings, to: '/settings' },
]

export default function Navbar() {
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
          </NavLink>
        ))}
      </nav>
    </header>
  )
}
