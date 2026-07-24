const os = require('os')
const Redis = require('ioredis')
const { getIO } = require('../config/socket')
const { processEngineStatsUpdate } = require('./algoSessionService')

// Plan 6 Step 6.5 (ENG-16) — durable, ordered, at-least-once consumer for
// the engine's `algo:events` Redis Stream (`core/node_notifier.py`'s
// `NodeNotifier.notify()`), replacing the old fire-and-forget HTTP PATCH
// that silently dropped events on any Node downtime. Applies every entry
// through the exact same `processEngineStatsUpdate()` the old
// `PATCH /internal/algo/sessions/:id/stats` route used — correctness
// against duplicate/out-of-order delivery relies on that function's
// existing `lastSeqBySymbol` staleness guard, unchanged here.
const STREAM_KEY = 'algo:events'
const GROUP_NAME = 'node-consumers'
// Hostname (== container ID under Docker), NOT process.pid — this dev
// environment's nodemon restarts the Node process on every file-watch
// event while the container itself stays up. A pid-based name meant every
// nodemon restart abandoned its predecessor's pending (unacked) entries
// under a name no future process would ever read again — found live via
// XPENDING showing entries stuck under dead `consumer-<old-pid>` names.
// Hostname is stable across those restarts, so this consumer reclaims its
// own prior incarnation's pending entries via XAUTOCLAIM below.
const CONSUMER_NAME = `consumer-${os.hostname()}`
const BLOCK_MS = 5000
const BATCH_SIZE = 20
const CLAIM_MIN_IDLE_MS = 30_000 // reclaim entries idle at least this long, regardless of which consumer name holds them

// Separate connection — XREADGROUP with BLOCK occupies the connection until
// data arrives or the block times out, so it cannot share the BullMQ/
// pub-sub clients (same rule socketEmitter.js documents for its own
// subscriber connection).
const consumerClient = new Redis(process.env.REDIS_URL || 'redis://redis:6379', {
  maxRetriesPerRequest: null,
})

consumerClient.on('error', (err) => console.error('[eventStreamConsumer] redis error:', err.message))

let running = false

async function ensureGroup() {
  try {
    await consumerClient.xgroup('CREATE', STREAM_KEY, GROUP_NAME, '0', 'MKSTREAM')
    console.log(`[eventStreamConsumer] created consumer group ${GROUP_NAME} on ${STREAM_KEY}`)
  } catch (err) {
    if (!String(err.message).includes('BUSYGROUP')) throw err
  }
}

async function applyEntry(id, fields) {
  // ioredis returns stream fields as a flat [key, value, key, value, ...] array.
  const obj = {}
  for (let i = 0; i < fields.length; i += 2) obj[fields[i]] = fields[i + 1]
  const { sessionId, payload } = obj
  if (!sessionId || !payload) {
    console.warn(`[eventStreamConsumer] malformed entry ${id} (missing sessionId/payload), acking to skip`)
    return
  }
  let body
  try {
    body = JSON.parse(payload)
  } catch (err) {
    console.warn(`[eventStreamConsumer] unparseable payload for entry ${id}, acking to skip:`, err.message)
    return
  }
  await processEngineStatsUpdate({ id: sessionId, body, io: getIO() })
}

async function processBatch(entries, client = consumerClient) {
  for (const [id, fields] of entries) {
    try {
      await applyEntry(id, fields)
    } catch (err) {
      // Apply failed for a reason other than malformed input (e.g. a
      // transient Mongo hiccup) — do NOT ack, so this entry stays in the
      // consumer group's pending list and is redelivered on the next
      // drainPending() (a fresh loop iteration or the next process start).
      console.error(`[eventStreamConsumer] apply failed for entry ${id}, will retry:`, err.message)
      continue
    }
    await client.xack(STREAM_KEY, GROUP_NAME, id)
  }
}

async function claimStalePending(client = consumerClient) {
  // XAUTOCLAIM reassigns any entry idle >= CLAIM_MIN_IDLE_MS to this
  // consumer, REGARDLESS of which consumer name (dead or alive) currently
  // holds it — unlike XREADGROUP '0' (which only ever sees entries already
  // assigned to the exact consumer name asking), this recovers entries
  // from a genuinely dead prior process, not just this process's own crash
  // history. Reply shape: [nextCursor, claimedEntries, deletedIds].
  let cursor = '0'
  let totalClaimed = 0
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const res = await client.xautoclaim(
      STREAM_KEY, GROUP_NAME, CONSUMER_NAME, CLAIM_MIN_IDLE_MS, cursor, 'COUNT', BATCH_SIZE
    )
    const [nextCursor, entries] = res
    if (entries.length) {
      totalClaimed += entries.length
      await processBatch(entries, client)
    }
    cursor = nextCursor
    if (cursor === '0' || !entries.length) break
  }
  if (totalClaimed) {
    console.log(`[eventStreamConsumer] claimed and processed ${totalClaimed} stale-pending entries (possibly from a dead prior consumer)`)
  }
}

async function loop() {
  while (running) {
    let res
    try {
      res = await consumerClient.xreadgroup(
        'GROUP', GROUP_NAME, CONSUMER_NAME, 'BLOCK', BLOCK_MS, 'COUNT', BATCH_SIZE,
        'STREAMS', STREAM_KEY, '>'
      )
    } catch (err) {
      console.error('[eventStreamConsumer] xreadgroup error:', err.message)
      await new Promise((resolve) => setTimeout(resolve, 1000))
      continue
    }
    if (!res) continue // BLOCK timeout elapsed, no new entries
    const [[, entries]] = res
    await processBatch(entries)
  }
}

async function start() {
  if (running) return
  running = true
  await ensureGroup()
  await claimStalePending()
  loop().catch((err) => {
    console.error('[eventStreamConsumer] loop crashed:', err)
    running = false
  })
  console.log(`[eventStreamConsumer] started as ${CONSUMER_NAME}`)
}

async function stop() {
  running = false
  await consumerClient.quit()
}

module.exports = {
  start,
  stop,
  _internal: { applyEntry, processBatch, claimStalePending, ensureGroup, STREAM_KEY, GROUP_NAME, CONSUMER_NAME },
}
