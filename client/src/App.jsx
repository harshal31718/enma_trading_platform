import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import queryClient from '@/lib/queryClient'
import Navbar from '@/components/layout/Navbar'
import { useAuth } from '@/hooks/useAuth'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import Backtest from '@/pages/Backtest'
import Strategies from '@/pages/Strategies'
import Settings from '@/pages/Settings'
import Trade from '@/pages/Trade'
import AlgoTrading from '@/pages/AlgoTrading'
import OrderHistory from '@/pages/OrderHistory'
import RiskDashboard from '@/pages/RiskDashboard'
import AdminPanel from '@/pages/AdminPanel'

function ProtectedLayout() {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-[#0a0d13]">
        <div className="w-5 h-5 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return (
    <>
      <Navbar />
      <Outlet />
    </>
  )
}

export default function App() {
  return (
    <div className="dark">
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<ProtectedLayout />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/backtest" element={<Backtest />} />
              <Route path="/strategies" element={<Strategies />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/trade" element={<Navigate to="/trade/BTCUSDT" replace />} />
              <Route path="/trade/:symbol" element={<Trade />} />
              <Route path="/algo" element={<AlgoTrading />} />
              <Route path="/order-history" element={<OrderHistory />} />
              <Route path="/risk-dashboard" element={<RiskDashboard />} />
              <Route path="/admin" element={<AdminPanel />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </div>
  )
}
