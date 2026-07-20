// Plan 7 Step 7.4 (CLI-1): extracted out of Trade.jsx.
import { useEffect, useRef, useState } from 'react'
import {
  useTradePositions,
  useTradeOpenOrders,
  useTradeAccount,
  useTradeOrders,
  useTradeExecutions,
  useTradeTransactions,
} from '@/hooks/useTrade'
import { useCurrentSymbol } from '@/context/SymbolContext'
import PositionsTable from './PositionsTable'
import OpenOrdersTable from './OpenOrdersTable'
import AssetsTable from './AssetsTable'
import { OrderHistoryTable, TradeHistoryTable, TransactionHistoryTable } from './HistoryTables'

export default function BottomPanel({ ocoToast, ocoBanner, onDismissBanner }) {
  const [activeTab, setActiveTab] = useState('Positions')

  const { symbol } = useCurrentSymbol()
  const { data: positions, isLoading: posLoading, isFetching: posFetching } = useTradePositions()
  const { data: openOrders, isLoading: ordLoading, isFetching: ordFetching } = useTradeOpenOrders()
  const { data: account, isLoading: accLoading, isFetching: accFetching } = useTradeAccount()
  const { data: ordersRaw, isLoading: ordHistoryLoading, isFetching: ordHistoryFetching } = useTradeOrders(symbol, {
    enabled: activeTab === 'Order History' && !!symbol,
    refetchInterval: 8000,
  })
  const { data: execRaw, isLoading: execLoading, isFetching: execFetching } = useTradeExecutions(symbol, {
    enabled: activeTab === 'Trade History' && !!symbol,
    refetchInterval: 8000,
  })
  const { data: txRaw, isLoading: txLoading, isFetching: txFetching } = useTradeTransactions(symbol, {
    enabled: activeTab === 'Transaction History',
    refetchInterval: 8000,
  })

  const ordersHistory = ordersRaw?.orders ?? ordersRaw
  const ordersSynced  = ordersRaw?.synced ?? true
  const executions    = execRaw?.executions ?? execRaw
  const execSynced    = execRaw?.synced ?? true
  const transactions  = txRaw?.transactions ?? txRaw
  const txSynced      = txRaw?.synced ?? true

  const [localBanner, setLocalBanner] = useState(null)
  const bannerTimerRef = useRef(null)

  const posCount = positions?.length ?? 0
  const ordCount = openOrders?.length ?? 0

  const activeBanner = ocoBanner || localBanner

  function handleOcoBannerEvent(msg) {
    clearTimeout(bannerTimerRef.current)
    setLocalBanner(msg)
    bannerTimerRef.current = setTimeout(() => setLocalBanner(null), 8000)
  }

  useEffect(() => {
    return () => clearTimeout(bannerTimerRef.current)
  }, [])

  return (
    <div className="bg-title-bg border-t border-slate-700/50 flex flex-col shrink-0 h-[200px]">
      <div className="flex border-b border-slate-700/50 shrink-0 title-fade bg-title-bg">
        {[
          { key: 'Positions', label: `Positions(${posCount})`, isRefreshing: posFetching },
          { key: 'Open Orders', label: `Open Orders(${ordCount})`, isRefreshing: ordFetching },
          { key: 'Order History', label: 'Order History', isRefreshing: ordHistoryFetching },
          { key: 'Trade History', label: 'Trade History', isRefreshing: execFetching },
          { key: 'Transaction History', label: 'Transaction History', isRefreshing: txFetching },
          { key: 'Assets', label: 'Assets', isRefreshing: accFetching },
        ].map(({ key, label, isRefreshing }, i) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={[
              `${i === 0 ? 'pl-2 pr-4' : 'px-4'} py-2 text-xs font-medium transition-colors whitespace-nowrap flex items-center gap-1.5`,
              activeTab === key
                ? 'text-gray-100 border-b-2 border-emerald-400 -mb-px'
                : 'text-slate-400 opacity-50 hover:opacity-100 hover:text-gray-300',
            ].join(' ')}
          >
            <span>{label}</span>
            {isRefreshing && (
              <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-ping shrink-0" />
            )}
          </button>
        ))}
      </div>

      {/* Persistent OCO event banner */}
      {activeBanner && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-yellow-400/10 border-b border-yellow-600/30 shrink-0">
          <span className="text-[11px] text-yellow-400">{activeBanner}</span>
          <button
            onClick={() => { clearTimeout(bannerTimerRef.current); setLocalBanner(null); onDismissBanner?.() }}
            className="text-yellow-600 hover:text-yellow-400 text-xs leading-none ml-2"
          >
            ✕
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto min-h-0">
        {activeTab === 'Positions' && (
          <PositionsTable data={positions} isLoading={posLoading} account={account} />
        )}
        {activeTab === 'Open Orders' && (
          <OpenOrdersTable
            data={openOrders}
            isLoading={ordLoading}
            onOcoBannerEvent={handleOcoBannerEvent}
          />
        )}
        {activeTab === 'Order History' && (
          <OrderHistoryTable data={ordersHistory} isLoading={ordHistoryLoading} synced={ordersSynced} />
        )}
        {activeTab === 'Trade History' && (
          <TradeHistoryTable data={executions} isLoading={execLoading} synced={execSynced} />
        )}
        {activeTab === 'Transaction History' && (
          <TransactionHistoryTable data={transactions} isLoading={txLoading} synced={txSynced} />
        )}
        {activeTab === 'Assets' && (
          <AssetsTable data={account} isLoading={accLoading} />
        )}
      </div>
    </div>
  )
}
