const express = require('express')
const { getAllowedEmails, addAllowedEmail, removeAllowedEmail } = require('../controllers/admin.controller')
const { requireAdmin } = require('../middleware/auth.middleware')

const router = express.Router()

router.use(requireAdmin)

router.get('/allowed-emails', getAllowedEmails)
router.post('/allowed-emails', addAllowedEmail)
router.delete('/allowed-emails/:email', removeAllowedEmail)

module.exports = router
