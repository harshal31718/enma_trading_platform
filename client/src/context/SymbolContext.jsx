import { createContext, useContext, useMemo } from 'react'
import { useParams } from 'react-router-dom'

const KNOWN_QUOTES = ['USDT', 'USDC', 'BUSD', 'BTC', 'ETH', 'BNB']

function parseBaseQuote(symbol) {
  for (const quote of KNOWN_QUOTES) {
    if (symbol.endsWith(quote) && symbol.length > quote.length) {
      return [symbol.slice(0, -quote.length), quote]
    }
  }
  return [symbol, '']
}

const SymbolContext = createContext(null)

export function SymbolProvider({ children }) {
  const { symbol: rawSymbol } = useParams()
  const symbol = rawSymbol ?? 'BTCUSDT'

  const value = useMemo(() => {
    const [base, quote] = parseBaseQuote(symbol)
    const streamPrefix = symbol.toLowerCase()
    return { symbol, binanceSymbol: symbol, streamPrefix, base, quote }
  }, [symbol])

  return (
    <SymbolContext.Provider value={value}>
      {children}
    </SymbolContext.Provider>
  )
}

export function useCurrentSymbol() {
  const ctx = useContext(SymbolContext)
  if (!ctx) throw new Error('useCurrentSymbol must be used within SymbolProvider')
  return ctx
}
