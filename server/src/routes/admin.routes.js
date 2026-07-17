const express = require('express')
const { listUsers, setUserAlgoAccess } = require('../controllers/admin.controller')
const { requireAdmin } = require('../middleware/auth.middleware')

const router = express.Router()

router.use(requireAdmin)

router.get('/users', listUsers)
router.patch('/users/:id/algo-access', setUserAlgoAccess)

module.exports = router
