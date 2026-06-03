import { createContext, useContext } from 'react'
import { useParams } from 'react-router-dom'

const SymbolContext = createContext(null)

export function SymbolProvider({ children }) {
  const { symbol: rawSymbol } = useParams()
  const symbol = rawSymbol ?? 'BTC-USDT'
  const binanceSymbol = symbol.replace('-', '')
  const streamPrefix = binanceSymbol.toLowerCase()
  const [base, quote] = symbol.split('-')

  return (
    <SymbolContext.Provider value={{ symbol, binanceSymbol, streamPrefix, base, quote }}>
      {children}
    </SymbolContext.Provider>
  )
}

export function useCurrentSymbol() {
  const ctx = useContext(SymbolContext)
  if (!ctx) throw new Error('useCurrentSymbol must be used within SymbolProvider')
  return ctx
}
