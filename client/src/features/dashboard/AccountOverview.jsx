import { Link } from 'react-router-dom'
import { formatPrice, formatPnl } from '@/utils/formatters'

// One account metric tile. Edge-to-edge, separated by borders (design system:
// no rounded corners, gap-0 panels).
function Tile({ label, badge, children }) {
  return (
    <div className="p-4 border-r border-b border-slate-700/50 last:border-r-0 min-h-[88px] flex flex-col justify-between">
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">{label}</span>
        {badge}
      </div>
      <div className="mt-2">{children}</div>
    </div>
  )
}

function TestnetBadge() {
  return (
    <span className="text-[10px] font-semibold uppercase tracking-wider text-yellow-400 bg-yellow-500/10 border border-yellow-500/20 px-1.5 py-0.5">
      Testnet
    </span>
  )
}

function MainnetBadge() {
  return (
    <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 px-1.5 py-0.5">
      Mainnet · RO
    </span>
  )
}

// Renders a balance tile body from a per-env balance object, handling the
// not-configured and fetch-error states.
function BalanceBody({ env }) {
  if (!env || env.configured === false) {
    return (
      <Link to="/settings" className="text-xs text-slate-400 hover:text-emerald-400 transition-colors">
        Add keys in Settings →
      </Link>
    )
  }
  if (env.ok === false) {
    return <div className="text-xs text-red-400 leading-snug">{env.error || 'Unavailable'}</div>
  }
  return (
    <>
      <div className="text-xl font-mono tabular-nums font-bold text-gray-100">
        {formatPrice(env.totalWalletBalance)}
      </div>
      <div className="text-xs text-slate-400 mt-0.5">
        Available {formatPrice(env.availableBalance)}
      </div>
    </>
  )
}

export default function AccountOverview({ balances, positions = [] }) {
  const testnet = balances?.testnet
  const mainnet = balances?.mainnet
  const openCount = Array.isArray(positions)
    ? positions.filter((p) => parseFloat(p.positionAmt) !== 0).length
    : 0

  const upnl = testnet?.ok ? formatPnl(testnet.totalUnrealizedProfit) : null

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-0 border-t border-slate-700/50">
      <Tile label="Testnet Balance" badge={<TestnetBadge />}>
        <BalanceBody env={testnet} />
      </Tile>

      <Tile label="Mainnet Balance" badge={<MainnetBadge />}>
        <BalanceBody env={mainnet} />
      </Tile>

      <Tile label="Unrealized P&L">
        {upnl ? (
          <div className={`text-xl font-mono tabular-nums font-bold ${upnl.isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {upnl.value}
          </div>
        ) : (
          <div className="text-xl font-mono tabular-nums font-bold text-slate-400">—</div>
        )}
        <div className="text-xs text-slate-400 mt-0.5">Testnet open positions</div>
      </Tile>

      <Tile label="Margin Balance">
        <div className="text-xl font-mono tabular-nums font-bold text-gray-100">
          {testnet?.ok ? formatPrice(testnet.totalMarginBalance) : '—'}
        </div>
        <div className="text-xs text-slate-400 mt-0.5">
          {openCount} open position{openCount === 1 ? '' : 's'}
        </div>
      </Tile>
    </div>
  )
}
