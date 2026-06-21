const mongoose = require('mongoose')
const { v4: uuidv4 } = require('uuid')
const backtestQueue = require('../services/backtestQueue')
const engineClient = require('../services/engineClient')
const BacktestResult = require('../models/BacktestResult')
const BacktestTrade = require('../models/BacktestTrade')
const Strategy = require('../models/Strategy')
const Settings = require('../models/Settings')
const ApiResponse = require('../utils/ApiResponse')
const ApiError = require('../utils/ApiError')
const { resolveModelParams } = require('../utils/risk')

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

async function runBacktest(req, res, next) {
  try {
    const {
      jobId: clientJobId,
      strategyId,
      exchange,
      symbol,
      timeframe,
      startDate,
      endDate,
      capital,
      leverage,
      feeRate,
      riskParams: riskOverride,
    } = req.body

    if (!strategyId || !exchange || !symbol || !timeframe || !startDate || !endDate || !capital) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'Missing required fields for running a backtest')
    }

    const capitalNum = Number(capital)
    if (!isFinite(capitalNum) || capitalNum <= 0) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'capital must be a positive number')
    }

    const leverageNum = Number(leverage ?? 1)
    if (!Number.isInteger(leverageNum) || leverageNum < 1 || leverageNum > 125) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'leverage must be an integer between 1 and 125')
    }

    // Load saved exchange settings — used as defaults when the client omits fee/slippage
    const savedSettings = await Settings.findById('global') || {}
    const defaultFeeRate = savedSettings.takerFee ?? 0.0005
    const defaultSlippage = savedSettings.slippagePct ?? 0.0005
    const defaultFunding = savedSettings.fundingEnabled ?? false
    const defaultFundingRate = savedSettings.fundingRate ?? 0.0001

    // Risk model: merge per-run override (if any) over saved global defaults,
    // then map to the engine's snake_case risk_params dict.
    const riskParams = resolveModelParams(savedSettings, riskOverride)

    const feeRateNum = Number(feeRate !== undefined ? feeRate : defaultFeeRate)
    if (!isFinite(feeRateNum) || feeRateNum < 0 || feeRateNum > 0.05) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'feeRate must be a number between 0 and 0.05')
    }

    const startDt = new Date(startDate)
    const endDt = new Date(endDate)
    if (isNaN(startDt.getTime()) || isNaN(endDt.getTime())) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'startDate and endDate must be valid dates')
    }
    if (startDt >= endDt) {
      throw new ApiError(400, 'VALIDATION_ERROR', 'startDate must precede endDate')
    }

    const strategy = await Strategy.findById(strategyId).lean()
    if (!strategy) {
      throw new ApiError(404, 'NOT_FOUND', 'Strategy not found')
    }

    // Accept a pre-generated UUID from the client so the client can join the socket
    // room before the POST lands, eliminating the completion-event race condition.
    const jobId = (clientJobId && UUID_RE.test(clientJobId)) ? clientJobId : uuidv4()

    await BacktestResult.create({
      jobId,
      strategyId: strategy._id,
      strategyName: strategy.name,
      exchange,
      symbol,
      timeframe,
      startDate,
      endDate,
      capital: capitalNum,
      leverage: leverageNum,
      feeRate: feeRateNum,
      riskParams,
      status: 'queued',
    })

    await backtestQueue.add('run', {
      jobId,
      strategyFile: strategy.filePath,
      exchange,
      symbol,
      timeframe,
      startDate,
      endDate,
      capital: capitalNum,
      leverage: leverageNum,
      feeRate: feeRateNum,
      slippagePct: defaultSlippage,
      fundingEnabled: defaultFunding,
      fundingRate: defaultFundingRate,
      riskParams,
    }, { jobId })

    res.status(202).json(ApiResponse.success({ jobId, status: 'queued' }))
  } catch (err) {
    next(err)
  }
}

async function getBacktest(req, res, next) {
  try {
    const { id } = req.params
    const query = mongoose.Types.ObjectId.isValid(id)
      ? { $or: [{ _id: id }, { jobId: id }] }
      : { jobId: id }

    const backtest = await BacktestResult.findOne(query).lean()
    if (!backtest) throw new ApiError(404, 'NOT_FOUND', 'Backtest result not found')

    res.json(ApiResponse.success(backtest))
  } catch (err) {
    next(err)
  }
}

// Cursor-based pagination: pass ?before=<lastId> to get the next page.
// Avoids the O(skip) collection scan that .skip() requires.
async function listBacktests(req, res, next) {
  try {
    const parsedLimit = parseInt(req.query.limit, 10)
    const limit = Math.min(isNaN(parsedLimit) ? 20 : parsedLimit, 100)
    const before = req.query.before  // MongoDB _id string of the last item seen

    const { strategyName, symbol, timeframe, status, createdAfter, createdBefore } = req.query

    const filter = {}

    if (strategyName) filter.strategyName = strategyName
    if (symbol) filter.symbol = symbol
    if (timeframe) filter.timeframe = timeframe
    if (status) filter.status = status

    if (createdAfter || createdBefore) {
      filter.createdAt = {}
      if (createdAfter) {
        const afterDate = new Date(createdAfter)
        if (!isNaN(afterDate.getTime())) {
          filter.createdAt.$gte = afterDate
        }
      }
      if (createdBefore) {
        const beforeDate = new Date(createdBefore)
        if (!isNaN(beforeDate.getTime())) {
          filter.createdAt.$lte = beforeDate
        }
      }
      if (Object.keys(filter.createdAt).length === 0) {
        delete filter.createdAt
      }
    }

    if (before && mongoose.Types.ObjectId.isValid(before)) {
      filter._id = { $lt: new mongoose.Types.ObjectId(before) }
    }

    const backtests = await BacktestResult.find(filter)
      .select('jobId strategyName symbol timeframe status exchange createdAt error tradeCount')
      .sort({ _id: -1 })
      .limit(limit + 1)   // fetch one extra to know if there's a next page
      .lean()

    const hasMore = backtests.length > limit
    const page = hasMore ? backtests.slice(0, limit) : backtests
    const nextCursor = hasMore ? String(page[page.length - 1]._id) : null

    const formatted = page.map(b => ({
      id: b._id,
      jobId: b.jobId,
      strategyName: b.strategyName,
      symbol: b.symbol,
      timeframe: b.timeframe,
      status: b.status,
      exchange: b.exchange,
      createdAt: b.createdAt,
      error: b.error,
      tradeCount: b.tradeCount ?? null,
    }))

    res.json(ApiResponse.success({ backtests: formatted, nextCursor }))
  } catch (err) {
    next(err)
  }
}

// GET /api/v1/backtest/:id/trades?page=1&limit=50
async function getBacktestTrades(req, res, next) {
  try {
    const { id } = req.params
    const parsedPage = parseInt(req.query.page, 10)
    const parsedLimit = parseInt(req.query.limit, 10)
    const page = Math.max(1, isNaN(parsedPage) ? 1 : parsedPage)
    const limit = Math.min(isNaN(parsedLimit) ? 50 : parsedLimit, 5000)
    const skip = (page - 1) * limit

    // Resolve jobId — id may be a UUID (jobId) or a MongoDB ObjectId
    const query = mongoose.Types.ObjectId.isValid(id)
      ? { $or: [{ _id: id }, { jobId: id }] }
      : { jobId: id }

    const backtest = await BacktestResult.findOne(query).select('jobId tradeCount').lean()
    if (!backtest) throw new ApiError(404, 'NOT_FOUND', 'Backtest result not found')

    const jobId = backtest.jobId
    const total = backtest.tradeCount
      ?? await BacktestTrade.countDocuments({ jobId })

    const trades = await BacktestTrade.find({ jobId })
      .sort({ tradeIndex: 1 })
      .skip(skip)
      .limit(limit)
      .select('-_id -__v -jobId')
      .lean()

    res.json(ApiResponse.success({
      trades,
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

async function cancelBacktest(req, res, next) {
  try {
    const { id } = req.params
    const query = mongoose.Types.ObjectId.isValid(id)
      ? { $or: [{ _id: id }, { jobId: id }] }
      : { jobId: id }

    const backtest = await BacktestResult.findOne(query).lean()
    if (!backtest) throw new ApiError(404, 'NOT_FOUND', 'Backtest result not found')

    const response = await engineClient.post('/backtest/cancel', { jobId: backtest.jobId })
    res.json(ApiResponse.success(response.data.data))
  } catch (err) {
    next(err)
  }
}

module.exports = {
  runBacktest,
  getBacktest,
  listBacktests,
  getBacktestTrades,
  cancelBacktest,
}
