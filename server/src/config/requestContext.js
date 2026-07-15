// Plan 2 Step 2.4 (SYS-6): threads the current request's correlation id through
// async call chains (controllers → services → engineClient) without changing
// any function signatures. Set once per request by middleware/requestId.js.
const { AsyncLocalStorage } = require('async_hooks')

const requestContext = new AsyncLocalStorage()

function getRequestId() {
  return requestContext.getStore()?.requestId
}

module.exports = { requestContext, getRequestId }
