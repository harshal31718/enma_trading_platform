const Redis = require('ioredis')
const { getIO } = require('../config/socket')

// Separate connection for subscriptions — cannot share the BullMQ connection
const subscriber = new Redis(process.env.REDIS_URL || 'redis://redis:6379')

subscriber.on('error', (err) => console.error('[socketEmitter] redis error:', err))

const jobTypes = new Map() // jobId -> type ('candles' | 'backtest')

function subscribeToJob(jobId, type = 'candles') {
  jobTypes.set(jobId, type)
  const channel = `progress:${jobId}`
  subscriber.subscribe(channel, (err) => {
    if (err) console.error('[socketEmitter] subscribe error:', err)
    else console.log(`[socketEmitter] subscribed to ${channel} (${type})`)
  })
}

subscriber.on('message', (channel, message) => {
  const jobId = channel.replace('progress:', '')
  const type = jobTypes.get(jobId)
  if (!type) return
  try {
    const io = getIO()
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

function unsubscribeFromJob(jobId) {
  const channel = `progress:${jobId}`
  subscriber.unsubscribe(channel, (err) => {
    if (err) console.error('[socketEmitter] unsubscribe error:', err)
    else console.log(`[socketEmitter] unsubscribed from ${channel}`)
  })
  jobTypes.delete(jobId)
}

module.exports = { subscribeToJob, unsubscribeFromJob }
