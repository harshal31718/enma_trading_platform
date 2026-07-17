// Minimal static fallback — the client fetches live symbol rules from the engine
// as its primary source (via GET /candles/symbols → symbolsData?.rules?.[symbol]).
// This file is only used when the engine is unreachable (4 common symbols).
export const SYMBOL_LIMITS = {
  "BTCUSDT": { "tickSize": 0.1, "stepSize": 0.0001, "minQty": 0.0001, "minNotional": 50.0 },
  "ETHUSDT": { "tickSize": 0.01, "stepSize": 0.001, "minQty": 0.001, "minNotional": 20.0 },
  "SOLUSDT": { "tickSize": 0.01, "stepSize": 0.01, "minQty": 0.01, "minNotional": 5.0 },
  "BNBUSDT": { "tickSize": 0.01, "stepSize": 0.01, "minQty": 0.01, "minNotional": 5.0 },
};
