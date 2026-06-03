import { useState, useEffect, useCallback } from 'react'
import { CheckCircle, XCircle } from 'lucide-react'
import { useSocket } from '@/hooks/useSocket'
import socket from '@/lib/socket'

export default function ImportProgress({ jobId, onComplete }) {
  const [pct, setPct] = useState(0)
  const [message, setMessage] = useState('Starting import…')
  const [status, setStatus] = useState('running') // running | completed | error
  const [errorMsg, setErrorMsg] = useState('')
  const [candlesImported, setCandlesImported] = useState(0)

  useEffect(() => {
    socket.connect()
    socket.emit('join', `candles:${jobId}`)
    return () => {
      // leave room on unmount — socket.io auto-cleans on disconnect
    }
  }, [jobId])

  const handleProgress = useCallback((data) => {
    if (data.jobId !== jobId) return
    setPct(data.pct)
    setMessage(data.message)
  }, [jobId])

  const handleComplete = useCallback((data) => {
    if (data.jobId !== jobId) return
    setPct(100)
    setMessage('Import complete')
    setStatus('completed')
    setCandlesImported(data.candlesImported)
    onComplete()
  }, [jobId, onComplete])

  const handleError = useCallback((data) => {
    if (data.jobId !== jobId) return
    setStatus('error')
    setErrorMsg(data.error)
  }, [jobId])

  useSocket('candles:progress', handleProgress)
  useSocket('candles:complete', handleComplete)
  useSocket('candles:error', handleError)

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
      <h3 className="text-gray-100 font-medium mb-4">Import Progress</h3>

      {status === 'error' ? (
        <div className="flex items-start gap-2 text-red-400 text-sm">
          <XCircle size={16} className="mt-0.5 shrink-0" />
          <span>{errorMsg || 'Import failed'}</span>
        </div>
      ) : status === 'completed' ? (
        <div className="flex items-center gap-2 text-green-400 text-sm">
          <CheckCircle size={16} className="shrink-0" />
          <span>{candlesImported.toLocaleString()} candles imported</span>
        </div>
      ) : (
        <>
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>{message}</span>
            <span>{pct}%</span>
          </div>
          <div className="w-full bg-gray-800 rounded-full h-2">
            <div
              className="bg-emerald-500 h-2 rounded-full transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        </>
      )}
    </div>
  )
}
