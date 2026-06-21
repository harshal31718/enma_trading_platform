import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import queryClient from '@/lib/queryClient'
import Navbar from '@/components/layout/Navbar'
import Dashboard from '@/pages/Dashboard'
import Backtest from '@/pages/Backtest'
import Strategies from '@/pages/Strategies'
import Settings from '@/pages/Settings'
import Trade from '@/pages/Trade'
import AlgoTrading from '@/pages/AlgoTrading'
import OrderHistory from '@/pages/OrderHistory'

export default function App() {
  return (
    <div className="dark">
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Navbar />
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/trade" element={<Navigate to="/trade/BTCUSDT" replace />} />
            <Route path="/trade/:symbol" element={<Trade />} />
            <Route path="/algo" element={<AlgoTrading />} />
            <Route path="/order-history" element={<OrderHistory />} />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </div>
  )
}
