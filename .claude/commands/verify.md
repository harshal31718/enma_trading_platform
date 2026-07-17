# Verify

Run the Enma stack and confirm a change actually works — not just that it compiles. Also the
canonical bring-up runbook (absorbed the former `/setup`). Use after implementing or fixing
something, or to bring the stack up from a clean checkout.

Arguments: $ARGUMENTS (what to verify, e.g. "backtest cancel button" — optional)

---

## Bring the stack up (clean checkout / onboarding)

Everything runs in containers — **never** install TA-Lib, Node modules, or Python deps on the
host. `.env` files must be present in `engine/`, `server/`, `client/` (never commit or modify them).

```
docker compose up -d --build
docker compose ps      # all 6 services should become healthy
```

| Service | Port | Health check |
|---------|------|--------------|
| client (React/Vite) | 5173 | open http://localhost:5173 |
| server (Express) | 5000 | `curl -f http://localhost:5000/api/v1/health` |
| engine (FastAPI) | 8000 | `curl -f http://localhost:8000/health` |
| mongodb | 27017 | `docker exec enma_trading_platform-mongodb-1 mongosh --eval "db.adminCommand('ping')"` |
| redis | 6379 | `docker exec enma_trading_platform-redis-1 redis-cli ping` |
| timescaledb | 5432 | `docker exec enma_trading_platform-timescaledb-1 pg_isready -U enma -d enma_candles` |

**Common issues**
- **Engine slow / unhealthy on first boot:** TA-Lib compiles inside the image — the first `--build` is slow. Wait for it.
- **INSUFFICIENT_CANDLES / no candles:** candles auto-fetch on the first backtest; the first run for a symbol/timeframe takes longer.
- **Reset databases:** `docker compose down -v` drops the named volumes (mongo, redis, timescale) — destroys all candles, results, and settings. Use deliberately.

---

## Verify a change works

1. **Stack healthy:** `docker compose ps` shows all 6 services healthy; if not, bring it up (above).
2. **Health-check each touched service:**
   - Engine: `curl -f http://localhost:8000/health`
   - Server: `curl -f http://localhost:5000/api/v1/health`
   - Client: `http://localhost:5173` serves the SPA
3. **Exercise the actual change** end to end through the running app (UI at :5173, or the API). Do not assert success from reading code alone — observe the behavior.
4. **Check logs** on the touched service: `docker logs --tail 50 enma_trading_platform-<service>-1`.
5. **Data checks** (when relevant): MongoDB via `docker exec enma_trading_platform-mongodb-1 mongosh enma_trading --quiet --eval '...'`. Candles live in TimescaleDB (engine only) — never assert candle state from the server.
6. **Strategies seed check** (after engine restart): `docker logs enma_trading_platform-engine-1 | grep "Strategy ready"` (expect 5).

## Report

State plainly: what you ran, what you observed, and whether it works. If it failed, paste the real error and stop. Never report "verified" without having observed the behavior.
