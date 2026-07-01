const engineClient = require('../services/engineClient')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')

async function getStats(req, res, next) {
  try {
    const response = await engineClient.get('/dashboard/stats', { params: { userId: req.user.id } })
    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    next(new ApiError(503, 'ENGINE_UNAVAILABLE', 'Could not fetch dashboard stats from engine'))
  }
}

async function getPerformanceCalendar(req, res, next) {
  try {
    const response = await engineClient.get('/dashboard/performance-calendar', { params: { userId: req.user.id } })
    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    next(new ApiError(503, 'ENGINE_UNAVAILABLE', 'Could not fetch performance calendar from engine'))
  }
}

module.exports = { getStats, getPerformanceCalendar }
