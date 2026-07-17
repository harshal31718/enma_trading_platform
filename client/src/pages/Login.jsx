import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import {
  FlaskConical,
  Bot,
  Activity,
  Shield,
  AlertTriangle,
} from 'lucide-react'

const FEATURES = [
  {
    icon: FlaskConical,
    title: 'Backtesting Engine',
    description:
      'Strict sequential candle replay with isolated-margin futures, maker/taker fees, slippage, and liquidation modeling.',
    color: 'text-emerald-400',
    bg: 'bg-emerald-400/5',
    borderHover: 'hover:border-emerald-500/30',
  },
  {
    icon: Bot,
    title: 'Algo Trading Bots',
    description:
      'Deploy Python strategies as live bots — candle-driven execution with exchange-reconciled state.',
    color: 'text-sky-400',
    bg: 'bg-sky-400/5',
    borderHover: 'hover:border-sky-500/30',
  },
  {
    icon: Activity,
    title: 'Trading Terminal',
    description:
      'Real-time charts, orderbook, and order placement with TP/SL on Binance Futures Testnet.',
    color: 'text-violet-400',
    bg: 'bg-violet-400/5',
    borderHover: 'hover:border-violet-500/30',
  },
  {
    icon: Shield,
    title: 'Risk Intelligence',
    description:
      'Portfolio VaR/CVaR, Monte Carlo simulations, hierarchical risk overrides, and position sizing.',
    color: 'text-amber-400',
    bg: 'bg-amber-400/5',
    borderHover: 'hover:border-amber-500/30',
  },
]

const TECH_STACK = [
  'Python',
  'FastAPI',
  'React',
  'TimescaleDB',
  'Redis',
  'MongoDB',
  'Binance',
]

function AnimatedGridBackground() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {/* Base grid pattern */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: `
            linear-gradient(rgba(52, 211, 153, 0.06) 1px, transparent 1px),
            linear-gradient(90deg, rgba(52, 211, 153, 0.06) 1px, transparent 1px)
          `,
          backgroundSize: '60px 60px',
        }}
      />

      {/* Horizontal animated lines */}
      <div
        className="absolute top-[20%] left-0 w-full h-px"
        style={{
          background:
            'linear-gradient(90deg, transparent, rgba(52, 211, 153, 0.5), transparent)',
          animation: 'grid-line-h 5s linear infinite',
        }}
      />
      <div
        className="absolute top-[45%] left-0 w-full h-px"
        style={{
          background:
            'linear-gradient(90deg, transparent, rgba(52, 211, 153, 0.35), transparent)',
          animation: 'grid-line-h 7s linear infinite 2s',
        }}
      />
      <div
        className="absolute top-[75%] left-0 w-full h-px"
        style={{
          background:
            'linear-gradient(90deg, transparent, rgba(52, 211, 153, 0.4), transparent)',
          animation: 'grid-line-h 6s linear infinite 4s',
        }}
      />

      {/* Vertical animated lines */}
      <div
        className="absolute left-[25%] top-0 w-px h-full"
        style={{
          background:
            'linear-gradient(180deg, transparent, rgba(52, 211, 153, 0.4), transparent)',
          animation: 'grid-line-v 6s linear infinite 1s',
        }}
      />
      <div
        className="absolute left-[65%] top-0 w-px h-full"
        style={{
          background:
            'linear-gradient(180deg, transparent, rgba(52, 211, 153, 0.3), transparent)',
          animation: 'grid-line-v 8s linear infinite 3s',
        }}
      />

      {/* Large emerald glow orb — subtle background accent */}
      <div
        className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px]"
        style={{
          background:
            'radial-gradient(circle, rgba(52, 211, 153, 0.1) 0%, transparent 70%)',
          animation: 'emerald-pulse 4s ease-in-out infinite',
        }}
      />
    </div>
  )
}

function FeatureCard({ icon: Icon, title, description, color, bg, borderHover, delay }) {
  return (
    <div
      className={`${bg} border border-slate-700/40 ${borderHover} p-5 transition-all duration-300 hover:translate-y-[-2px] hover:shadow-lg animate-fade-in-up`}
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex items-start gap-4">
        <div
          className={`shrink-0 w-10 h-10 flex items-center justify-center border border-slate-700/40 ${bg}`}
        >
          <Icon size={20} className={color} />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-gray-100 mb-1">{title}</h3>
          <p className="text-xs text-slate-300 leading-relaxed">{description}</p>
        </div>
      </div>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 0 0 2.38-5.88c0-.57-.05-.66-.15-1.18z"
      />
      <path
        fill="#34A853"
        d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2.01c-.72.48-1.63.76-2.7.76-2.08 0-3.84-1.4-4.47-3.29H1.88v2.07A8 8 0 0 0 8.98 17z"
      />
      <path
        fill="#FBBC05"
        d="M4.51 10.52A4.8 4.8 0 0 1 4.26 9c0-.52.09-1.02.25-1.52V5.41H1.88A8 8 0 0 0 .98 9c0 1.29.31 2.51.9 3.59l2.63-2.07z"
      />
      <path
        fill="#EA4335"
        d="M8.98 3.58c1.17 0 2.23.4 3.06 1.2l2.3-2.3A8 8 0 0 0 8.98 1a8 8 0 0 0-7.1 4.41l2.63 2.07c.63-1.89 2.39-3.3 4.47-3.3z"
      />
    </svg>
  )
}

export default function Login() {
  const { isAuthenticated, isLoading } = useAuth()
  const navigate = useNavigate()
  const errorParam = new URLSearchParams(window.location.search).get('error')

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  function handleGoogleLogin() {
    window.location.href = `${import.meta.env.VITE_API_URL}/api/v1/auth/google`
  }

  return (
    <div className="h-screen flex flex-col lg:flex-row bg-[#060a0f] overflow-hidden">
      {/* ═══════════ LEFT PANEL — Feature Showcase ═══════════ */}
      <div className="relative flex-1 flex flex-col justify-center px-8 lg:px-16 py-12 lg:py-0 overflow-y-auto">
        <AnimatedGridBackground />

        {/* Content — sits above the animated background */}
        <div className="relative z-10 max-w-xl mx-auto lg:mx-0 w-full">
          {/* Hero Section */}
          <div className="mb-12 animate-fade-in" style={{ animationDelay: '100ms' }}>
            <div className="flex items-center gap-3 mb-6">
              {/* ENMA wordmark with emerald gradient */}
              <h1
                className="text-5xl lg:text-6xl font-bold tracking-tight"
                style={{
                  background: 'linear-gradient(135deg, #34d399 0%, #6ee7b7 50%, #34d399 100%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  filter: 'drop-shadow(0 0 30px rgba(52, 211, 153, 0.2))',
                }}
              >
                ENMA
              </h1>
            </div>
            <p className="text-xl lg:text-2xl font-semibold text-gray-100 mb-3 leading-tight">
              Algorithmic Trading Platform.
              <br />
              <span className="text-emerald-400">Engineered for Edge.</span>
            </p>
            <p className="text-sm text-slate-400 leading-relaxed max-w-md">
              Build, backtest, and deploy quantitative strategies on Binance
              Futures — with institutional-grade risk controls and real-time
              execution.
            </p>
          </div>

          {/* Feature Cards — 2x2 grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-0">
            {FEATURES.map((feature, i) => (
              <FeatureCard
                key={feature.title}
                {...feature}
                delay={300 + i * 150}
              />
            ))}
          </div>

          {/* Tech Stack Bar */}
          <div
            className="mt-10 flex flex-wrap items-center gap-2 animate-fade-in"
            style={{ animationDelay: '1000ms' }}
          >
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mr-2">
              Built with
            </span>
            {TECH_STACK.map((tech) => (
              <span
                key={tech}
                className="text-[10px] font-mono text-slate-400 bg-slate-800/40 border border-slate-700/30 px-2 py-0.5"
              >
                {tech}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ═══════════ RIGHT PANEL — Login Section ═══════════ */}
      <div className="relative w-full lg:w-[420px] xl:w-[460px] shrink-0 bg-[#0a0d13] border-t lg:border-t-0 lg:border-l border-slate-700/50 flex flex-col items-center justify-center px-8 py-12 lg:py-0">
        {/* Subtle top gradient accent */}
        <div
          className="absolute top-0 left-0 right-0 h-px"
          style={{
            background:
              'linear-gradient(90deg, transparent, rgba(52, 211, 153, 0.3), transparent)',
          }}
        />

        <div className="w-full max-w-[340px] animate-fade-in" style={{ animationDelay: '200ms' }}>
          <div className="bg-white/[0.03] border border-slate-700/50 p-8">
            {/* Heading */}
            <h2 className="text-xl font-semibold text-gray-100 mb-2">Welcome</h2>
            <p className="text-sm text-slate-400 mb-6">
              Sign in to access your trading workspace.
            </p>

            {/* Google Login Button */}
            <button
              onClick={handleGoogleLogin}
              className="w-full flex items-center justify-center gap-3 bg-white hover:bg-gray-50 text-gray-900 text-sm font-medium px-4 py-3 transition-all duration-200 hover:translate-y-[-1px] hover:shadow-lg hover:shadow-emerald-500/5 active:translate-y-0"
            >
              <GoogleIcon />
              Continue with Google
            </button>

            {/* Error State */}
            {errorParam === 'auth_failed' && (
              <div className="mt-5 bg-red-950/20 border border-red-800/40 p-3 animate-shake">
                <div className="flex items-start gap-2">
                  <AlertTriangle
                    size={16}
                    className="text-red-400 shrink-0 mt-0.5"
                  />
                  <div>
                    <p className="text-sm font-medium text-red-400 mb-0.5">
                      Sign-in failed
                    </p>
                    <p className="text-xs text-red-400/80 leading-relaxed">
                      Something went wrong signing you in. Please try again.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer — outside card */}
          <p className="mt-5 text-[10px] text-slate-600 text-center">
            By signing in, you agree to the platform terms of use.
          </p>
        </div>

        {/* Development notice */}
        <div className="absolute bottom-4 right-6">
          <span className="text-[10px] text-slate-600 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 bg-emerald-500/60" style={{ borderRadius: '50%' }} />
            Currently in beta — new features shipping regularly
          </span>
        </div>
      </div>
    </div>
  )
}
