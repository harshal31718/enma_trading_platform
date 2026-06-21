# Add Endpoint

Add a new REST endpoint crossing the entire Enma stack: engine → server → client.

Arguments: $ARGUMENTS (Format: Action/Path, e.g. POST /trade/close-all)

## Instructions

### 1. Engine Layer

- Define a router endpoint inside `engine/routers/`.
- Use Pydantic v2 schemas for body parsing.
- Return standard response: `{"success": True, "data": {...}}`.
- All heavy computation stays in the engine — never proxy computation back to the server.

### 2. Server Layer

- **Route path**: Define inside `server/src/routes/`. There is **no** JWT auth or `express-validator` in this codebase — do not add them. Apply the `requireBinanceCredentials` middleware only if the endpoint proxies a Binance call; validate inputs inline in the controller.
- **Controller**: Write the method inside `server/src/controllers/` using the `engineClient.js` axios proxy — never raw axios in a controller.
- **Response**: Return via `ApiResponse.success(result.data.data)`.
- The server is a proxy — no computation here, and it never connects to TimescaleDB.

### 3. Client Layer

- Write a React custom hook in `client/src/hooks/` using TanStack Query `useMutation` or `useQuery`.
- Ensure mutations invalidate the appropriate keys (e.g. `['positions']`, `['backtest']`).
- Never call the server directly from a component — always through the hook.

### 4. Documentation

- Document request and response parameters in `workspace/docs/core/API_CONTRACTS.md`.
- Run `/sync-spec`.
