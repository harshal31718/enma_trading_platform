import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
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
import StrategyLab from '@/pages/StrategyLab'
import AdminPanel from '@/pages/AdminPanel'
import NotFound from '@/pages/NotFound'

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
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            style: {
              background: '#0d1117',
              color: '#cbd5e1',
              border: '1px solid rgba(51, 65, 85, 0.5)',
              fontFamily: 'monospace',
              fontSize: '12px',
            },
            success: {
              iconTheme: {
                primary: '#34d399',
                secondary: '#0d1117',
              },
            },
            error: {
              iconTheme: {
                primary: '#f87171',
                secondary: '#0d1117',
              },
            },
          }}
        />
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
              <Route path="/lab" element={<StrategyLab />} />
              <Route path="/admin" element={<AdminPanel />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </div>
  )
}
