const axios = require('axios')
const Settings = require('../models/Settings')

// Plan 14 / fixes-queue F3: per-user webhook notifications on trade
// lifecycle events (Discord/Slack/IFTTT via a plain POST). Server-only —
// the engine stays Binance-isolated and stateless re: notifications; the
// server already owns the event fan-out in algo.controller.js's
// handleEngineStats, which is the natural emit point.
const VALID_EVENTS = [
  'entry_fill', 'exit_fill', 'liquidation', 'session_start', 'session_stop', 'session_error',
  // Plan 22 Step 22.1: Session Risk Governor breach notifications. Must stay
  // in sync with Settings.js's `webhook.events` enum — that schema already
  // included this (and defaults to opt-in), but this module's own
  // VALID_EVENTS (used by settings.controller.js to validate a PUT) had
  // drifted, silently rejecting a user trying to save it (found in Plan 22
  // Step 22.7's doc pass).
  'risk_breach',
]

function _buildBody(eventType, payload) {
  return { event: eventType, ts: new Date().toISOString(), ...payload }
}

// Single HTTP attempt, no retry — throws on failure so callers decide what
// to do with it (dispatchWebhook retries + swallows; sendTestWebhook
// surfaces the error to the caller for immediate UI feedback).
async function _sendOnce({ url, format, timeoutMs }, body) {
  if (format === 'form') {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(body)) {
      params.append(key, typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value))
    }
    await axios.post(url, params, { timeout: timeoutMs })
    return
  }
  await axios.post(url, body, { timeout: timeoutMs, headers: { 'Content-Type': 'application/json' } })
}

/**
 * Fire-and-forget dispatch of a trade-lifecycle event to the user's
 * configured webhook. Reads `Settings.webhook` fresh (no caching — config
 * changes take effect on the very next event). No-ops silently if
 * disabled, no url configured, or `eventType` isn't in the user's opted-in
 * `events` list.
 *
 * Contract: this function NEVER throws and NEVER rejects. A slow or dead
 * webhook endpoint must never stall or fail the trade path that calls it —
 * callers should invoke this WITHOUT awaiting it (or await only after their
 * own persist path has already resolved), per Plan 14.
 */
async function dispatchWebhook(userId, eventType, payload = {}) {
  try {
    const settings = await Settings.findOne({ userId }).select('webhook').lean()
    const cfg = settings && settings.webhook
    if (!cfg || !cfg.enabled || !cfg.url) return
    // An empty events array means "opted into nothing" (block everything),
    // not "unfiltered" — only a genuinely missing/non-array `events` (a
    // malformed doc, never produced by the schema's own default) skips this
    // filter and falls through unfiltered.
    if (Array.isArray(cfg.events) && !cfg.events.includes(eventType)) return

    const body = _buildBody(eventType, payload)
    const retries = Number.isFinite(cfg.retries) ? cfg.retries : 2
    const timeoutMs = Number.isFinite(cfg.timeoutMs) ? cfg.timeoutMs : 5000
    const resolved = { url: cfg.url, format: cfg.format === 'form' ? 'form' : 'json', timeoutMs }

    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        await _sendOnce(resolved, body)
        return
      } catch (err) {
        if (attempt === retries) {
          console.error(
            `[Webhook] dispatch failed after ${retries + 1} attempt(s) (user=${userId}, event=${eventType}): ${err.message}`
          )
        }
        // else: loop retries — bounded, no backoff needed at this volume/priority.
      }
    }
  } catch (err) {
    // Covers the Settings lookup itself failing — still never throw.
    console.error(`[Webhook] dispatchWebhook error (user=${userId}, event=${eventType}): ${err.message}`)
  }
}

/**
 * One-shot test delivery for the Settings "Send test" button. Unlike
 * dispatchWebhook, this takes the config directly (so the UI can test a URL
 * before saving it) and THROWS on failure so the controller can report a
 * real pass/fail to the user instead of swallowing it.
 */
async function sendTestWebhook({ url, format, timeoutMs }) {
  if (!url) {
    throw new Error('No webhook URL configured')
  }
  const body = _buildBody('status', { message: 'Enma test webhook', sessionId: null })
  await _sendOnce(
    { url, format: format === 'form' ? 'form' : 'json', timeoutMs: Number.isFinite(timeoutMs) ? timeoutMs : 5000 },
    body
  )
}

module.exports = { dispatchWebhook, sendTestWebhook, VALID_EVENTS }
