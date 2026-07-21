// Plan 8 Step 8.7 (SEC-8): extracted so /api/v1/health's connection-reuse
// behavior is testable without requiring the entire app.js (which
// transitively opens its own real Redis connections via socketEmitter.js/
// BullMQ queue definitions — unrelated machinery for a health check).

async function checkMongoHealth(mongooseConnection) {
  try {
    if (mongooseConnection.readyState !== 1) return 'disconnected'
    await mongooseConnection.db.admin().command({ ping: 1 })
    return 'connected'
  } catch {
    return 'error'
  }
}

// The shared redis singleton (config/redis.js) is created with
// maxRetriesPerRequest: null (BullMQ's own requirement), so a queued command
// waits indefinitely for reconnection instead of rejecting — bound the wait
// here so an unreachable Redis reports "error" quickly instead of hanging
// the health check.
async function checkRedisHealth(redisClient, timeoutMs = 2000) {
  try {
    await Promise.race([
      redisClient.ping(),
      new Promise((_, reject) => setTimeout(() => reject(new Error('redis ping timeout')), timeoutMs)),
    ])
    return 'connected'
  } catch {
    return 'error'
  }
}

module.exports = { checkMongoHealth, checkRedisHealth }
