// Binance USD-M Futures WebSocket manager.
//
// Official docs: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams
//
// Different stream types route to different base paths:
//   /public/ws/  — high-frequency depth streams (@depth*)
//   /market/ws/  — everything else (kline, aggTrade, ticker, trade)

const RECONNECT_DELAY_MS = 3000

function baseUrl(streamName) {
  if (streamName.includes('@depth')) {
    return 'wss://fstream.binance.com/public/ws'
  }
  return 'wss://fstream.binance.com/market/ws'
}

class BinanceWSManager {
  constructor() {
    // streamName → { ws: WebSocket|null, callbacks: Set, timer: TimeoutId|null }
    this.streams = new Map()
  }

  _open(streamName) {
    const entry = this.streams.get(streamName)
    if (!entry) return

    const ws = new WebSocket(`${baseUrl(streamName)}/${streamName}`)
    entry.ws = ws

    ws.onmessage = (evt) => {
      const e = this.streams.get(streamName)
      if (!e) return
      let msg
      try { msg = JSON.parse(evt.data) } catch { return }
      e.callbacks.forEach((cb) => { try { cb(msg) } catch {} })
    }

    ws.onclose = () => {
      const e = this.streams.get(streamName)
      if (!e) return
      e.ws = null
      e.timer = setTimeout(() => this._open(streamName), RECONNECT_DELAY_MS)
    }

    ws.onerror = () => {
      // onclose fires immediately after
    }
  }

  subscribe(streamName, callback) {
    if (!this.streams.has(streamName)) {
      // Defer open by one microtask so React Strict Mode's immediate
      // unmount→remount cycle cancels the open before the socket is created.
      const entry = { ws: null, callbacks: new Set(), timer: null, openTimer: null }
      this.streams.set(streamName, entry)
      entry.openTimer = setTimeout(() => {
        entry.openTimer = null
        if (this.streams.has(streamName)) this._open(streamName)
      }, 0)
    }

    const entry = this.streams.get(streamName)
    entry.callbacks.add(callback)

    return () => {
      const e = this.streams.get(streamName)
      if (!e) return
      e.callbacks.delete(callback)

      if (e.callbacks.size > 0) return

      // Cancel deferred open if it hasn't fired yet
      if (e.openTimer !== null) {
        clearTimeout(e.openTimer)
        e.openTimer = null
      }
      clearTimeout(e.timer)
      if (e.ws) {
        e.ws.onclose = null
        e.ws.onerror = null
        e.ws.close()
        e.ws = null
      }
      this.streams.delete(streamName)
    }
  }
}

const binanceWS = new BinanceWSManager()
export default binanceWS
