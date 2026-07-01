const TradeRecord = require('../models/TradeRecord')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')

// Whitelist of columns the client is allowed to sort by (UI Refinement Phase 2, §3.4).
// Never pass req.query.sort straight into .sort() — that would let a client sort by an
// arbitrary/unindexed field or inject a Mongo operator.
const SORTABLE_FIELDS = new Set([
  'exitTime', 'entryTime', 'symbol', 'side', 'netPnl', 'pnlPct', 'leverage', 'margin',
])

async function getOrderHistory(req, res, next) {
  try {
    const parsedPage = parseInt(req.query.page, 10)
    const parsedLimit = parseInt(req.query.limit, 10)
    const page = Math.max(1, isNaN(parsedPage) ? 1 : parsedPage)
    const limit = Math.min(isNaN(parsedLimit) ? 50 : parsedLimit, 200)
    const skip = (page - 1) * limit

    const { symbol, source, side, executedBy } = req.query
    const filter = { userId: req.user.id }

    if (symbol) filter.symbol = symbol
    if (source) filter.source = source
    if (side) filter.side = side
    if (executedBy) filter.executedBy = executedBy

    const sortField = SORTABLE_FIELDS.has(req.query.sort) ? req.query.sort : 'exitTime'
    const sortOrder = req.query.order === 'asc' ? 1 : -1

    const [records, total] = await Promise.all([
      TradeRecord.find(filter)
        .sort({ [sortField]: sortOrder })
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
      sort: sortField,
      order: sortOrder === 1 ? 'asc' : 'desc',
    }))
  } catch (err) {
    next(err)
  }
}

module.exports = {
  getOrderHistory,
}