const express = require('express')
const router = express.Router()
const { getOrderHistory } = require('../controllers/orderHistory.controller')

router.get('/', getOrderHistory)

module.exports = router