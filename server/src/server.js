require('dotenv').config()
const http = require('http')
const mongoose = require('mongoose')
const app = require('./app')
const { initSocket } = require('./config/socket')

// Import worker to start it — side effect only
require('./workers/backtest.worker')

const PORT = process.env.PORT || 5000
const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongodb:27017/enma_trading'

mongoose
  .connect(MONGO_URI)
  .then(() => console.log('MongoDB connected'))
  .catch((err) => console.error('MongoDB connection error:', err))

const httpServer = http.createServer(app)

initSocket(httpServer)

httpServer.listen(PORT, '0.0.0.0', () => {
  console.log(`Server running on port ${PORT}`)
})
