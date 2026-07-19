import { useState, useRef, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Code2,
  FlaskConical,
  Activity,
  Settings,
  Bot,
  History,
  Shield,
  ShieldCheck,
  Dices,
  LogOut,
  Menu,
  X,
} from 'lucide-react'
import { useAlgoSessions } from '../../hooks/useAlgoSessions'
import { useAuth, useLogout } from '../../hooks/useAuth'
import Avatar from '../ui/Avatar'

const navItems = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
  { label: 'Trade', icon: Activity, to: '/trade' },
  { label: 'Strategies', icon: Code2, to: '/strategies' },
  { label: 'Risk Dashboard', icon: Shield, to: '/risk-dashboard' },
  { label: 'Backtest', icon: FlaskConical, to: '/backtest' },
  { label: 'Strategy Lab', icon: Dices, to: '/lab' },
  { label: 'AlgoTrading', icon: Bot, to: '/algo' },
  { label: 'Order History', icon: History, to: '/order-history' },
]

export default function Navbar() {
  const { data: algoSessions = [] } = useAlgoSessions()
  const runningCount = algoSessions.filter((s) => s.status === 'running').length
  const { user } = useAuth()
  const logout = useLogout()
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const dropdownRef = useRef(null)
  const mobileMenuRef = useRef(null)

  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setDropdownOpen(false)
      }
      if (mobileMenuRef.current && !mobileMenuRef.current.contains(event.target)) {
        const toggleBtn = document.getElementById('mobile-menu-toggle')
        if (!toggleBtn || !toggleBtn.contains(event.target)) {
          setMobileMenuOpen(false)
        }
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <header className="fixed top-0 left-0 right-0 h-14 bg-title-bg title-fade border-b border-slate-700/50 flex items-center justify-between z-50 px-6">
      <div className="flex items-center gap-3">
        {/* Mobile Hamburger toggle */}
        <button
          id="mobile-menu-toggle"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={mobileMenuOpen}
          aria-controls="mobile-nav-menu"
          className="md:hidden p-1 text-slate-400 hover:text-gray-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 rounded"
        >
          {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>

        <span className="text-emerald-400 font-medium text-lg select-none">ENMA</span>
      </div>

      {/* Desktop Menu */}
      <nav className="hidden md:flex items-center gap-1 flex-1 ml-6">
        {navItems.map(({ label, icon: Icon, to }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            title={label}
            className={({ isActive }) =>
              [
                'inline-flex items-center gap-2 px-3 py-2 text-sm transition-colors rounded font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500',
                isActive
                  ? 'text-emerald-400 bg-emerald-400/10 border-b-2 border-emerald-400'
                  : 'text-slate-400 hover:text-gray-100 hover:bg-slate-800/50 border-b-2 border-transparent',
              ].join(' ')
            }
          >
            <Icon size={16} className="shrink-0" />
            <span className="hidden lg:inline">{label}</span>
            {label === 'AlgoTrading' && runningCount > 0 && (
              <span className="ml-1 text-xs bg-emerald-600 text-white px-1.5 py-0.5 rounded-full leading-none shrink-0">
                {runningCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Avatar wrapper (always on right) */}
      <div className="flex items-center gap-4">
        {user && (
          <>
            <NavLink
              to="/settings"
              title="Settings"
              aria-label="Settings"
              className={({ isActive }) =>
                [
                  'p-1.5 text-slate-400 hover:text-gray-100 hover:bg-slate-800/50 rounded transition-colors',
                  isActive ? 'text-emerald-400 bg-emerald-400/10' : '',
                ].join(' ')
              }
            >
              <Settings size={18} />
            </NavLink>

            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => setDropdownOpen(!dropdownOpen)}
                aria-haspopup="menu"
                aria-expanded={dropdownOpen}
                aria-label="User menu"
                className="flex items-center justify-center [border-radius:50%] hover:ring-2 hover:ring-emerald-500/50 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
              >
              <Avatar src={user.avatar} name={user.name} className="w-8 h-8" />
            </button>

            {dropdownOpen && (
              <div role="menu" className="absolute right-0 mt-2 w-56 bg-[#0d1117] border border-slate-700/50 shadow-2xl py-1 z-50 animate-in fade-in slide-in-from-top-1 duration-150 origin-top-right">
                <div className="px-4 py-2 border-b border-slate-800">
                  <p className="text-xs text-slate-400">Logged in as</p>
                  <p className="text-sm font-medium text-slate-200 truncate" title={user.name}>
                    {user.name}
                  </p>
                  <p className="text-xs text-slate-500 truncate" title={user.email}>
                    {user.email}
                  </p>
                </div>
                {user.role === 'admin' && (
                  <NavLink
                    to="/admin"
                    onClick={() => setDropdownOpen(false)}
                    className={({ isActive }) =>
                      [
                        'flex items-center gap-2 px-4 py-2 text-sm transition-colors',
                        isActive
                          ? 'text-emerald-400 bg-emerald-400/5'
                          : 'text-slate-300 hover:bg-slate-800/50 hover:text-white',
                      ].join(' ')
                    }
                  >
                    <ShieldCheck size={14} />
                    Admin Panel
                  </NavLink>
                )}
                <button
                  onClick={() => {
                    setDropdownOpen(false)
                    logout()
                  }}
                  className="flex w-full items-center gap-2 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800/50 hover:text-red-400 transition-colors text-left"
                >
                  <LogOut size={14} />
                  Log Out
                </button>
              </div>
            )}
          </div>
          </>
        )}
      </div>

      {/* Mobile Drawer menu overlay */}
      {mobileMenuOpen && (
        <div
          id="mobile-nav-menu"
          className="absolute top-14 left-0 right-0 bg-[#0d1117] border-b border-slate-700/50 z-45 flex flex-col p-4 gap-1 md:hidden animate-in slide-in-from-top duration-150"
          ref={mobileMenuRef}
        >
          {navItems.map(({ label, icon: Icon, to }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setMobileMenuOpen(false)}
              className={({ isActive }) =>
                [
                  'flex items-center gap-3 px-4 py-2.5 text-sm transition-colors rounded font-medium',
                  isActive
                    ? 'text-emerald-400 bg-emerald-400/10'
                    : 'text-slate-400 hover:text-gray-100 hover:bg-slate-800/50',
                ].join(' ')
              }
            >
              <Icon size={16} className="shrink-0" />
              <span>{label}</span>
              {label === 'AlgoTrading' && runningCount > 0 && (
                <span className="ml-auto text-xs bg-emerald-600 text-white px-1.5 py-0.5 rounded-full leading-none">
                  {runningCount}
                </span>
              )}
            </NavLink>
          ))}
        </div>
      )}
    </header>
  )
}