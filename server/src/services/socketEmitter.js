const Redis = require('ioredis')
const { getIO } = require('../config/socket')

// Separate connection for subscriptions — cannot share the BullMQ connection
const subscriber = new Redis(process.env.REDIS_URL || 'redis://redis:6379')

subscriber.on('error', (err) => console.error('[socketEmitter] redis error:', err))

function subscribeToJob(jobId) {
  const channel = `progress:${jobId}`
  subscriber.subscribe(channel, (err) => {
    if (err) console.error('[socketEmitter] subscribe error:', err)
    else console.log(`[socketEmitter] subscribed to ${channel}`)
  })
}

subscriber.on('message', (channel, message) => {
  const jobId = channel.replace('progress:', '')
  try {
    const io = getIO()
    io.to(`candles:${jobId}`).emit('candles:progress', {
      jobId,
      ...JSON.parse(message),
    })
  } catch (err) {
    console.error('[socketEmitter] emit error:', err.message)
  }
})

module.exports = { subscribeToJob }
