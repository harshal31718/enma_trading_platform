// Plan 7 Step 7.4 (CLI-1): extracted out of Trade.jsx. Used only by
// PositionsTable.
import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { usePlaceOCOOrder } from '@/hooks/useTrade'
import { fmtPrice, fmtPriceForSymbol, fmtQtyForSymbol } from './formatters'

export default function TpSlModal({ position, onClose }) {
  const [tpEnabled, setTpEnabled] = useState(false)
  const [slEnabled, setSlEnabled] = useState(false)
  const [tpPrice, setTpPrice] = useState('')
  const [slPrice, setSlPrice] = useState('')
  const [submitError, setSubmitError] = useState(null)

  const posSize = parseFloat(position.positionAmt)
  const isLong = posSize > 0
  const quantity = Math.abs(posSize)
  const markPrice = parseFloat(position.markPrice)
  const entryPrice = parseFloat(position.entryPrice)
  const entrySide = isLong ? 'BUY' : 'SELL'
  const displaySymbol = position.symbol.replace('USDT', '-USDT')

  const { mutate: execPlaceOCO, isPending } = usePlaceOCOOrder()

  // Per-field inline validation (derived, no state needed)
  const tpError = (() => {
    if (!tpEnabled || !tpPrice) return null
    const v = parseFloat(tpPrice)
    if (isNaN(v) || v <= 0) return 'Enter a valid price'
    if (isLong && v <= markPrice) return 'Trigger price should be higher than mark price'
    if (!isLong && v >= markPrice) return 'Trigger price should be lower than mark price'
    return null
  })()

  const slError = (() => {
    if (!slEnabled || !slPrice) return null
    const v = parseFloat(slPrice)
    if (isNaN(v) || v <= 0) return 'Enter a valid price'
    if (isLong && v >= markPrice) return 'Trigger price should be lower than mark price'
    if (!isLong && v <= markPrice) return 'Trigger price should be higher than mark price'
    return null
  })()

  const canConfirm =
    !isPending &&
    (tpEnabled || slEnabled) &&
    (!tpEnabled || (tpPrice !== '' && !tpError)) &&
    (!slEnabled || (slPrice !== '' && !slError))

  function handleConfirm() {
    setSubmitError(null)
    execPlaceOCO(
      {
        symbol: displaySymbol,
        side: entrySide,
        quantity,
        stopPrice: slEnabled ? parseFloat(slPrice) : undefined,
        takeProfitPrice: tpEnabled ? parseFloat(tpPrice) : undefined,
      },
      {
        onSuccess: onClose,
        onError: (err) => {
          const detail =
            err.response?.data?.error?.message ||
            err.response?.data?.message ||
            err.response?.data?.detail ||
            err.message
          setSubmitError(typeof detail === 'string' ? detail : 'Failed to place TP/SL')
        },
      }
    )
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="w-80 p-0 gap-0">
        <DialogHeader className="flex flex-row items-center justify-between px-4 py-3 border-b border-slate-700/50 space-y-0">
          <DialogTitle className="text-sm font-semibold text-gray-100">Take Profit / Stop Loss</DialogTitle>
        </DialogHeader>

        {/* Direction indicator (read-only, matches position) */}
        <div className="flex mx-4 mt-3 rounded-lg overflow-hidden text-xs font-semibold">
          <div className={`flex-1 py-2 text-center rounded-l-lg ${isLong ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
            Buy / Long
          </div>
          <div className={`flex-1 py-2 text-center rounded-r-lg ${!isLong ? 'bg-red-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
            Sell / Short
          </div>
        </div>

        <div className="flex flex-col px-4 pt-3 pb-1">
          <div className="text-[10px] text-slate-400 mb-2 tabular-nums">
            Mark: {fmtPriceForSymbol(markPrice, position.symbol)} · Entry: {fmtPriceForSymbol(entryPrice, position.symbol)} · Qty: {fmtQtyForSymbol(quantity, position.symbol)} {position.symbol.replace('USDT', '')}
          </div>

          {/* Take Profit section */}
          <div className="flex flex-col gap-2 py-3 border-b border-slate-700/50">
            <label
              className="flex items-center gap-2.5 cursor-pointer select-none"
              onClick={() => { setTpEnabled((v) => !v); setTpPrice('') }}
            >
              <div className={[
                'w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 transition-colors',
                tpEnabled ? 'bg-emerald-400 border-emerald-400' : 'border-slate-600 bg-transparent',
              ].join(' ')}>
                {tpEnabled && <span className="text-white text-[9px] font-bold leading-none">✓</span>}
              </div>
              <span className="text-sm text-gray-200 font-medium">Take Profit</span>
            </label>

            {tpEnabled && (
              <>
                <input
                  type="number"
                  value={tpPrice}
                  onChange={(e) => setTpPrice(e.target.value)}
                  placeholder="Trigger Price"
                  autoFocus
                  disabled={isPending}
                  className={[
                    'w-full bg-[#0a0d13] border rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-slate-600',
                    'focus:outline-none tabular-nums transition-colors disabled:opacity-50',
                    tpError ? 'border-red-500 focus:border-red-500' : 'border-slate-700/50 focus:border-emerald-400',
                  ].join(' ')}
                />
                {tpError && <span className="text-[11px] text-red-400">{tpError}</span>}
                {!tpError && tpPrice && (
                  <span className="text-[10px] text-slate-400">
                    When Mark Price reaches <span className="text-gray-300 tabular-nums">{fmtPrice(tpPrice)} USDT</span>, a Market order will be triggered to close the position.
                  </span>
                )}
              </>
            )}
          </div>

          {/* Stop Loss section */}
          <div className="flex flex-col gap-2 py-3">
            <label
              className="flex items-center gap-2.5 cursor-pointer select-none"
              onClick={() => { setSlEnabled((v) => !v); setSlPrice('') }}
            >
              <div className={[
                'w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 transition-colors',
                slEnabled ? 'bg-emerald-400 border-emerald-400' : 'border-slate-600 bg-transparent',
              ].join(' ')}>
                {slEnabled && <span className="text-white text-[9px] font-bold leading-none">✓</span>}
              </div>
              <span className="text-sm text-gray-200 font-medium">Stop Loss</span>
            </label>

            {slEnabled && (
              <>
                <input
                  type="number"
                  value={slPrice}
                  onChange={(e) => setSlPrice(e.target.value)}
                  placeholder="Trigger Price"
                  disabled={isPending}
                  className={[
                    'w-full bg-[#0a0d13] border rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-slate-600',
                    'focus:outline-none tabular-nums transition-colors disabled:opacity-50',
                    slError ? 'border-red-500 focus:border-red-500' : 'border-slate-700/50 focus:border-emerald-400',
                  ].join(' ')}
                />
                {slError && <span className="text-[11px] text-red-400">{slError}</span>}
                {!slError && slPrice && (
                  <span className="text-[10px] text-slate-400">
                    When Mark Price reaches <span className="text-gray-300 tabular-nums">{fmtPrice(slPrice)} USDT</span>, a Market order will be triggered to close the position.
                  </span>
                )}
              </>
            )}
          </div>

          {submitError && (
            <div className="mb-2 text-[11px] text-red-400 bg-red-950/20 border border-red-800/30 rounded-lg px-3 py-2">
              {submitError}
            </div>
          )}
        </div>

        {/* Confirm button */}
        <div className="px-4 pb-4">
          <button
            onClick={handleConfirm}
            disabled={!canConfirm}
            className={[
              'w-full py-3 rounded-lg text-sm font-semibold transition-colors',
              canConfirm
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white cursor-pointer'
                : 'bg-slate-800 text-slate-600 cursor-not-allowed',
            ].join(' ')}
          >
            {isPending ? 'Confirming…' : 'Confirm'}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
