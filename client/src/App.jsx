import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import queryClient from '@/lib/queryClient'
import Navbar from '@/components/layout/Navbar'
import Dashboard from '@/pages/Dashboard'
import Backtest from '@/pages/Backtest'
import LiveTrading from '@/pages/LiveTrading'
import Strategies from '@/pages/Strategies'
import Settings from '@/pages/Settings'

export default function App() {
  return (
    <div className="dark">
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Navbar />
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/live" element={<LiveTrading />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </div>
  )
}
