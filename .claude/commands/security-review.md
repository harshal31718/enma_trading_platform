# Security Review

Scan the working tree for Enma's known risk patterns before committing or sharing. Report findings; do not auto-fix unless asked.

Arguments: $ARGUMENTS (optional path / scope)

## Checks

1. **Secrets in committed or staged files:**
   - Tokens/keys: search for `ghp_`, `sk-`, `AKIA`, `-----BEGIN`, `password`, `secret`, `apiKey`, and Binance key patterns.
   - Confirm `.env` files are git-ignored and never staged.
   - Confirm no literal token sits in `.mcp.json`, `.claude/`, or any committed config — use `${ENV_VAR}` references, never literals.
2. **Multi-user scoping invariant:** every mutable Mongoose model (BacktestResult, BacktestTrade, LiveSession, Settings, TradeOrder, TradeExecution, TradeTransaction, TradeRecord) must carry `userId`, and every query on them must filter by the authenticated user's id — flag any unscoped query (cross-user leakage). `Strategy` is intentionally global (no `userId`). Confirm no `/api/v1/*` route bypasses `verifyJWT` except the auth routes.
3. **Layer-boundary leaks:**
   - Binance calls outside `engine/` (`fapi.binance.com`, signed REST, ccxt) inside `server/` or `client/`.
   - `server/` connecting to TimescaleDB.
   - Financial / order / indicator math in `server/` or `client/`.
4. **Key handling:** Binance keys must be AES-encrypted via `server/src/utils/encryption.js` before storage — never plaintext.
5. **Engine write boundary:** server writing `metrics` / `equityCurve` / trades to `backtestResults` / `backtestTrades` (only the engine may).

## Report

List each finding as `file:line`, severity, and the rule it violates. End with a clear pass/fail verdict and the top action items. For any exposed secret, recommend rotation explicitly.
