# Plan 1 — Public access + admin-gated algo/testnet-start

**Status:** Shipped · **Priority:** — · **Depends on:** — · **Related:** —

## Goal

Make the application public — anyone with a Google account can log in — while keeping the
sensitive "start trading" actions locked to admin-invited users.

## Scope / what changes

- **Open login:** anyone can authenticate (Google OAuth + JWT cookie). No email whitelist.
- **Open to all authenticated users:**
  - Enter testnet API keys.
  - Place orders from the **Trade** page.
  - **View** the Algo Trading page, Chaos Mode, and the new-bots UI.
- **Gated to admin-granted users only (the *start* actions):**
  - Start a testnet algo session.
  - Start Chaos mode.
  - Non-granted users can see the UI but, on pressing start, get a message like
    *"Admin access required — only invited users can start algo trading."*
- Users request access from Settings; admins grant/revoke from an admin user table.

## Out of scope

- Mainnet trading (stays read-only / balance-only per existing decisions).
- Backtest and manual Trade gating (these stay open to all authenticated users).

## Open questions

- Confirm the exact copy of the "request access" / "denied" messaging.

## Notes

⚠️ **Likely already shipped.** Commits `ddce1c1` ("open login for all; gate Algo Trading start
behind per-user admin-granted access; replace email whitelist with admin user table +
Settings request flow") and `efa8cd5` (deploy docs for open-login + per-user algo gate) appear
to fully implement this. `CLAUDE.md` Core Rule 1 already documents the exact behavior
(`requireAlgoAccess` on `POST /algo/sessions` + `POST /algo/chaos`, admin bypass via role).

**Action before reopening:** verify against the running stack; if complete, mark `Shipped`. If
a gap exists, carve the gap into a fresh plan and mark this one `Shipped` for the delivered part.

---
_Originally captured as `1.md`._
