const TradeRecord = require('../models/TradeRecord')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')

async function getOrderHistory(req, res, next) {
  try {
    const parsedPage = parseInt(req.query.page, 10)
    const parsedLimit = parseInt(req.query.limit, 10)
    const page = Math.max(1, isNaN(parsedPage) ? 1 : parsedPage)
    const limit = Math.min(isNaN(parsedLimit) ? 50 : parsedLimit, 200)
    const skip = (page - 1) * limit

    const { symbol, source, side, executedBy } = req.query
    const filter = {}

    if (symbol) filter.symbol = symbol
    if (source) filter.source = source
    if (side) filter.side = side
    if (executedBy) filter.executedBy = executedBy

    const [records, total] = await Promise.all([
      TradeRecord.find(filter)
        .sort({ exitTime: -1 })
        .skip(skip)
        .limit(limit)
        .lean(),
      TradeRecord.countDocuments(filter),
    ])

    res.json(ApiResponse.success({
      records,
      pagination: {
        page,
        limit,
        total,
        totalPages: Math.ceil(total / limit),
      },
    }))
  } catch (err) {
    next(err)
  }
}

module.exports = {
  getOrderHistory,
}