// Plan 2 Step 2.2: one render smoke test per top-level page. Not full coverage —
// just proves the harness runs and each page mounts without throwing, so later
// refactors (Plan 7) have a net. API calls are expected to fail/hang in this
// environment (no live server) — pages must already handle that per client
// CLAUDE.md's "all components must handle loading and error states" rule.
import { describe, test, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import Dashboard from '@/pages/Dashboard'
import Backtest from '@/pages/Backtest'
import Strategies from '@/pages/Strategies'
import Settings from '@/pages/Settings'
import Trade from '@/pages/Trade'
import AlgoTrading from '@/pages/AlgoTrading'
import OrderHistory from '@/pages/OrderHistory'
import Login from '@/pages/Login'
import AdminPanel from '@/pages/AdminPanel'
import RiskDashboard from '@/pages/RiskDashboard'
import NotFound from '@/pages/NotFound'

// jsdom has no ResizeObserver/matchMedia/canvas — chart-heavy pages need stubs.
if (typeof window !== 'undefined') {
  window.ResizeObserver = window.ResizeObserver || class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  if (!HTMLCanvasElement.prototype.getContext || !HTMLCanvasElement.prototype.__stubbed) {
    HTMLCanvasElement.prototype.getContext = () => null
    HTMLCanvasElement.prototype.__stubbed = true
  }
  window.matchMedia = window.matchMedia || ((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

function renderPage(ui, { route = '/' } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('top-level page smoke tests', () => {
  test('Login mounts', () => {
    expect(() => renderPage(<Login />, { route: '/login' })).not.toThrow()
  })

  test('Dashboard mounts', () => {
    expect(() => renderPage(<Dashboard />)).not.toThrow()
  })

  test('Backtest mounts', () => {
    expect(() => renderPage(<Backtest />, { route: '/backtest' })).not.toThrow()
  })

  test('Strategies mounts', () => {
    expect(() => renderPage(<Strategies />, { route: '/strategies' })).not.toThrow()
  })

  test('Settings mounts', () => {
    expect(() => renderPage(<Settings />, { route: '/settings' })).not.toThrow()
  })

  test('Trade mounts', () => {
    expect(() => renderPage(<Trade />, { route: '/trade/BTCUSDT' })).not.toThrow()
  })

  test('AlgoTrading mounts', () => {
    expect(() => renderPage(<AlgoTrading />, { route: '/algo' })).not.toThrow()
  })

  test('OrderHistory mounts', () => {
    expect(() => renderPage(<OrderHistory />, { route: '/order-history' })).not.toThrow()
  })

  test('AdminPanel mounts', () => {
    expect(() => renderPage(<AdminPanel />, { route: '/admin' })).not.toThrow()
  })

  test('RiskDashboard mounts', () => {
    expect(() => renderPage(<RiskDashboard />, { route: '/risk-dashboard' })).not.toThrow()
  })

  test('NotFound mounts', () => {
    expect(() => renderPage(<NotFound />, { route: '/nonexistent' })).not.toThrow()
  })
})
