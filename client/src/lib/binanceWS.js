const WS_URL = 'wss://fstream.binance.com/stream'
const INITIAL_RECONNECT_DELAY = 1000
const MAX_RECONNECT_DELAY = 30000

class BinanceWSManager {
  constructor() {
    this.ws = null
    this.listeners = new Map()   // streamName → Set<callback>
    this.idCounter = 1
    this.reconnectDelay = INITIAL_RECONNECT_DELAY
    this.intentionalClose = false
    this._connect()
  }

  _connect() {
    this.intentionalClose = false
    this.ws = new WebSocket(WS_URL)

    this.ws.onopen = () => {
      this.reconnectDelay = INITIAL_RECONNECT_DELAY
      // Re-subscribe all active streams after reconnect
      const streams = [...this.listeners.keys()].filter(
        (s) => this.listeners.get(s).size > 0
      )
      if (streams.length > 0) {
        this._send({ method: 'SUBSCRIBE', params: streams, id: this.idCounter++ })
      }
    }

    this.ws.onmessage = (evt) => {
      let msg
      try { msg = JSON.parse(evt.data) } catch { return }

      // Combined stream envelope: { stream, data }
      if (!msg.stream) return
      const callbacks = this.listeners.get(msg.stream)
      if (!callbacks) return
      callbacks.forEach((cb) => {
        try { cb(msg.data) } catch {}
      })
    }

    this.ws.onclose = () => {
      if (this.intentionalClose) return
      setTimeout(() => {
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, MAX_RECONNECT_DELAY)
        this._connect()
      }, this.reconnectDelay)
    }

    this.ws.onerror = () => {
      // onclose fires after onerror; reconnect handled there
      this.ws.close()
    }
  }

  _send(payload) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload))
    }
  }

  subscribe(streamName, callback) {
    if (!this.listeners.has(streamName)) {
      this.listeners.set(streamName, new Set())
    }
    const set = this.listeners.get(streamName)
    const isFirst = set.size === 0
    set.add(callback)

    if (isFirst) {
      this._send({ method: 'SUBSCRIBE', params: [streamName], id: this.idCounter++ })
    }

    return () => {
      set.delete(callback)
      if (set.size === 0) {
        this.listeners.delete(streamName)
        this._send({ method: 'UNSUBSCRIBE', params: [streamName], id: this.idCounter++ })
      }
    }
  }

  destroy() {
    this.intentionalClose = true
    this.ws?.close()
  }
}

// Singleton — one connection for the entire app lifetime
const binanceWS = new BinanceWSManager()
export default binanceWS
