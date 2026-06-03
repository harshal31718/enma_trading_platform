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

    socket.on('join', (room) => {
      socket.join(room)
      console.log(`[Socket.IO] ${socket.id} joined room: ${room}`)
    })

    socket.on('disconnect', () => {
      console.log('[Socket.IO] client disconnected:', socket.id)
    })
  })

  return io
}

function getIO() {
  if (!io) throw new Error('Socket.IO not initialized')
  return io
}

module.exports = { initSocket, getIO }
