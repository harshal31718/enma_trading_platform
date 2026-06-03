import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useSymbols, useImportCandles } from '@/hooks/useCandles'
import { Skeleton } from '@/components/ui/skeleton'

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w']
const EXCHANGES = ['Binance Futures', 'Binance Spot']

export default function ImportForm({ onJobStarted }) {
  const [exchange, setExchange] = useState('Binance Futures')
  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState('1h')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  const { data: symbols, isLoading: symbolsLoading } = useSymbols()
  const { mutate: importCandles, isPending } = useImportCandles()

  const symbolList = exchange === 'Binance Futures'
    ? (symbols?.futures ?? [])
    : (symbols?.spot ?? [])

  function handleSubmit(e) {
    e.preventDefault()
    importCandles(
      { exchange, symbol, timeframe, startDate, endDate },
      { onSuccess: (data) => onJobStarted(data.jobId) }
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-gray-900 border border-gray-800 rounded-lg p-6"
    >
      <h2 className="text-gray-100 font-medium mb-4">Import Candles</h2>

      <div className="space-y-4">
        <div>
          <label className="block text-gray-400 text-sm mb-1">Exchange</label>
          <select
            value={exchange}
            onChange={(e) => { setExchange(e.target.value); setSymbol('') }}
            disabled={isPending}
            className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-gray-100 text-sm focus:outline-none focus:border-emerald-500"
          >
            {EXCHANGES.map((ex) => (
              <option key={ex} value={ex}>{ex}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-gray-400 text-sm mb-1">Symbol</label>
          {symbolsLoading ? (
            <Skeleton className="h-9 w-full" />
          ) : (
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              disabled={isPending}
              required
              className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-gray-100 text-sm focus:outline-none focus:border-emerald-500"
            >
              <option value="">Select symbol…</option>
              {symbolList.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          )}
        </div>

        <div>
          <label className="block text-gray-400 text-sm mb-1">Timeframe</label>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            disabled={isPending}
            className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-gray-100 text-sm focus:outline-none focus:border-emerald-500"
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-gray-400 text-sm mb-1">Start Date</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            disabled={isPending}
            required
            className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-gray-100 text-sm focus:outline-none focus:border-emerald-500"
          />
        </div>

        <div>
          <label className="block text-gray-400 text-sm mb-1">End Date</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            disabled={isPending}
            required
            className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-gray-100 text-sm focus:outline-none focus:border-emerald-500"
          />
        </div>

        <button
          type="submit"
          disabled={isPending || !symbol || !startDate || !endDate}
          className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
        >
          {isPending && <Loader2 size={16} className="animate-spin" />}
          {isPending ? 'Importing…' : 'Import Candles'}
        </button>
      </div>
    </form>
  )
}
