const ApiResponse = require('../utils/ApiResponse')

function errorHandler(err, req, res, next) {
  console.error('[Error]', err)
  const statusCode = err.statusCode || 500
  const code = err.code || 'INTERNAL_ERROR'
  const message = err.message || 'Something went wrong'
  res.status(statusCode).json(ApiResponse.error(code, message))
}

module.exports = errorHandler
