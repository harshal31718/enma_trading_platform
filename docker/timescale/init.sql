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
