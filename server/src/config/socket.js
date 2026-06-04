const { Server } = require('socket.io')

let io

function initSocket(httpServer) {
  io = new Server(httpServer, {
    cors: {
      origin: process.env.CLIENT_URL || 'http://localhost:5173',
      methods: ['GET', 'POST'],
    },
  })

  io.on('connection', (socket) => {
    console.log('[Socket.IO] client connected:', socket.id)

    const trackedRooms = new Set()

    socket.on('join', (room) => {
      socket.join(room)
      console.log(`[Socket.IO] ${socket.id} joined room: ${room}`)

      if (room.startsWith('backtest:')) {
        trackedRooms.add(room)
        const jobId = room.replace('backtest:', '')
        const { subscribeToJob } = require('../services/socketEmitter')
        subscribeToJob(jobId, 'backtest')
      }
    })

    socket.on('leave', (room) => {
      socket.leave(room)
      trackedRooms.delete(room)
      console.log(`[Socket.IO] ${socket.id} left room: ${room}`)

      if (room.startsWith('backtest:')) {
        const remaining = io.sockets.adapter.rooms.get(room)?.size || 0
        if (remaining === 0) {
          const jobId = room.replace('backtest:', '')
          const { unsubscribeFromJob } = require('../services/socketEmitter')
          unsubscribeFromJob(jobId)
        }
      }
    })

    socket.on('disconnect', () => {
      console.log('[Socket.IO] client disconnected:', socket.id)

      for (const room of trackedRooms) {
        if (room.startsWith('backtest:')) {
          const remaining = io.sockets.adapter.rooms.get(room)?.size || 0
          if (remaining === 0) {
            const jobId = room.replace('backtest:', '')
            const { unsubscribeFromJob } = require('../services/socketEmitter')
            unsubscribeFromJob(jobId)
          }
        }
      }
      trackedRooms.clear()
    })
  })

  return io
}

function getIO() {
  if (!io) throw new Error('Socket.IO not initialized')
  return io
}

module.exports = { initSocket, getIO }
