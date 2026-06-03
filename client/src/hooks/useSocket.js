import { useEffect } from 'react'
import socket from '../lib/socket'

export function useSocket(event, handler) {
  useEffect(() => {
    socket.connect()
    socket.on(event, handler)
    return () => {
      socket.off(event, handler)
    }
  }, [event, handler])
}
