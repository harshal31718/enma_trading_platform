const { Server } = require('socket.io')
const jwt = require('jsonwebtoken')
const User = require('../models/User')

let io

function parseCookies(cookieHeader = '') {
  const cookies = {}
  cookieHeader.split(';').forEach(pair => {
    const [key, ...rest] = pair.trim().split('=')
    if (key) cookies[decodeURIComponent(key.trim())] = decodeURIComponent(rest.join('=').trim())
  })
  return cookies
}

function initSocket(httpServer) {
  io = new Server(httpServer, {
    cors: {
      origin: process.env.CLIENT_URL || 'http://localhost:5173',
      methods: ['GET', 'POST'],
      credentials: true,
    },
  })

  io.use(async (socket, next) => {
    try {
      const cookies = parseCookies(socket.handshake.headers.cookie)
      const token = cookies.enma_jwt
      if (!token) return next(new Error('UNAUTHORIZED'))

      const decoded = jwt.verify(token, process.env.JWT_SECRET)
      const user = await User.findById(decoded.userId).lean()
      if (!user?.isActive) return next(new Error('UNAUTHORIZED'))

      socket.user = user
      next()
    } catch {
      next(new Error('UNAUTHORIZED'))
    }
  })

  io.on('connection', (socket) => {
    console.log('[Socket.IO] client connected:', socket.id)
    socket.join(`user:${socket.user._id}`)

    const trackedRooms = new Set()

    socket.on('join', (room) => {
      socket.join(room)
      console.log(`[Socket.IO] ${socket.id} joined room: ${room}`)

      // Plan 10 Phase 1: simulation.worker.js already self-subscribes/unsubscribes
      // around its engine call regardless of client room membership, so this
      // client-triggered path is a no-op today (no UI joins a simulation: room
      // yet) — kept for parity so Phase 2's UI gets the same double-subscribe/
      // auto-cleanup semantics backtest: rooms get, without a second wiring pass.
      if (room.startsWith('backtest:') || room.startsWith('simulation:') || room.startsWith('optimization:')) {
        trackedRooms.add(room)
        const [prefix, jobId] = room.split(':')
        const { subscribeToJob } = require('../services/socketEmitter')
        subscribeToJob(jobId, prefix)
      }
    })

    socket.on('leave', (room) => {
      socket.leave(room)
      trackedRooms.delete(room)
      console.log(`[Socket.IO] ${socket.id} left room: ${room}`)

      if (room.startsWith('backtest:') || room.startsWith('simulation:') || room.startsWith('optimization:')) {
        const remaining = io.sockets.adapter.rooms.get(room)?.size || 0
        if (remaining === 0) {
          const [, jobId] = room.split(':')
          const { unsubscribeFromJob } = require('../services/socketEmitter')
          unsubscribeFromJob(jobId)
        }
      }
    })

    socket.on('disconnect', () => {
      console.log('[Socket.IO] client disconnected:', socket.id)

      for (const room of trackedRooms) {
        if (room.startsWith('backtest:') || room.startsWith('simulation:') || room.startsWith('optimization:')) {
          const remaining = io.sockets.adapter.rooms.get(room)?.size || 0
          if (remaining === 0) {
            const [, jobId] = room.split(':')
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
