const Redis = require('ioredis')
const { getIO } = require('../config/socket')

// Separate connection for subscriptions — cannot share the BullMQ connection
const subscriber = new Redis(process.env.REDIS_URL || 'redis://redis:6379')

subscriber.on('error', (err) => console.error('[socketEmitter] redis error:', err))

const jobTypes = new Map() // jobId -> type ('candles' | 'backtest')
const tradeStreamUsers = new Set() // userIds currently subscribed to trade-stream:{userId}

function subscribeToJob(jobId, type = 'candles') {
  jobTypes.set(jobId, type)
  const channel = `progress:${jobId}`
  subscriber.subscribe(channel, (err) => {
    if (err) console.error('[socketEmitter] subscribe error:', err)
    else console.log(`[socketEmitter] subscribed to ${channel} (${type})`)
  })
}

function unsubscribeFromJob(jobId) {
  const channel = `progress:${jobId}`
  subscriber.unsubscribe(channel, (err) => {
    if (err) console.error('[socketEmitter] unsubscribe error:', err)
    else console.log(`[socketEmitter] unsubscribed from ${channel}`)
  })
  jobTypes.delete(jobId)
}

// Relays engine/services/manual_trade_stream.py's per-user Binance User Data
// Stream events (real-time order/account push) to the client, so the Trade
// page can stop REST-polling account/positions/open-orders at high
// frequency — see workspace/docs/features/live-trading/SPEC.md.
function subscribeToTradeStream(userId) {
  if (tradeStreamUsers.has(userId)) return // already subscribed
  tradeStreamUsers.add(userId)
  const channel = `trade-stream:${userId}`
  subscriber.subscribe(channel, (err) => {
    if (err) console.error('[socketEmitter] trade-stream subscribe error:', err)
    else console.log(`[socketEmitter] subscribed to ${channel}`)
  })
}

function unsubscribeFromTradeStream(userId) {
  if (!tradeStreamUsers.has(userId)) return
  tradeStreamUsers.delete(userId)
  const channel = `trade-stream:${userId}`
  subscriber.unsubscribe(channel, (err) => {
    if (err) console.error('[socketEmitter] trade-stream unsubscribe error:', err)
    else console.log(`[socketEmitter] unsubscribed from ${channel}`)
  })
}

subscriber.on('message', (channel, message) => {
  try {
    const io = getIO()

    if (channel.startsWith('trade-stream:')) {
      const userId = channel.replace('trade-stream:', '')
      const parsed = JSON.parse(message)
      io.to(`user:${userId}`).emit('trade:stream-update', parsed)
      return
    }

    const jobId = channel.replace('progress:', '')
    const type = jobTypes.get(jobId)
    if (!type) return
    const parsed = JSON.parse(message)
    if (type === 'backtest') {
      io.to(`backtest:${jobId}`).emit('backtest:progress', {
        jobId,
        ...parsed,
      })
    }
  } catch (err) {
    console.error('[socketEmitter] emit error:', err.message)
  }
})

module.exports = {
  subscribeToJob,
  unsubscribeFromJob,
  subscribeToTradeStream,
  unsubscribeFromTradeStream,
}
