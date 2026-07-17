CREATE TABLE IF NOT EXISTS candles (
  time             TIMESTAMPTZ  NOT NULL,
  exchange         TEXT         NOT NULL,
  symbol           TEXT         NOT NULL,
  timeframe        TEXT         NOT NULL,
  instrument_type  TEXT         NOT NULL DEFAULT 'spot',
  expiry           DATE         NULL,
  open             NUMERIC      NOT NULL,
  high             NUMERIC      NOT NULL,
  low              NUMERIC      NOT NULL,
  close            NUMERIC      NOT NULL,
  volume           NUMERIC      NOT NULL,
  quote_volume     NUMERIC      NOT NULL
);

SELECT create_hypertable('candles', 'time', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS candles_unique_idx
  ON candles (time, exchange, symbol, timeframe, instrument_type);

-- Plan 9 Step 9.7 (QNT-5): historical funding-rate ledger (perpetual futures
-- only — see services/funding_importer.py). Sparse (~every 8h per symbol),
-- irregular real event times from Binance's own fundingTime, not derived
-- boundaries.
CREATE TABLE IF NOT EXISTS funding_rates (
  time             TIMESTAMPTZ  NOT NULL,
  exchange         TEXT         NOT NULL,
  symbol           TEXT         NOT NULL,
  funding_rate     NUMERIC      NOT NULL,
  mark_price       NUMERIC      NULL
);

SELECT create_hypertable('funding_rates', 'time', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS funding_rates_unique_idx
  ON funding_rates (time, exchange, symbol);
