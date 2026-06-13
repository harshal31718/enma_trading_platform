import { useState, useEffect, useRef } from 'react'
import { Play, Square, Loader2, Calendar } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { useStrategies } from '../../hooks/useStrategies'
import { useSymbols } from '../../hooks/useCandles'
import { formatIsoDate } from '../../utils/formatters'
import { useExchangeSettings } from '../../hooks/useExchangeSettings'

// Date picker that shows "29 Aug '25" but stores/emits a YYYY-MM-DD ISO string
function DateInput({ value, onChange, label }) {
  const hiddenRef = useRef(null)
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-gray-400 text-xs font-medium">{label}</label>
      <button
        type="button"
        onClick={() => hiddenRef.current?.showPicker?.()}
        className="relative flex h-10 w-full items-center justify-between rounded border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 hover:border-gray-700 focus-visible:outline-none focus-visible:border-emerald-500 transition-colors"
      >
        <span>{formatIsoDate(value)}</span>
        <Calendar className="size-4 text-gray-500 shrink-0" />
        <input
          ref={hiddenRef}
          type="date"
          value={value}
          onChange={onChange}
          className="absolute inset-0 opacity-0 cursor-pointer w-full"
          tabIndex={-1}
        />
      </button>
    </div>
  )
}

export default function BacktestConfigForm({ isRunning, onSubmit, onCancel }) {
  const { data: strategies, isLoading: loadingStrategies } = useStrategies()
  const { data: symbolData, isLoading: loadingSymbols } = useSymbols()

  const [strategyId, setStrategyId] = useState('')
  const [exchange, setExchange] = useState('Binance Futures')
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [timeframe, setTimeframe] = useState('1h')
  const [startDate, setStartDate] = useState('2023-01-01')
  const [endDate, setEndDate] = useState('2024-01-01')
  const [capital, setCapital] = useState('10000')
  const [leverage, setLeverage] = useState('1')
  const [feeRate, setFeeRate] = useState('0.001')

  // Pre-fill from saved exchange settings (fires once)
  const { data: exchangeSettings } = useExchangeSettings()
  const settingsApplied = useRef(false)
  useEffect(() => {
    if (exchangeSettings && !settingsApplied.current) {
      setCapital(String(exchangeSettings.defaultCapital ?? 10000))
      setLeverage(String(exchangeSettings.defaultLeverage ?? 1))
      setFeeRate(String(exchangeSettings.takerFee ?? 0.001))
      settingsApplied.current = true
    }
  }, [exchangeSettings])

  useEffect(() => {
    if (strategies?.length > 0 && !strategyId) setStrategyId(strategies[0].id)
  }, [strategies, strategyId])

  useEffect(() => {
    if (symbolData?.futures?.length > 0 && !symbol) setSymbol(symbolData.futures[0])
  }, [symbolData, symbol])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!strategyId || !symbol) return
    if (new Date(endDate) <= new Date(startDate)) return
    onSubmit({
      strategyId,
      exchange,
      symbol,
      timeframe,
      startDate,
      endDate,
      capital: parseFloat(capital),
      leverage: parseInt(leverage, 10),
      feeRate: parseFloat(feeRate),
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Configuration</CardTitle>
        <CardDescription>Set parameters for simulation</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Strategy */}
          <div className="flex flex-col gap-1.5">
            <label className="text-gray-400 text-xs font-medium">Strategy</label>
            {loadingStrategies ? (
              <div className="h-10 bg-gray-950 border border-gray-800 rounded flex items-center px-3">
                <Loader2 className="size-4 animate-spin text-gray-600" />
              </div>
            ) : (
              <Select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
                {strategies?.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </Select>
            )}
          </div>

          {/* Exchange */}
          <div className="flex flex-col gap-1.5">
            <label className="text-gray-400 text-xs font-medium">Exchange</label>
            <Select value={exchange} onChange={(e) => setExchange(e.target.value)}>
              <option value="Binance Futures">Binance Futures</option>
              <option value="Binance Spot">Binance Spot</option>
            </Select>
          </div>

          {/* Symbol */}
          <div className="flex flex-col gap-1.5">
            <label className="text-gray-400 text-xs font-medium">Symbol</label>
            {loadingSymbols ? (
              <div className="h-10 bg-gray-950 border border-gray-800 rounded flex items-center px-3">
                <Loader2 className="size-4 animate-spin text-gray-600" />
              </div>
            ) : (
              <Select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
                {(exchange === 'Binance Futures' ? symbolData?.futures : symbolData?.spot)?.map((sym) => (
                  <option key={sym} value={sym}>{sym}</option>
                ))}
              </Select>
            )}
          </div>

          {/* Timeframe + Capital */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-gray-400 text-xs font-medium">Timeframe</label>
              <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                {['1m', '5m', '15m', '1h', '4h', '1d'].map((tf) => (
                  <option key={tf} value={tf}>{tf}</option>
                ))}
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-gray-400 text-xs font-medium">Starting Capital</label>
              <Input type="number" value={capital} onChange={(e) => setCapital(e.target.value)} />
            </div>
          </div>

          {/* Date range */}
          <div className="grid grid-cols-2 gap-4">
            <DateInput
              label="Start Date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
            <DateInput
              label="End Date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>
          {new Date(endDate) <= new Date(startDate) && (
            <p className="text-yellow-500 text-xs">End date must be after start date.</p>
          )}

          {/* Leverage + Fee Rate */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-gray-400 text-xs font-medium">Leverage</label>
              <Input type="number" value={leverage} onChange={(e) => setLeverage(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-gray-400 text-xs font-medium">Fee Rate</label>
              <Input type="number" step="0.0001" value={feeRate} onChange={(e) => setFeeRate(e.target.value)} />
            </div>
          </div>

          {isRunning ? (
            <Button
              type="button"
              variant="danger"
              className="w-full flex items-center justify-center gap-2 mt-2"
              onClick={onCancel}
            >
              <Square className="size-4" /> Cancel Backtest
            </Button>
          ) : (
            <Button
              type="submit"
              className="w-full flex items-center justify-center gap-2 mt-2"
              disabled={new Date(endDate) <= new Date(startDate)}
            >
              <Play className="size-4 fill-current" /> Run Backtest
            </Button>
          )}
        </form>
      </CardContent>
    </Card>
  )
}
