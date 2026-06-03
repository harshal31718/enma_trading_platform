const Redis = require('ioredis')

const redis = new Redis(process.env.REDIS_URL || 'redis://redis:6379', {
  maxRetriesPerRequest: null,
})

redis.on('error', (err) => console.error('[Redis] error:', err))
redis.on('connect', () => console.log('[Redis] connected'))

module.exports = redis
