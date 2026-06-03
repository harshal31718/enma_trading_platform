/**
 * OCO feature tests
 *
 * Covers:
 *  1. OCO validation logic (price relationship rules)
 *  2. Risk-position-sizing auto-quantity formula
 *  3. extractOcoId helper (OCO Group column)
 *  4. useOcoMonitor — sibling cancellation and event firing
 *  5. usePlaceOCOOrder mutation
 *  6. useCancelAllOrders mutation
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

// ── Inline helpers duplicated from Trade.jsx / useOcoMonitor for unit testing ──

function extractOcoId(clientOrderId) {
  if (!clientOrderId) return null
  const m = clientOrderId.match(/^(oco_[0-9a-f]{8}_)(?:sl|tp)$/)
  return m ? m[1] : null
}

function validateOco(side, marketPrice, stopPrice, takeProfitPrice) {
  const mp = marketPrice
  const sl = parseFloat(stopPrice)
  const tp = parseFloat(takeProfitPrice)
  if (isNaN(sl) || sl <= 0) return 'Stop-loss price is required'
  if (isNaN(tp) || tp <= 0) return 'Take-profit price is required'
  if (side === 'BUY') {
    if (!(sl < mp && mp < tp)) return `Long OCO: stop-loss must be below market and take-profit above market`
  } else {
    if (!(tp < mp && mp < sl)) return `Short OCO: take-profit must be below market and stop-loss above market`
  }
  return null
}

function calcQuantityFromRisk({ totalEquity, riskPct, entryPrice, stopPrice }) {
  const riskUSDT = totalEquity * (riskPct / 100)
  const priceDiff = Math.abs(entryPrice - stopPrice)
  if (priceDiff <= 0) return 0
  return riskUSDT / priceDiff
}

// ── 1. extractOcoId ───────────────────────────────────────────────────────────

describe('extractOcoId', () => {
  it('extracts prefix from SL clientOrderId', () => {
    expect(extractOcoId('oco_a1b2c3d4_sl')).toBe('oco_a1b2c3d4_')
  })

  it('extracts prefix from TP clientOrderId', () => {
    expect(extractOcoId('oco_a1b2c3d4_tp')).toBe('oco_a1b2c3d4_')
  })

  it('returns null for non-OCO clientOrderId', () => {
    expect(extractOcoId('web_x92837')).toBeNull()
  })

  it('returns null for empty string', () => {
    expect(extractOcoId('')).toBeNull()
  })

  it('returns null for undefined', () => {
    expect(extractOcoId(undefined)).toBeNull()
  })

  it('SL and TP share same prefix', () => {
    const ocoId = 'oco_deadbeef_'
    expect(extractOcoId(`${ocoId}sl`)).toBe(ocoId)
    expect(extractOcoId(`${ocoId}tp`)).toBe(ocoId)
  })
})

// ── 2. OCO validation ─────────────────────────────────────────────────────────

describe('validateOco', () => {
  const MARKET = 65000

  describe('BUY (Long) — SL < market < TP', () => {
    it('passes when SL < market < TP', () => {
      expect(validateOco('BUY', MARKET, '60000', '70000')).toBeNull()
    })

    it('fails when SL is above market', () => {
      const err = validateOco('BUY', MARKET, '66000', '70000')
      expect(err).toMatch(/stop-loss must be below market/)
    })

    it('fails when TP is below market', () => {
      const err = validateOco('BUY', MARKET, '60000', '63000')
      expect(err).toMatch(/take-profit above market/)
    })

    it('fails when SL equals market', () => {
      const err = validateOco('BUY', MARKET, String(MARKET), '70000')
      expect(err).not.toBeNull()
    })

    it('fails when SL is zero', () => {
      const err = validateOco('BUY', MARKET, '0', '70000')
      expect(err).toMatch(/stop-loss price is required/i)
    })

    it('fails when TP is missing', () => {
      const err = validateOco('BUY', MARKET, '60000', '')
      expect(err).toMatch(/take-profit price is required/i)
    })
  })

  describe('SELL (Short) — TP < market < SL', () => {
    it('passes when TP < market < SL', () => {
      expect(validateOco('SELL', MARKET, '70000', '60000')).toBeNull()
    })

    it('fails when SL is below market', () => {
      const err = validateOco('SELL', MARKET, '63000', '60000')
      expect(err).toMatch(/stop-loss above market/)
    })

    it('fails when TP is above market', () => {
      const err = validateOco('SELL', MARKET, '70000', '66000')
      expect(err).toMatch(/take-profit must be below market/)
    })
  })
})

// ── 3. Risk-position-sizing formula ──────────────────────────────────────────

describe('calcQuantityFromRisk', () => {
  it('computes correct quantity for 1% risk', () => {
    // equity=10000, risk=1% → riskUSDT=100, diff=1000 → qty=0.1
    const qty = calcQuantityFromRisk({
      totalEquity: 10000,
      riskPct: 1,
      entryPrice: 65000,
      stopPrice: 64000,
    })
    expect(qty).toBeCloseTo(0.1, 5)
  })

  it('computes correct quantity for 2% risk', () => {
    // equity=10000, risk=2% → riskUSDT=200, diff=500 → qty=0.4
    const qty = calcQuantityFromRisk({
      totalEquity: 10000,
      riskPct: 2,
      entryPrice: 65000,
      stopPrice: 64500,
    })
    expect(qty).toBeCloseTo(0.4, 5)
  })

  it('returns 0 when entry equals stop (avoid division by zero)', () => {
    const qty = calcQuantityFromRisk({
      totalEquity: 10000,
      riskPct: 1,
      entryPrice: 65000,
      stopPrice: 65000,
    })
    expect(qty).toBe(0)
  })

  it('handles short direction (stop above entry)', () => {
    // equity=5000, risk=1% → riskUSDT=50, diff=250 → qty=0.2
    const qty = calcQuantityFromRisk({
      totalEquity: 5000,
      riskPct: 1,
      entryPrice: 65000,
      stopPrice: 65250,
    })
    expect(qty).toBeCloseTo(0.2, 5)
  })
})

// ── 4. useOcoMonitor ─────────────────────────────────────────────────────────

// Mock axios so no real HTTP calls are made anywhere in the test suite.
vi.mock('@/lib/axios', () => ({
  default: { get: vi.fn(), delete: vi.fn(), post: vi.fn() },
}))

// Partially mock useTrade: only stub useTradeOpenOrders (used by useOcoMonitor).
// usePlaceOCOOrder and useCancelAllOrders use the real implementations so their
// mutation tests exercise the actual hook code path.
vi.mock('@/hooks/useTrade', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real, useTradeOpenOrders: vi.fn() }
})

import api from '@/lib/axios'
import useOcoMonitor from '@/hooks/useOcoMonitor'
import { useTradeOpenOrders, usePlaceOCOOrder, useCancelAllOrders as useCancelAll } from '@/hooks/useTrade'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useOcoMonitor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does nothing when there are no OCO orders', async () => {
    useTradeOpenOrders.mockReturnValue({ data: [{ orderId: 1, clientOrderId: 'web_123' }] })
    const onEvent = vi.fn()

    renderHook(() => useOcoMonitor({ symbol: 'BTC-USDT', onEvent }), {
      wrapper: makeWrapper(),
    })

    await waitFor(() => {})
    expect(onEvent).not.toHaveBeenCalled()
    expect(api.get).not.toHaveBeenCalled()
  })

  it('fetches order status when an OCO leg disappears', async () => {
    const ocoId = 'oco_deadbeef_'
    const slOrderId = 9001
    const tpOrderId = 9002

    // First render: both legs present
    useTradeOpenOrders.mockReturnValueOnce({
      data: [
        { orderId: slOrderId, clientOrderId: `${ocoId}sl` },
        { orderId: tpOrderId, clientOrderId: `${ocoId}tp` },
      ],
    })

    // Second render: SL leg disappeared (filled), TP still open
    useTradeOpenOrders.mockReturnValue({
      data: [{ orderId: tpOrderId, clientOrderId: `${ocoId}tp` }],
    })

    api.get.mockResolvedValue({ data: { data: { orderId: slOrderId, status: 'FILLED' } } })
    api.delete.mockResolvedValue({ data: {} })

    const onEvent = vi.fn()
    const { rerender } = renderHook(() => useOcoMonitor({ symbol: 'BTC-USDT', onEvent }), {
      wrapper: makeWrapper(),
    })

    rerender()

    await waitFor(() => expect(api.get).toHaveBeenCalled())
    await waitFor(() => expect(api.delete).toHaveBeenCalled())
    await waitFor(() => expect(onEvent).toHaveBeenCalled())

    const eventMsg = onEvent.mock.calls[0][0]
    expect(eventMsg).toMatch(/stop-loss triggered/i)
    expect(eventMsg).toMatch(/take-profit order cancelled/i)
  })

  it('does not cancel sibling if disappearance was not a fill', async () => {
    const ocoId = 'oco_aabbccdd_'
    const slOrderId = 9003
    const tpOrderId = 9004

    useTradeOpenOrders.mockReturnValueOnce({
      data: [
        { orderId: slOrderId, clientOrderId: `${ocoId}sl` },
        { orderId: tpOrderId, clientOrderId: `${ocoId}tp` },
      ],
    })
    useTradeOpenOrders.mockReturnValue({
      data: [{ orderId: tpOrderId, clientOrderId: `${ocoId}tp` }],
    })

    // Status is CANCELED (user cancelled it manually) — not FILLED
    api.get.mockResolvedValue({ data: { data: { orderId: slOrderId, status: 'CANCELED' } } })

    const onEvent = vi.fn()
    const { rerender } = renderHook(() => useOcoMonitor({ symbol: 'BTC-USDT', onEvent }), {
      wrapper: makeWrapper(),
    })

    rerender()

    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(api.delete).not.toHaveBeenCalled()
    expect(onEvent).not.toHaveBeenCalled()
  })
})

// ── 5. usePlaceOCOOrder mutation ──────────────────────────────────────────────

// useTrade hooks use the real implementation; axios is already mocked above

describe('usePlaceOCOOrder', () => {
  beforeEach(() => vi.clearAllMocks())

  it('calls the correct endpoint with the right payload', async () => {
    api.post = vi.fn().mockResolvedValue({
      data: { data: { ocoId: 'oco_12345678_', orders: [] } },
    })

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    const { result } = renderHook(() => usePlaceOCOOrder(), { wrapper })

    await act(async () => {
      result.current.mutate({
        symbol: 'BTC-USDT',
        side: 'BUY',
        quantity: 0.01,
        stopPrice: 60000,
        takeProfitPrice: 70000,
      })
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(api.post).toHaveBeenCalledWith(
      '/api/v1/trade/order/oco_futures',
      expect.objectContaining({
        symbol: 'BTC-USDT',
        side: 'BUY',
        quantity: 0.01,
        stopPrice: 60000,
        takeProfitPrice: 70000,
      })
    )
  })
})

// ── 6. useCancelAllOrders mutation ────────────────────────────────────────────

describe('useCancelAllOrders', () => {
  beforeEach(() => vi.clearAllMocks())

  it('calls DELETE /api/v1/trade/all-orders with symbol param', async () => {
    api.delete = vi.fn().mockResolvedValue({ data: { data: { cancelled: true } } })

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    const { result } = renderHook(() => useCancelAll(), { wrapper })

    await act(async () => {
      result.current.mutate({ symbol: 'BTC-USDT' })
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(api.delete).toHaveBeenCalledWith(
      '/api/v1/trade/all-orders',
      expect.objectContaining({ params: { symbol: 'BTC-USDT' } })
    )
  })
})
