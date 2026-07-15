// Plan 2 Step 2.4 (SYS-6): accepts an inbound X-Request-Id (e.g. forwarded from
// a caller that already has one) or generates a fresh uuid, attaches it to
// req.id, echoes it on the response, and threads it through the async
// call chain via requestContext so engineClient can propagate it to the engine.
const { v4: uuidv4 } = require('uuid')
const { requestContext } = require('../config/requestContext')

function requestId(req, res, next) {
  const id = req.headers['x-request-id'] || uuidv4()
  req.id = id
  res.setHeader('X-Request-Id', id)
  requestContext.run({ requestId: id }, next)
}

module.exports = requestId
