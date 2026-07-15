const ApiResponse = require('../utils/ApiResponse')
const logger = require('../config/logger')

function errorHandler(err, req, res, next) {
  const statusCode = err.statusCode || 500
  const code = err.code || 'INTERNAL_ERROR'
  const message = err.message || 'Something went wrong'
  logger.error({ err, requestId: req.id, statusCode, code }, message)
  res.status(statusCode).json(ApiResponse.error(code, message))
}

module.exports = errorHandler
