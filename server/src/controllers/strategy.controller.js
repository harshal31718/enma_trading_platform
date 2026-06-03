const Strategy = require('../models/Strategy')
const engineClient = require('../services/engineClient')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')

async function listStrategies(req, res, next) {
  try {
    const strategies = await Strategy.find({}).sort({ createdAt: 1 }).lean()
    const formatted = strategies.map(s => ({
      id: s._id,
      name: s.name,
      description: s.description,
      filePath: s.filePath,
      createdAt: s.createdAt,
      updatedAt: s.updatedAt,
    }))
    res.json(ApiResponse.success({ strategies: formatted }))
  } catch (err) {
    next(err)
  }
}

async function getStrategyCode(req, res, next) {
  try {
    const strategy = await Strategy.findById(req.params.id).lean()
    if (!strategy) throw new ApiError(404, 'NOT_FOUND', 'Strategy not found')

    const response = await engineClient.get(`/strategies/${strategy.name}/code`)
    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    if (err.response?.status === 404) {
      return next(new ApiError(404, 'NOT_FOUND', 'Strategy file not found on engine'))
    }
    next(err)
  }
}

module.exports = { listStrategies, getStrategyCode }
