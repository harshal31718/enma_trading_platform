// Plan 7 Step 7.1 (SRV-1) fourth slice: `trade.controller.js`'s
// `getTradeOrders`/`getTradeExecutions`/`getTradeTransactions` independently
// duplicated the same shape — best-effort engine sync (bulkWrite into the
// local Mongoose collection, degrading to `synced:false` rather than
// blocking on failure) followed by a read of the local collection, the
// server's own persisted cache. Pure extraction — same try/catch boundary,
// same bulkWrite op shape, same log-and-degrade-not-throw behavior on a
// failed engine fetch.
const engineClient = require('./engineClient')

/**
 * @param {object} params
 * @param {import('mongoose').Model} params.Model
 * @param {string} params.engineEndpoint
 * @param {object} params.headers
 * @param {object} params.query - extra query params sent to the engine (merged with limit:100)
 * @param {string} params.idField - field bulkWrite dedupes on (e.g. 'orderId', 'id', 'tranId')
 * @param {(item: object) => object} params.transform - per-item shape for the bulkWrite $set
 * @param {string} params.syncErrorLabel - text for the "Failed to sync X from engine" log line
 * @param {object} params.readFilter - the Mongoose filter for the local-collection read
 * @returns {Promise<{ items: object[], synced: boolean }>}
 */
async function syncAndListTradeHistory({ Model, engineEndpoint, headers, query, idField, transform, syncErrorLabel, readFilter }) {
  let synced = true
  try {
    const { data } = await engineClient.get(engineEndpoint, {
      headers,
      params: { limit: 100, ...query },
    })

    if (data?.data && Array.isArray(data.data)) {
      const ops = data.data.map(item => ({
        updateOne: {
          filter: { [idField]: item[idField] },
          update: { $set: transform(item) },
          upsert: true,
        }
      }))
      if (ops.length > 0) {
        await Model.bulkWrite(ops)
      }
    }
  } catch (engineErr) {
    console.error(`Failed to sync ${syncErrorLabel} from engine:`, engineErr.message)
    synced = false
  }

  const items = await Model.find(readFilter).sort({ time: -1 }).lean()
  return { items, synced }
}

module.exports = { syncAndListTradeHistory }
