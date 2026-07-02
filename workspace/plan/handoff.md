---
## 2026-07-02 — Deployment Docs Updated (post-deploy corrections + branch/merge model) — COMPLETE ✅

**Goal:** User asked to update `dev`'s docs to reflect the new `dev`/`main` merge plan (see the
"`main` Stripped..." entry below) and, while in there, apply the 4 plan-doc corrections flagged
during the actual deployment session (also below) — all in `workspace/plan/deployment_plan.md`,
which only exists on `dev` now.

**Corrections applied (were wrong or missing, confirmed against the real deploy):**
1. **iptables warning (Step 1):** no longer claims `-I INPUT 6` reliably lands before the REJECT
   rule — now instructs verifying rule order via `iptables -L INPUT -n --line-numbers` and adjusting
   the insert position if the ACCEPT rules land after any REJECT/DROP line.
2. **Clone step (Step 3.4):** added a full private-repo path (SSH deploy key generation,
   `gh repo deploy-key add`, `~/.ssh/config` pinning, cloning as `ubuntu` not root) alongside the
   original public-repo one-liner.
3. **ARM64 Compatibility (Troubleshooting §3):** corrected the false "TA-Lib builds natively on
   aarch64 — no changes needed" claim. Now explains TA-Lib's bundled `config.guess`/`config.sub`
   don't recognize aarch64, and that `engine/Dockerfile` already carries the fix — no action needed
   *because of that fix*, not because TA-Lib is naturally ARM64-clean.
4. **Nginx/TLS (Step 6):** added a new hard-verify sub-step (`curl` the public IP/domain for a `200`
   from *outside* the VPS) before running certbot, with a note that the OCI Security List console
   has been observed silently saving only one of two ingress rules in a single session.

**New section — branch/merge model documented (the actual ask):**
- Added §0 "Doc/Tooling Divergence Between `dev` and `main` (intentional)" under "Cross-Branch
  Environment & URL Management," explaining `main` permanently lacks `.claude/`, `AGENTS.md`,
  `CLAUDE.md` files, and `workspace/` by design, and how the `.gitattributes` `merge=ours` +
  local `git config merge.ours.driver true` mechanism keeps future `dev`→`main` merges from
  conflicting or resurrecting those paths.
- Reworded the top-of-section claim: the "byte-identical branches" invariant now applies only to
  what ships to production (code + config), not the full file tree.
- Added the `git config merge.ours.driver true` prerequisite call-out to "Release / Update
  Workflow" and a cross-reference to it from "Branch Promotion Workflow."

**Files changed:** `workspace/plan/deployment_plan.md`, `workspace/plan/handoff.md` (this entry +
marking the corrections list above as applied). Both `dev`-only, as designed.

**Open questions:** None.

---
## 2026-07-02 — `main` Stripped of Agent-Tooling & Planning Docs — COMPLETE ✅

**Goal:** User wants `.claude/`, `AGENTS.md`, all `CLAUDE.md` files, and `workspace/` gone from
`main` (production branch) — they're used only by AI coding agents during development, never read
at runtime by `server/`, `client/`, or `engine/`, and the VPS has no use for them.

**Important — this is a real, intentional divergence between `dev` and `main`, not a bug.**
`dev` keeps all of these files (agents need them every session). `main` now permanently lacks them.
This breaks the "byte-identical branches" invariant `deployment_plan.md` used to describe — that
doc itself no longer exists on `main` as of this change, so the invariant is moot there, but it's
worth remembering next time `dev`'s docs are edited: **`main` will never see those doc edits, by
design.**

**Mechanism (so future merges don't fight this):**
- Removed on `main` only (commit `2eb65ef`): `.claude/` (9 files), `AGENTS.md`, root `CLAUDE.md`,
  `client/CLAUDE.md`, `engine/CLAUDE.md`, `server/CLAUDE.md`, `workspace/` (71 files — archive,
  docs, next_phase, plan).
- Added `.gitattributes` on `main` mapping those exact paths to `merge=ours`. Combined with a
  **local repo config** (`git config merge.ours.driver true` — already set on this machine), a
  future `git checkout main && git merge dev` will keep main's deletion for these paths
  automatically — no conflict, no resurrection — even though `dev` edits `workspace/plan/handoff.md`
  constantly. **If this is ever run from a different machine, `git config merge.ours.driver true`
  must be set there too**, or the merge will conflict (modify/delete) on these paths instead of
  silently doing the right thing.
- VPS (`/opt/enma`, tracks `main`) pulled to `2eb65ef` — confirmed all target paths gone from disk.
  No container rebuild needed; none of this touches runtime code.

**No root `README.md` exists yet** — user said one could be added later if wanted; not created
this session (nothing requested it explicitly).

**Open items:**
- If `main` is ever the fresh-clone target for onboarding a new contributor (currently N/A —
  single-user project), they'll be missing all architecture/API docs by design. Not a concern now.
- Housekeeping done same session: deleted local `stable-single-user` branch ref (already fully
  merged into `main`, byte-identical to `origin/stable-single-user` — nothing lost). Fixed local
  `main`'s missing upstream tracking (`git branch --set-upstream-to=origin/main main`) — it had
  none because `push.autoSetupRemote` is `false` in this git config, so `git push origin main`
  alone never wires up tracking.

---
## 2026-07-02 — Production Deployment to Oracle Cloud — COMPLETE ✅

**Goal:** Finish deploying Enma to the OCI VPS (`enma-production`, ap-mumbai-1), resuming from
`workspace/plan/leftof.md` (OS upgrade paused mid-deploy in the prior session).

**Done this session (all of `leftof.md` §2–3):**
- **OS upgrade finished:** `do-release-upgrade` to Ubuntu 22.04 completed, rebooted, confirmed
  `22.04.5 LTS`, ran `apt --fix-broken install` + `autoremove` cleanup.
- **Host firewall:** opened 80/443 in iptables — **found and fixed a rule-ordering bug**: the
  `-I INPUT 6` insert (from `deployment_plan.md`) landed *after* the chain's catch-all REJECT rule
  (position 5), so the ACCEPT rules were dead. Reordered to insert before REJECT, removed dead
  duplicates, `netfilter-persistent save`.
- **Stack installed:** docker.io, docker-compose-v2, nginx, certbot, python3-certbot-nginx, git.
- **Repo access — plan was wrong:** `deployment_plan.md`'s bare `git clone https://github.com/...`
  assumes a public repo; **the repo is private**. Fixed by generating an ed25519 deploy key on the
  VPS (`~/.ssh/enma_deploy_key`) and registering it read-only via `gh repo deploy-key add` (repo
  settings → Deploy keys, id `156130614`). VPS `~/.ssh/config` pins `github.com` to that key.
  Cloned to `/opt/enma`, checked out `dev` (not `main` — per standing instruction, VPS tracks `dev`
  for now).
- **`.env` uploaded** from `C:\Users\harsh\.enma\prod.env` to `/opt/enma/.env` (chmod 600).
- **Client built** via throwaway `node:20-alpine` container → `/opt/enma/client/dist`.
- **Nginx + TLS:** HTTP-only vhost first, then `certbot --nginx -d enmaquant.duckdns.org`
  (succeeded, expires 2026-09-30, auto-renewal confirmed via `certbot renew --dry-run`).
- **OCI Security List was never actually configured** despite `leftof.md` §1 claiming "added in
  the cloud console" — the subnet's Default Security List only had ingress for port 22 + ICMP.
  User added TCP 80 and TCP 443 (`0.0.0.0/0`) ingress rules via the console (two separate
  `Add Ingress Rules` actions — the first pass only saved the 80 rule, needed a second pass for
  443). No NSG was attached, so that wasn't a factor.
- **TA-Lib ARM64 build failure — real Dockerfile bug, not session config:** `engine/Dockerfile`'s
  `ta-lib-0.4.0-src.tar.gz` ships a `config.guess` from 2006 that doesn't recognize aarch64 →
  `./configure` fails with "cannot guess build type". `deployment_plan.md`'s claim that "TA-Lib
  builds natively on aarch64 — no changes needed" is **wrong** for this TA-Lib version. Fixed by
  downloading fresh `config.guess`/`config.sub` from the GNU config project before `./configure`.
  Committed `8296e6b` on `dev`, pushed, pulled on VPS, rebuild succeeded.
- **`docker compose -f docker-compose.prod.yml up -d --build`** — all 4 services
  (`redis`, `timescaledb`, `engine`, `server`) came up healthy.
- **Verified:** `/api/v1/health` returns `{"status":"ok","mongo":"connected","redis":"connected"}`
  both on `127.0.0.1:5000` and via `https://enmaquant.duckdns.org`. Frontend HTML/JS/CSS serves
  correctly over HTTPS with a valid cert. User confirmed manually: login page loads, Google OAuth
  sign-in with `admin.enmaquant@gmail.com` works, dashboard + Socket.IO connected, `/admin`
  reachable, backtest runs end-to-end.

**Files changed:** `engine/Dockerfile` (TA-Lib config.guess/config.sub fix, commit `8296e6b` on
`dev`, already pushed). VPS-side state (not in git): iptables rules, `/opt/enma/.env`,
`/etc/nginx/sites-available/enma`, Let's Encrypt cert, `~/.ssh/enma_deploy_key`.

**Plan doc corrections — all applied 2026-07-02, see the "Deployment Docs Updated" entry above:**
1. ~~`deployment_plan.md` Step 3.4 assumes a public repo~~ — done: added a deploy-key section for private repos.
2. ~~iptables insert position (`-I INPUT 6`) claimed reliable~~ — done: now says verify via
   `iptables -L INPUT -n --line-numbers` and adjust position instead of trusting a fixed insert.
3. ~~"TA-Lib builds natively on aarch64 — no changes needed"~~ — done: corrected to explain the
   config.guess/config.sub fix baked into `engine/Dockerfile` is *why* no action is needed.
4. ~~Security List assumed done from a prior claim~~ — done: added a hard-verify `curl` step
   before certbot, plus a note that OCI's console has silently saved only one of two rules before.

**Next session / open items (from `leftof.md` §5, still open):**
- ~~Ask user when `dev` → `main` promotion + tagging should happen~~ — **done same session**: merged
  `dev` → `main` (fast-forward, `79ed49f`), tagged `v1.0`, VPS switched to track `main`.
- Consider Oracle idle-reclamation insurance (keep-alive cron, or PAYG upgrade) — not done.
- Public IP is **Ephemeral**, not Reserved (seen in OCI console this session) — plan recommended a
  reserved IP so it survives instance stop/start without a DNS update. Not yet switched.
- `leftof.md` deleted this session per its own §5 instruction (superseded by this entry).

**⚠️ New — OCI Free Trial expiry, checked 2026-07-02:** Tenancy `enmaquant` is on a **Universal
Credits trial subscription, SGD 400 credit, expiring 2026-07-30** (confirmed via Cost Management →
Overview → Active Subscriptions gauge) — not a plain indefinite Always-Free signup. Cost Analysis
confirms **SGD 0.00 spent to date** (the `VM.Standard.A1.Flex` 4 OCPU/24GB shape is fully within
Always Free eligibility). **User decision (2026-07-02): accept the risk, stay on the trial, deal
with it if/when it breaks** — explicitly informed that Oracle's behavior at trial expiry without
upgrading to Pay As You Go is unconfirmed (`[Guessing]`, not verified against current OCI docs):
could be a harmless pause/restart, or could reclaim the compute resource entirely. **If reclaimed,
this is not just downtime** — TimescaleDB candle data lives only on that instance's Docker volume
(unlike MongoDB, which is external on Atlas and safe) and would need to be refetched from Binance
from scratch; nothing else on the VM is backed up externally. Action-forcing date: **2026-07-30**.
The safe fix (not yet done, user's call): ☰ → Governance & Administration → Account Management →
"Upgrade and Pay As You Go" — adding a payment method does not itself trigger billing as long as
usage stays within Always Free limits.

**Open questions:** None blocking — the two items above (main promotion timing, reserved IP) are
user-scheduling decisions, not technical blockers.

---
## 2026-07-02 — Deployment Kickoff: Domain Decision + Config Finalized — CODE-SIDE COMPLETE ✅

**Goal:** Proceed with `deployment_plan.md`. Verified repo deploy-readiness, resolved the domain decision, finalized all domain-dependent config.

**Done this session:**
- **Verified deploy-readiness:** `trust proxy` present in `server/src/app.js:34`; `docker-compose.prod.yml`, `client/.env.production`, `.env.example` all tracked; `dev` = `main` = `origin/main` = `origin/dev` at `7339fb3` — no promotion needed.
- **Domain decision:** User initially wanted to drop domains entirely; pushed back (raw IP breaks Google OAuth login — origins/redirect URIs reject IPs — and secure cookies). User agreed to free DuckDNS and claimed **`enmaquant.duckdns.org`**.
- **`client/.env.production`:** placeholder replaced with `https://enmaquant.duckdns.org` (both `VITE_API_URL` and `VITE_SOCKET_URL`).
- **`deployment_plan.md`:** all `yourdomain.com` occurrences replaced with `enmaquant.duckdns.org`; prerequisites rewritten (domain done; DuckDNS A-record note; reserved-public-IP recommendation; benign ipv6 notice); OAuth section notes to edit the existing client rather than create a new one.

**⚠️ Critical gotcha recorded:** DuckDNS auto-filled the user's home ISP IP (`152.59.186.180`) at claim time. **The DuckDNS IP must be updated to the VPS public IP once the OCI instance exists — before the certbot step.**

**Files changed:** `client/.env.production`, `workspace/plan/deployment_plan.md`, `workspace/plan/handoff.md` — uncommitted on `dev`.

**Next session / remaining (all manual, user-driven — follow deployment_plan.md top to bottom):**
1. OCI signup + `VM.Standard.A1.Flex` instance (Step 1) — user had nothing provisioned as of this session.
2. Update DuckDNS IP to the VPS public IP.
3. Google OAuth console: add `https://enmaquant.duckdns.org` origin + `/api/v1/auth/google/callback` redirect to the existing client (user reports Atlas + OAuth otherwise done).
4. Atlas: whitelist the VPS public IP.
5. VPS Steps 3–8 (base setup, `.env`, client build, nginx+certbot, compose up, verify).
6. Commit the config changes and merge `dev` → `main` before the VPS clones.

**Open questions:** None.

---
## 2026-07-02 — Deployment Plan Refinement + Pre-Deploy Changes — COMPLETE ✅

**Goal:** Merge `auth` into `dev`, rewrite `workspace/plan/deployment_plan.md` verified against actual code, and implement its pre-deploy code changes on `dev`.

**Done this session:**
- **Merged `auth` → `dev`** (clean fast-forward, 13 commits; `auth` untouched).
- **Rewrote `deployment_plan.md`** (`d838fb9`): fixed env var names to match code (`TIMESCALE_URL`, `REDIS_URL`, `MONGO_DB`, `ENGINE_API_KEY`), documented the `SERVER_URL` (internal Docker URL for engine callbacks) vs `GOOGLE_CALLBACK_URL` (public OAuth callback, priority override in `passport.js`) split, added nginx install + Oracle host-iptables gotcha + containerized client build + `certbot --nginx` renewal + release/rollback workflow.
- **Implemented pre-deploy changes** (`b0518d4`, `10ea1c5`):
  - `server/src/app.js`: `app.set('trust proxy', 1)` (required behind nginx for express-rate-limit v7, `req.ip`, secure cookies). Boot-verified in a container: trust proxy = 1.
  - `docker-compose.prod.yml` (new, repo root): prod commands (`node src/server.js`, uvicorn without `--reload`), healthchecks on all services, server bound `127.0.0.1:5000` only, engine/redis/timescale publish no host ports, `enma_engine_strategies` volume. Validates via `docker compose config`.
  - `client/.env.production` (new, tracked): prod Vite URLs; required a `!client/.env.production` exception in `.gitignore` (blanket `.env.production` ignore was blocking it).
  - `.env.example`: added `GOOGLE_CLIENT_ID/SECRET`, `GOOGLE_CALLBACK_URL`, `ADMIN_EMAIL`, `ENCRYPTION_KEY`, `SERVER_URL`.

**Files changed:** `workspace/plan/deployment_plan.md`, `server/src/app.js`, `docker-compose.prod.yml`, `client/.env.production`, `.env.example`, `.gitignore` — all on `dev` only.

**Next session:** Deployment itself is manual (OCI account, domain, DNS, VPS steps in the plan). Before first deploy: replace `yourdomain.com` placeholder in `client/.env.production` with the real domain. Promote `dev` → `main` when releasing.

**Open questions:** None.

---
## 2026-07-02 — UI Refinement Phase 3 (UX Polish & Responsiveness) — ALL STEPS COMPLETE ✅

**Goal:** Complete all tasks for Phase 3 UI Refinement (Code Quality/Refactoring, Design System Sweep, Mobile Responsiveness) and remaining items from `workspace/plan/ui_refinement.md`.

**Done this session:**
- **Table Responsive wrappers & min-h chart (§4.3.7/§4.3.2)**: Wrapped `PositionsTable` and `OpenOrdersTable` in `overflow-x-auto` layouts inside `Trade.jsx`. Set chart container height constraint `min-h-[300px] lg:min-h-0` in `Trade.jsx` to prevent flex collapse on mobile.
- **Mobile Dialog steps indicator collapse (§4.3.6)**: Refactored `NewBacktestWizard.jsx` and `ChaosWizard.jsx` steps progress bar to collapse to a clear current step fraction (`Step X of Y: Label`) under `sm` screens.
- **Global axios connectivity toast interceptor (§4.7)**: Configured a response interceptor in `axios.js` to toast connectivity or 5xx server issues, automatically deduplicating parallel requests to avoid toast clutter.
- **Visual & Design System Standardisation**:
  - Centralized `<Badge>` component in `client/src/components/ui/badge.jsx` with variants and mappings to support status labels, buy/sell indicators, long/short types, and bot/manual orders.
  - Replaced custom div elements with `<Card>` panels inside `StrategyCard.jsx` and `AdminPanel.jsx`.
  - Refactored raw button elements to standard `<Button>` components in `Settings.jsx`.
  - Swept skeleton loaders in `AlgoTrading.jsx`, `NewSessionWizard.jsx`, and `NewBacktestWizard.jsx` to slate colors.
- **Mobile Grid Columns breakpoints**: Added responsive grid columns on `Backtest.jsx` metrics and settings layout.
- **Optimized bundle size via lazy loading**: Configured dynamic imports (`React.lazy`) and `<Suspense>` on heavy widgets, wizards, and matrices.
- **Verification**: Production build compiles in 8.01 seconds; backend boundary test suite passes 20/20.

**Files changed:**
- `client/src/components/algo/ChaosWizard.jsx`
- `client/src/components/algo/NewSessionWizard.jsx`
- `client/src/components/algo/SessionCard.jsx`
- `client/src/components/ui/badge.jsx`
- `client/src/features/backtest/NewBacktestWizard.jsx`
- `client/src/features/strategies/StrategyCard.jsx`
- `client/src/lib/axios.js`
- `client/src/pages/AdminPanel.jsx`
- `client/src/pages/AlgoTrading.jsx`
- `client/src/pages/Backtest.jsx`
- `client/src/pages/RiskDashboard.jsx`
- `client/src/pages/Settings.jsx`
- `client/src/pages/Trade.jsx`
- `workspace/docs/state/CURRENT_STATE.md`
- `workspace/plan/handoff.md`

**Next session:** Complete. All UI Refinement phase workstreams have been fully resolved, documented, and verified.

**Open questions:** None.

---
## 2026-07-02 — UI Refinement Phase 2 (Structural & Convention) — ALL STEPS COMPLETE ✅

**Goal:** Complete all remaining deferred items from Phase 2 UI Refinement (Toasts, ARIA/A11y sweep, polling indicators, table sorting, empty states).

**Done this session:**
- **3.9 Toasts Integration**: Installed `react-hot-toast` and configured it in `App.jsx`. Replaced local success states with toasts in `Settings.jsx` and `RiskDashboard.jsx`. Wired toasts for strategy creation (`StrategyCreateDialog.jsx`), backtest cues (`Backtest.jsx`), and bot sessions mutations (`useAlgoSessions.js`).
- **3.10 ARIA & A11y Sweep**: Added appropriate accessibility properties to `Navbar.jsx` (settings link), `SymbolSearchBar.jsx` (combobox/listbox options selection), `BacktestHistory.jsx` (filters, refresh, selections), `SessionCard.jsx` (busy stops, chevrons), `ParamsForm.jsx` / `RiskParamsFields.jsx` (labels and inputs link), and `Trade.jsx` (timeframe buttons).
- **3.11 Polling `isFetching` States**: Surfaced background queries refresh status using a pulsating status dot next to tabs in `Trade.jsx` and the header in `AlgoTrading.jsx`.
- **3.4 follow-up sorting**: Wired client-side column sorting using `useTableSort` hook and `<SortableHeader>` component in `RecentActivityTable.jsx`, `StrategyLeaderboard.jsx`, and `CachedCandlesTable.jsx`.
- **3.8 follow-up empty states**: Wrapped `EmptyState` component inside the empty table rows in `Trade.jsx`, and on `BacktestHistory.jsx`, `Strategies.jsx`, and `AdminPanel.jsx`.
- **Golden master & Build**: Confirmed successful client workspace compilation (`npm run build` succeeds). Zero-finding code-doc drift review.

**Files changed:**
- `client/package.json`
- `client/src/App.jsx`
- `client/src/pages/Settings.jsx`
- `client/src/pages/RiskDashboard.jsx`
- `client/src/features/strategies/StrategyCreateDialog.jsx`
- `client/src/pages/Backtest.jsx`
- `client/src/hooks/useAlgoSessions.js`
- `client/src/components/layout/Navbar.jsx`
- `client/src/components/SymbolSearchBar.jsx`
- `client/src/features/backtest/BacktestHistory.jsx`
- `client/src/components/algo/SessionCard.jsx`
- `client/src/components/algo/ParamsForm.jsx`
- `client/src/components/RiskParamsFields.jsx`
- `client/src/pages/Trade.jsx`
- `client/src/pages/AlgoTrading.jsx`
- `client/src/features/dashboard/RecentActivityTable.jsx`
- `client/src/features/dashboard/StrategyLeaderboard.jsx`
- `client/src/features/dashboard/CachedCandlesTable.jsx`
- `client/src/pages/Strategies.jsx`
- `client/src/pages/AdminPanel.jsx`
- `client/CLAUDE.md`
- `workspace/docs/state/CURRENT_STATE.md`
- `workspace/plan/handoff.md`

**Next session:** Complete. All deferred items resolved and verified against spec. Ready for Phase 3 polish.

**Open questions:** None.

---
## 2026-07-01 — UI Refinement Phase 2 (Structural & Convention) — PARTIAL, see below

**Goal:** Execute items 3.1–3.13 from `workspace/plan/ui_refinement.md` on the `auth` branch only.

**Decisions confirmed with user before starting:** 3.1 navbar → update docs to match code (not revert code); 3.9 toast library → react-hot-toast (not yet installed — deferred, see below); 3.4 sort → "do both" client-side + server-side.

**Done this session:**
- **3.1** Navbar a11y: `aria-label`/`aria-expanded`/`aria-controls` on the hamburger, `focus-visible` rings on nav items + active `border-b-2 border-emerald-400`, `aria-haspopup`/`aria-expanded`/`aria-label` + `role="menu"` on the avatar dropdown. `client/CLAUDE.md` navbar spec rewritten to match the actual 7-item navbar + mobile drawer (decision 5.1 = keep code, update docs).
- **3.2** Avatar circle: replaced 3× inline `style={{borderRadius:'50%'}}` with the Tailwind arbitrary class `[border-radius:50%]` in `Navbar.jsx`.
- **3.3** New `components/ui/pagination.jsx` (First/Prev/page-numbers-with-ellipsis/jump-to-page/Next/Last, `aria-current`, 36px targets). Wired into `OrderHistory.jsx`, `Backtest.jsx` (trades table), `BacktestHistory.jsx` (history list).
- **3.4** `OrderHistory.jsx` and `Backtest.jsx` history filters now live in `useSearchParams()` (shareable/back-button-able URLs). New `components/ui/table.jsx` → `<SortableHeader>` (`aria-sort`, toggles asc/desc/none) + `hooks/useTableSort.js` (client-side sort for in-memory tables). Server-side sort added to `GET /api/v1/order-history` (`?sort=&order=`, whitelisted `SORTABLE_FIELDS` in `orderHistory.controller.js` to prevent Mongo-operator injection) and wired end-to-end in `OrderHistory.jsx`. BacktestHistory/Dashboard tables still need `useTableSort` wiring — not done (time-boxed).
- **3.5/3.6** Added `formatCompact`, `formatPercent`, `formatDateTime` (UTC-default, `UTC` suffix), `formatDate` to `utils/formatters.js`, documented in `client/CLAUDE.md`. Replaced ad-hoc `toLocaleString`/`toLocaleDateString`/`toLocaleTimeString` calls with UTC-consistent formatting in `Trade.jsx` (order/trade/transaction history tables + recent-trades blotter, now labeled "Time (UTC)"), `SessionCard.jsx` (equity tooltip, started time, activity log), `Backtest.jsx` (trade list), `OrderHistory.jsx`. **Not done:** `Trade.jsx`'s symbol-precision-aware `fmtPrice`/`fmtQty`/`fmtPriceForSymbol`/`fmtQtyForSymbol` were deliberately left alone — they're not simple duplicates of the canonical formatters (different precision/rounding semantics for order-book display), and blindly swapping them on the live trading page without visual QA was judged too risky.
- **3.7** Swept `text-slate-500` → `text-slate-400` across all 27 occurrences in `client/src` (body copy contrast fix). Documented the ≥18px decorative-only exception in `client/CLAUDE.md`.
- **3.8** New `components/ui/empty-state.jsx` (icon + title + description + action). Applied to `OrderHistory.jsx`. **Not applied yet** to `BacktestHistory.jsx`, `Trade.jsx` (6 sites), `Strategies.jsx`, `AdminPanel.jsx` — time-boxed, follow-up.
- **3.12** `client/CLAUDE.md` folder-structure section now documents `Login.jsx`, `AdminPanel.jsx`, `RiskDashboard.jsx`, `NotFound.jsx`, `components/risk/*` (4 files), `DashboardCalendar.jsx` (flagged unused), `backtest-analytics.js`, `exporters.js`, `useAuth.js`, `useRiskSettings.js`.
- **3.13** `workspace/docs/core/API_CONTRACTS.md`: added `/api/v1/auth/*`, `/api/v1/admin/*`, `/api/v1/risk/*` sections and documented the `tpsl_<uuid8>_<sl|tp>` / `oco_<uuid>_<sl|tp>` clientOrderId prefix convention. Removed the stale "auth routes not mounted" note.

**Not done (deferred to next session — see `ui_refinement.md` §3.9–3.11):**
- 3.9 Toast library (react-hot-toast) — not installed, hand-rolled banners untouched.
- 3.10 ARIA sweep on the remaining ~20 icon-only buttons / form labels / SymbolSearchBar combobox semantics.
- 3.11 Stale-data (`isFetching`) indicators on polling queries.
- 3.4 follow-up: wire `useTableSort` into Dashboard tables (`RecentActivityTable`, `StrategyLeaderboard`, `CachedCandlesTable`) and `BacktestHistory.jsx`.
- 3.8 follow-up: `EmptyState` on `Trade.jsx`, `BacktestHistory.jsx`, `Strategies.jsx`, `AdminPanel.jsx`.

**⚠️ Incident this session — pre-existing file truncation, now repaired:**
Before any Phase 2 edits, `git diff` showed the whole repo as "modified" — almost entirely CRLF/LF
line-ending noise unrelated to real changes (only 11 files had real Phase-1 content, confirmed via
`git diff -w`). Only those 11 + files touched this session were staged/committed; the repo-wide CRLF
drift was left alone (recommend a dedicated `.gitattributes` + normalization commit later, separate
from feature work).

Separately, **6 files were found byte-truncated mid-JSX** (missing their closing tags entirely —
would have failed to build): `BacktestHistory.jsx`, `Navbar.jsx`, `SessionCard.jsx`, `AdminPanel.jsx`,
`NewBacktestWizard.jsx`, `RiskDashboard.jsx`, `Backtest.jsx`. Root cause: a bulk `sed -i` color-sweep
(for §3.7) run from the sandbox shell read several just-edited files through a stale filesystem-mount
cache and wrote the truncated version back over the real file. All 6 were repaired and verified
complete via direct file inspection (the shell's view of this mount lags live edits by an unpredictable
amount this session — **do not use shell `sed`/`grep`-based bulk edits on files edited in the same
session; use the file-editing tool's own find/replace instead**). Reconstruction confidence:
- **High** (small, unambiguous gap, verified against variable/handler names already in the file):
  `Navbar.jsx`, `AdminPanel.jsx`, `NewBacktestWizard.jsx`, `SessionCard.jsx`, `BacktestHistory.jsx`.
- **Medium** (larger gap, rebuilt from surrounding code + component props, structurally sound but
  not visually verified): `Backtest.jsx` (comparison-tab rendering + the New-Backtest-Wizard `Dialog`
  mount was missing entirely — rebuilt using the `ComparisonTable`/`handleRun`/`showWizard` already
  defined earlier in the same file).
- **Lossy — flagged for manual review**: `RiskDashboard.jsx`. The Symbol-Overrides form (Max
  Leverage / Volatility Multiplier / Max Exposure Notional inputs) was reconstructed with high
  confidence (state setters `symMaxLeverage`/`symVolMult`/`symMaxExposure` already existed in the
  file). **Zone 3 ("Historical Simulations" — leverage-scenario + Monte Carlo results UI, per
  `CURRENT_STATE.md`) was never seen by this session and was NOT reconstructed** — the file was
  closed out safely after Zone 2 instead of guessing at unseen UI. **Action needed: diff/review
  `RiskDashboard.jsx` against your own editor history or a backup to confirm Zone 3 wasn't lost, and
  re-add it if so.**

**Files changed (Phase 2, real content — not CRLF noise):**
- `client/src/components/layout/Navbar.jsx`, `client/CLAUDE.md`, `workspace/docs/core/API_CONTRACTS.md`
- `client/src/utils/formatters.js` (new exports)
- `client/src/components/ui/pagination.jsx` (new), `client/src/components/ui/empty-state.jsx` (new)
- `client/src/components/ui/table.jsx` (`SortableHeader` added), `client/src/hooks/useTableSort.js` (new)
- `client/src/pages/OrderHistory.jsx` (rewritten), `client/src/hooks/useOrderHistory.js`, `server/src/controllers/orderHistory.controller.js`
- `client/src/pages/Backtest.jsx`, `client/src/features/backtest/BacktestHistory.jsx`, `client/src/features/backtest/NewBacktestWizard.jsx`
- `client/src/components/algo/SessionCard.jsx`, `client/src/pages/AdminPanel.jsx`, `client/src/pages/RiskDashboard.jsx`
- `client/src/pages/Trade.jsx` (date formatting only)

**Next session:** Finish 3.9 (toast), 3.10 (ARIA sweep), 3.11 (stale indicators), the 3.4/3.8
follow-ups listed above, then move to Phase 3 (`ui_refinement.md` §4). **First**, get user
confirmation that `RiskDashboard.jsx` Zone 3 is intact (see incident note above).

**Open questions:** Is `RiskDashboard.jsx` Zone 3 (Historical Simulations) content intact? See incident note.

---
## 2026-07-01 — UI Refinement Phase 1 (Production Blockers) COMPLETE ✅

**Goal:** Execute all 12 Phase 1 items from `workspace/plan/ui_refinement.md`.

**Done this session:**
- **2.1** `RiskDashboard.jsx`: Added `useBannerError` hook + `InlineError` component; replaced all 5 `alert()` calls with per-section inline error banners (globalLimitsError, stratOverrideError, symOverrideError).
- **2.2** Created `components/ui/confirm-dialog.jsx` (Radix AlertDialog). Wired to all 8 destructive action sites: SessionCard (delete session), AlgoTrading (clear stopped), Trade.jsx (close position, cancel all orders), AdminPanel (remove email), RiskDashboard (delete strategy override, delete symbol override).
- **2.3** Created `components/ErrorBoundary.jsx` (class component, dev-only stack trace, reset button). Wrapped `<App>` in `main.jsx`. Wrapped `<ChartContainer>` in Trade.jsx and `<EquityCurve>` in Backtest.jsx.
- **2.4** Created `pages/NotFound.jsx`. Added `<Route path="*">` catch-all in App.jsx.
- **2.5** Converted `TpSlModal` and `LeverageModal` in Trade.jsx from hand-rolled `div` overlays to Radix `<Dialog>` — gets focus trap, Escape-to-close, ARIA semantics for free.
- **2.6** Replaced all `text-red-500` → `text-red-400` in Backtest.jsx (6 occurrences). No `text-green-*` violations found elsewhere.
- **2.7** Replaced raw `fetch()` in Trade.jsx `fetchKlines` with `api.get()` via the shared axios instance. Removed hardcoded `API_BASE`.
- **2.8** Disabled Binance Spot option in `NewBacktestWizard.jsx` (disabled + "coming soon" label). Locked `symbolList` to futures-only.
- **2.9** Backtest.jsx: when `activeResult.status === 'failed'`, renders error banner + "Run Again" CTA and hides all tab content panels.
- **2.10** Trade.jsx Buy/Sell buttons: added `aria-busy={orderPending}`, `aria-label`, and "Placing…" spinner text while pending.
- **2.11** Backtest.jsx: added `isError` / `resultError` state; shows "Result not found" card with "Browse all runs" link when `?jobId=` deep-link fails. BacktestHistory.jsx: added `isError` prop + "Couldn't load history" banner with Retry button.
- **2.12** Typo in Trade.jsx:1387 was already clean (`Enter a valid quantity and price`).

**Files changed (Phase 1):**
- `client/src/components/ui/confirm-dialog.jsx` (new)
- `client/src/components/ErrorBoundary.jsx` (new)
- `client/src/pages/NotFound.jsx` (new)
- `client/src/pages/RiskDashboard.jsx`
- `client/src/pages/AdminPanel.jsx`
- `client/src/pages/AlgoTrading.jsx`
- `client/src/pages/Trade.jsx`
- `client/src/pages/Backtest.jsx`
- `client/src/components/algo/SessionCard.jsx`
- `client/src/features/backtest/BacktestHistory.jsx`
- `client/src/features/backtest/NewBacktestWizard.jsx`
- `client/src/main.jsx`
- `client/src/App.jsx`

**Next:** Phase 2 — Structural & Convention Alignment (items 3.1–3.13 in ui_refinement.md):
- 3.1 Navbar drift decision + a11y fixes
- 3.2 Avatar circle inline style fix
- 3.3 Pagination primitive
- 3.4 Filter state in URL + sortable table headers
- 3.5 Number formatter consolidation
- 3.6 Date/time formatter consolidation
- 3.7 `text-slate-500` → `text-slate-400` contrast sweep
- 3.8 `<EmptyState>` primitive
- 3.9 Toast library (sonner)
- 3.10 ARIA sweep (icon-only buttons, form labels, combobox semantics)
- 3.11 Stale data indicators
- 3.12/3.13 Doc updates (client/CLAUDE.md, API_CONTRACTS.md)

**Open questions:** None.

---
## 2026-07-01 — Auth Branch Phase 5 (Client) COMPLETE ✅

**Goal:** Add Google OAuth login page, auth guard, per-user Navbar (avatar + logout), AdminPanel, and API key entry to client.

**Done this session:**
- `client/src/lib/axios.js`: Added `withCredentials: true`
- `client/src/lib/socket.js`: Added `withCredentials: true`
- `client/src/hooks/useAuth.js` (new): `useAuth()` → TanStack Query `GET /api/v1/auth/me`, returns `{ user, isLoading, isAuthenticated }`; `useLogout()` → POSTs logout + clears cache + redirects to `/login`; 401 handled silently (returns null, no query error state)
- `client/src/pages/Login.jsx` (new): ENMA landing page with Google OAuth button (`VITE_API_URL + /api/v1/auth/google`); shows `not_invited` error message from URL param
- `client/src/pages/AdminPanel.jsx` (new): Email whitelist CRUD using `GET/POST/DELETE /api/v1/admin/allowed-emails`
- `client/src/App.jsx` (rewritten): `ProtectedLayout` component (spinner → redirect to `/login` → Navbar+Outlet); `/login` is unprotected; all other routes nested under `ProtectedLayout`; `/admin` route added
- `client/src/components/layout/Navbar.jsx`: Added user avatar/name with Google photo support, Admin link for admin role, LogOut button
- `client/src/pages/Settings.jsx`: Added API key entry section (`POST /api/v1/trade/settings/keys`), shows saved status indicator; updated env copy; added `useQueryClient` + `useMutation` + `useQuery` for keys
- `server/src/controllers/auth.controller.js`: Fixed redirect URLs — error goes to `/login?error=not_invited` (was `/?error=not_invited`), success goes to `/` (was `/dashboard`)

**Files changed (Phase 5):**
- `client/src/lib/axios.js`, `client/src/lib/socket.js`
- `client/src/hooks/useAuth.js` (new)
- `client/src/pages/Login.jsx` (new), `client/src/pages/AdminPanel.jsx` (new)
- `client/src/App.jsx` (rewritten), `client/src/components/layout/Navbar.jsx`
- `client/src/pages/Settings.jsx`
- `server/src/controllers/auth.controller.js`

**Next:** Phase 6 — update `workspace/docs/state/CURRENT_STATE.md` with auth branch changes. Then `/sync-spec`.

**Open questions:** None.

---
## 2026-06-24 — Risk Model Improvements (workstream #2) — ALL 5 STEPS COMPLETE ✅

**Goal:** Five additive risk-model changes across `engine/core/models/risk.py`, `engine/core/models/portfolio.py`, `engine/services/backtest_runner.py`, `engine/core/live_bot_manager.py`.

**Steps done:**
- **Step 1 — Trailing stop on `AtrBracketRiskModel`**: Added `__init__`/`_reset()` with `_current_stop`/`_initialized`. Maintain path gates on `trail_atr_mult > 0`; ratchets stop using `price ± trail_mult × ATR`. Default 0 = static (golden-master safe).
- **Step 2 — Breakeven move**: Expanded state with `_entry_price`, `_initial_risk`, `_signal_price`. Maintain path gates on `breakeven_r > 0`; floors stop at `_entry_price` once `price >= entry + breakeven_r × initial_risk`. Both features share one stateful init block.
- **Step 3 — ATR percentile filter**: Added `_atr_history` (session-level, not reset between trades). Accumulates `s.vars["atr"]` each candle (O(1)). Entry path gates on `atr_percentile_min > 0` + ≥20 samples; uses `bisect.bisect_left` for rank. Default 0 = disabled.
- **Step 4 — Cost gate injection default**: Changed `_risk.get("min_edge_mult", 0.0)` → `0.05` in both `backtest_runner.py:310` and `live_bot_manager.py:242`. Golden master unchanged (ATR-based edge >> 5% of fee for all 5 strategies).
- **Step 5 — Portfolio exposure cap**: Added cap in `DefaultPortfolioModel.construct()` after sizing: `(risk_per_unit × qty) / equity > max_portfolio_risk` → veto. Injected from `risk_params` with default 0.06 in both runners. Golden master unchanged (default risk_pct=1% << 6% cap).

**Golden master:** `ws2_final` == `baseline` within tol=1e-6 (all 5 strategies). No re-baseline needed — all defaults are neutral for the golden dataset. Boundary suite 20/20.

**Files changed:** `engine/core/models/risk.py`, `engine/core/models/portfolio.py`, `engine/services/backtest_runner.py`, `engine/core/live_bot_manager.py`, `workspace/docs/state/CURRENT_STATE.md`, `workspace/plan/INDEX.md`, `workspace/plan/STATUS.md`, `workspace/plan/handoff.md`.

**Next:** Seq #3 — Dashboard page restructure (`dashboardPage_restructure.md`): 8 KPI stat cards, equity sparkline, drawdown chart, performance calendar heatmap, new backend aggregation endpoints.

**Open questions:** None.

---
## 2026-06-24 — Strategy Performance Refactor (workstream #1) — Phases 1–8 COMPLETE ✅

**Goal:** Two-phase strategy contract (`prepare()` batch + index-only `before()`) to kill the
O(N²) indicator recompute in the backtest loop, with live parity. Branch:
`refactor/precompute-strategies` (merged to `dev`).

**ALL PHASES DONE & golden-master gated (byte-equivalent, tol 1e-6, all 5 strategies):**
- **P1** — `BaseStrategy.prepare(candles)` default no-op (`core/strategy.py`) + one-time
  `strategy.prepare(candles_np)` in `services/backtest_runner.py` (step 6a', after validate_params).
- **P2** — MicroMacroRSIDivergence: RSI/ATR/4 pivots/smoothed-RSI → prepare(); dropped `candles[off:]`
  windowing; no-lookahead via `i-right` horizon in `_last_two_visible`. (17 trades / -273.30)
- **P3** — MultiDivergence: ATR + price pivots + every enabled oscillator's pivot arrays → prepare();
  `before()` reads up to horizon `c = i-L`. 9× O(N)→1×. (55 / -1688.49)
- **P4** — MicroScalper: fast/slow EMA + ATR seq → prepare(); index at i and i-1. (9 / -131.61)
- **P5** — BestSupertrend (hardest): SMA cross arrays (per-index cross_up/dn = exits + most-recent
  state machine = old backward scan) + HTF supertrend precomputed once; `tsl[-2]` via bucket index
  `k → htf_tsl[k-1]`. **Found & fixed a latent pandas-2.x `datetime64[ms]` epoch bug** in the bucket
  map (now uses `reindex(ffill)` on datetimes). Verified 0 per-candle signal diffs. (61 / -117.56)
- **P6** — AdaptiveTrend: trend/fast/slow EMA + ATR seq → prepare(); index at i, i-1, i-slope_lookback.
  (7 / +1543.91)
- **P7** — Live parity (`core/live_bot_manager.py`): `prepare()` re-run on the rolling ≤500 window
  each closed candle (+ warmup replay), `index=len-1`, then index-only `before()`. Same code path as
  backtest → exact parity, no drift, **no per-strategy `append_candle`** (rejected doc §3 approach).
- **P8** — boundary tests 20/20 ✅; py_compile all 8 changed files ✅ (ruff not in container);
  CURRENT_STATE.md updated; this handoff.

**Files changed:** `core/strategy.py`, `services/backtest_runner.py`, `core/live_bot_manager.py`,
all 5 `strategies/*/__init__.py`, `scripts/golden/{baseline,phase1..6}.json`,
`workspace/docs/state/CURRENT_STATE.md`, `workspace/plan/handoff.md`.

**Verify command (re-confirm any time, in engine container):**
```
docker compose exec engine python -m scripts.golden_master compare --a baseline --b phase6
docker compose exec engine python -m pytest tests/test_boundaries.py -q
```

**NOT done / next:**
- **Workstream #2 (risk-model improvements)** — separate, behavior-changing, re-baselines golden.
  Note the doc's "enable cost gate" item is WRONG about mechanism: changing the class default
  `min_edge_mult` is a no-op; both `backtest_runner.py:299` and `live_bot_manager.py:242` inject it
  from `risk_params` defaulting 0.0 — change the **injection default** instead.
- Known limitation flagged in code: BestSupertrend weekly (`W-MON`, right-labeled) HTF bucket mapping
  is off-by-one; not golden-covered (golden uses daily). Revisit if weekly HTF is ever used.
- Update `/add-strategy` skill template to require `prepare()` + index-only `before()` (deferred).

**Open questions:** None.

**Decisions (vs. written docs):** Live path (P7) uses `prepare()` on the rolling ≤500 window per
closed candle — NOT per-strategy `append_candle()` incremental (doc §3 rejected: drift/IndexError/
5 custom methods). Backtest index alignment is direct (`strategy.index = t`).

---
## 2026-06-24 — Strategy Performance Refactor (workstream #1) — Phase 1 COMPLETE

**Goal:** Two-phase strategy contract (`prepare()` batch + index-only `before()`) to kill O(N²)
indicator recompute in the backtest loop. Plan: `C:\Users\harsh\.claude\plans\go-to-workspace-plan-index-md-we-cuddly-gosling.md`. Branch: `refactor/precompute-strategies`.

**Decisions (vs. written docs):** Live path (Phase 7) uses `prepare()` on the rolling ≤500 window
per closed candle — NOT per-strategy `append_candle()` incremental (doc §3 rejected: drift/IndexError/
5 custom methods). Backtest index alignment is direct (`strategy.index = t` = absolute index into the
full `candles_np` passed to `prepare()`).

**Done this session (Phase 1 — no-op foundation):**
- `engine/core/strategy.py`: added `BaseStrategy.prepare(candles)` default no-op + clarified `before()` docstring (index-only for migrated strategies).
- `engine/services/backtest_runner.py`: one-time `strategy.prepare(candles_np)` call inserted after `validate_params()` (step 6a', before sim loop). Alpha params (which indicators need) are injected before this; risk params (step 6b) are not needed by prepare().
- **Golden master:** captured `baseline` on current HEAD, then `phase1` → `compare` = **GOLDEN-MASTER OK (5 strategies, tol 1e-06)**. Byte-equivalent (prepare() is no-op).

**Baseline metrics (for reference):** MicroScalper trades=9 np=-131.61 · AdaptiveTrend 7/+1543.91 · BestSupertrend 61/-117.56 · MicroMacroRSIDivergence 17/-273.30 · MultiDivergence 55/-1688.49.

**Next:** Phase 2 — migrate `MicroMacroRSIDivergence` (move RSI/ATR/4 pivots/smoothed-RSI to `prepare()`, drop `win` windowing, `before()` index-only). Gate: `run --label phase2` then `compare --a baseline --b phase2` must be OK. Watch the windowing-equivalence risk (full-array pivots vs. windowed `_last_two`).

**Open questions:** None.

---
## 2026-06-24 — Plan seq #1 (Live PnL fix) + #2 (Backtest UI refactor) COMPLETE

**Goal:** Implement the two highest-priority isolated plans, verify, and update workspace docs + plan tracking.

**Done this session:**
- **Live PnL `—` on reload (Option A — persistent DB):** Added `positionDetails` (`Object`, default `{}`) to `LiveSession` schema. `handleEngineStats` now `$set`s the per-symbol snapshot `{ side, qty, price, leverage }` on `position:open` and `$unset`s it on `position:close` (folded into the existing log `$push` updates). `SessionCard` seeds `positionDetails` state from `session.positionDetails` via lazy `useState`, so live PnL resolves after reload instead of showing `—`.
- **Backtest UI refactor:** Overview headline grid `grid-cols-5` (10) → `grid-cols-7` (14) — added Leverage, Fee Rate, Total Fees, Liquidations; Max Drawdown now shows `actual / allowed` (`riskParams?.max_session_dd ?? 0.20`). "Export JSON" relocated from the bottom card into the tab header bar (right-aligned, `ml-auto mr-4`, sized `px-4 py-2 text-sm` to match the page-header "Run Backtest" button). Removed the bottom "Simulation Config" and "Export Results" blocks; dropped the now-unused `Calendar` import.
- **Verified:** `npm run build` clean twice (8–10s, only pre-existing chunk-size warning). User-confirmed screenshot shows the 2×7 grid + `14.16% / 20.00%` drawdown rendering.
- **Docs:** `CURRENT_STATE.md` (Algo Trading + Backtesting), `API_CONTRACTS.md` (`LiveSession.positionDetails`). Archived both plans to `workspace/plan/archive/`; `INDEX.md` + `STATUS.md` renumbered remaining sequence (#1 strategy-perf refactor workstream, #2 risk improvements).

**Files changed:**
- `server/src/models/LiveSession.js`, `server/src/controllers/algo.controller.js`
- `client/src/components/algo/SessionCard.jsx`, `client/src/pages/Backtest.jsx`
- `workspace/docs/state/CURRENT_STATE.md`, `workspace/docs/core/API_CONTRACTS.md`
- `workspace/plan/INDEX.md`, `workspace/plan/STATUS.md`, `workspace/plan/handoff.md`
- moved → `workspace/plan/archive/{live_pnl_fix_plan,backtest_ui_refactor}.md`

**Heads-up (intentional, per the approved plan):** deleting the "Simulation Config" block also dropped **Date Range**, **Symbol / Exchange**, and **Net Funding** from the Overview tab. Leverage/Fee Rate/Total Fees/Liquidations survive in the new grid; Net Funding is not currently shown anywhere on Overview. Re-add as a 15th metric if it's needed.

**Next session:** seq #1 — strategy performance refactor workstream (`plans/migration_checklist.md`, Phases 0–8, golden-master gated). Not started.

**Open questions:** None.

---
## 2026-06-22 — Title Block Shades, Dialog Widths, and Title Descriptions COMPLETE

**Goal:** Standardize background shades to `#0d1117` via `--title-bg`, enforce fixed widths for Chaos & New Bot wizard dialogs, remove section descriptions, and fix any build errors.

**Done this session:**
- **Standardized background shades:** Defined global `--title-bg` CSS variable mapping to `#0d1117` in `index.css` and registered color `'title-bg'` in `tailwind.config.js`. Updated `Navbar`, `card.jsx`, `dialog.jsx`, `SessionCard`, `StrategyCard`, `StrategyCreateDialog`, `CodeViewer`, `BacktestCalendar`, `OrderHistory`, `Settings`, and `Trade` components to use `bg-title-bg` consistently.
- **Fixed Width Dialogs:** Locked wizard dialog containers to `w-[720px] max-w-[95vw]` with `overflow-x-hidden` in [AlgoTrading.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/AlgoTrading.jsx) to prevent resizing/shifting across step tabs.
- **Removed descriptions:** Stripped CardDescription subheadings app-wide (Recent Activity, Strategy Leaderboard, Cache Tables, Backtest configuration, and chart subheadings).
- **Vite/Babel Syntax Fix:** Fixed mismatched closing div tags in `ChaosWizard.jsx` around step 2 / live preview containers. Verified production build compiles successfully on host and inside the client container.

**Files changed:**
- [index.css](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/index.css)
- [tailwind.config.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/tailwind.config.js)
- [Navbar.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/layout/Navbar.jsx)
- [card.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/ui/card.jsx)
- [dialog.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/ui/dialog.jsx)
- [SessionCard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/algo/SessionCard.jsx)
- [StrategyCard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/features/strategies/StrategyCard.jsx)
- [StrategyCreateDialog.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/features/strategies/StrategyCreateDialog.jsx)
- [CodeViewer.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/features/strategies/CodeViewer.jsx)
- [BacktestCalendar.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/features/backtest/BacktestCalendar.jsx)
- [OrderHistory.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/OrderHistory.jsx)
- [Settings.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/Settings.jsx)
- [Trade.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/Trade.jsx)
- [ChaosWizard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/algo/ChaosWizard.jsx)
- [NewSessionWizard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/algo/NewSessionWizard.jsx)

**Next session:**
- None. (Task complete).

---
## 2026-06-22 — Wizard Dialog Layout Width Fix COMPLETE

**Goal:** Fix layout shifting and resizing of "Chaos Mode" and "New Bot" wizard dialogs during step navigation and allocation toggles.

**Done this session:**
- **Fixed Width Dialogs:** Enforced a fixed width of `w-full md:w-[672px] md:max-w-2xl` on both `DialogContent` wrappers in [AlgoTrading.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/AlgoTrading.jsx).
- **Verified Build:** Built the client production build to confirm everything compiles correctly.

**Files changed:**
- [AlgoTrading.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/AlgoTrading.jsx)

**Next session:**
- None. (Task complete).

---
## 2026-06-22 — Configurable Chaos Mode Wizard COMPLETE

**Goal:** Turn Chaos Mode into a configurable launch wizard (matching the New-Bot NewSessionWizard pattern) to control active strategies, manual/auto symbol picks, capital/leverage defaults, and shared risk parameters.

**Done this session:**
- **Tiered symbols & Allocator:** Created `server/src/utils/chaosAllocator.js` (pure symbol allocator) and updated `server/src/constants/top_symbols.js` with 80 tiered symbols (high, mid, low volume).
- **Chaos Settings:** Added 5 configuration fields to the Settings database model, controller validation, and the frontend Settings UI page ("Chaos Setting (testnet)").
- **StartChaos Rework:** Updated `POST /api/v1/algo/chaos` route to accept and validate timeframe, custom strategies selection, manual symbol lists, and risk overrides.
- **ChaosWizard Component:** Implemented `client/src/components/algo/ChaosWizard.jsx` (4-step dialog wizard) with strategies select, auto/manual symbol picker with cap checks, live client-side allocation previews (counts & tiers), risk configs, and review before launch.
- **Wired Frontend:** Integrated `ChaosWizard` modal into the "Chaos Mode" button in `client/src/pages/AlgoTrading.jsx`.
- **Docs updated:** Updated `workspace/docs/state/CURRENT_STATE.md` and `workspace/docs/core/API_CONTRACTS.md`.

**Files changed:**
- [top_symbols.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/constants/top_symbols.js)
- [chaosAllocator.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/utils/chaosAllocator.js)
- [Settings.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/models/Settings.js)
- [settings.controller.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/controllers/settings.controller.js)
- [Settings.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/Settings.jsx)
- [algo.controller.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/controllers/algo.controller.js)
- [algo.routes.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/server/src/routes/algo.routes.js)
- [useAlgoSessions.js](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/hooks/useAlgoSessions.js)
- [ChaosWizard.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/components/algo/ChaosWizard.jsx) (New)
- [AlgoTrading.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/AlgoTrading.jsx)
- [CURRENT_STATE.md](file:///c:/Users/harsh/Desktop/enma_trading_platform/workspace/docs/state/CURRENT_STATE.md)
- [API_CONTRACTS.md](file:///c:/Users/harsh/Desktop/enma_trading_platform/workspace/docs/core/API_CONTRACTS.md)

**Next session:**
- Perform manual validation and testing in the Docker dev stack.

---
## 2026-06-22 — UI restyle to UI_STYLE_GUIDE.md — Phase 1 (foundation + chrome) COMPLETE; pages STAGED

**Goal:** Migrate the whole client to the midnight-blue trading-terminal palette in
`workspace/docs/core/UI_STYLE_GUIDE.md`. Reference impl (AlgoTrading.jsx + SessionCard.jsx) was
already on-style — the guide was derived from them.

**Done this session:**
- **Foundation layer migrated** (cascades to every page): `components/ui/{card,button,badge,input,select,table,dialog,tabs,skeleton}.jsx`, `layout/{Navbar,PageWrapper}.jsx`, `ui/PageHeader.jsx`, `features/dashboard/StatCard.jsx`, `components/RiskParamsFields.jsx`. Swaps: `bg-gray-900/950`→`bg-[#0d1117]`/`bg-[#060a0f]`/`bg-[#0a0d13]`, `border-gray-800`→`border-slate-700/50`, `text-gray-500`→`text-slate-400`, `rounded`→`rounded-lg`/`rounded-xl`, emerald-500/15→emerald-400/10.
- **Fully restyled pages:** Dashboard, Strategies, Settings, OrderHistory (+ their feature components: RecentActivityTable, StrategyLeaderboard, CachedCandlesTable, StrategyCard, CodeViewer, StrategyCreateDialog).
- **Page chrome only:** Trade.jsx root bg → `bg-[#060a0f]`; Backtest.jsx already uses PageWrapper/PageHeader (chrome free).
- **New skill:** `.claude/commands/restyle-ui.md` (`/restyle-ui`) — reads the guide + cheat-sheet and restyles any file on request.
- **Docs:** `client/CLAUDE.md` Layout/Styling/Chart/StatCard sections rewritten to the new palette and pointed at the guide as single source of truth.
- Verified: `npm run build` passes clean (8.9s, only pre-existing chunk-size warning).

**Next session — restyle remaining heavy internals (use `/restyle-ui`):**
- `pages/Trade.jsx` (~79 bespoke panels — bg-gray-900 boxes, order form, orderbook, chart panel, position table)
- `pages/Backtest.jsx` (~30 — inner panels, TableHeader bg-gray-950, progress bar) + `features/backtest/{BacktestConfigForm,BacktestHistory,BacktestCalendar,BacktestMetricCard}.jsx`
- `components/algo/{NewSessionWizard,SymbolPicker,ParamsForm}.jsx`, `components/SymbolSearchBar.jsx`
- `components/charts/EquityCurve.jsx` — apply chart-axis tokens (fill #94a3b8, stroke #1e293b, baseline #4B5563, line #34d399/#f87171)
- NOTE: `bg-gray-700/50` in AlgoTrading.jsx/SessionCard.jsx is the guide's sanctioned "stopped" status color — NOT a violation, leave it.

**Open questions:** None. Approach (foundation-first, pages staged; CLAUDE.md updated) confirmed with user.

---
## 2026-06-21 — Chaos Mode feature (feature.md) — Phases 1 + 2 COMPLETE

**Done:**
- Phase 1 (Leverage clamp): `engine/utils/symbols.py` → `get_max_leverage()` + `clamp_leverage()` (signed fetch + offline map). Wired into live bot (`live_bot_manager.py`, logs reduction), manual trade (`routers/trade.py`, returns `effectiveLeverage`), backtest runner (offline `_MAX_LEVERAGE_OFFLINE_MAP`, silent). Golden master confirmed byte-equivalent before/after (GOLDEN-MASTER OK).
- Phase 2 (Chaos runner): `POST /api/v1/algo/chaos` added to `server/src/controllers/algo.controller.js` (fan-out over 5 strategies, hardcoded max-vol params + disjoint symbol sets). Route registered in `server/src/routes/algo.routes.js`. Console script `engine/scripts/chaos_runner.py` thin client of endpoint with poll table + `--stop`. PnlFixer verified absent; `strategy_seeder.py` comment added.

**Phase 3 also COMPLETE:** `useStartChaos()` mutation added to `client/src/hooks/useAlgoSessions.js`. "Chaos Mode" button (amber, Zap icon) + confirm dialog + error banner added to `client/src/pages/AlgoTrading.jsx`. All 3 phases of feature.md are done.

**Files changed:**
- `engine/utils/symbols.py` — `get_max_leverage`, `clamp_leverage`, offline map
- `engine/core/live_bot_manager.py` — clamp + log before set-leverage
- `engine/routers/trade.py` — clamp in POST /leverage, return effectiveLeverage
- `engine/services/backtest_runner.py` — offline clamp
- `server/src/controllers/algo.controller.js` — startChaos + CHAOS_LAUNCH_LIST
- `server/src/routes/algo.routes.js` — POST /chaos registered
- `engine/scripts/chaos_runner.py` — new console script
- `engine/services/strategy_seeder.py` — PnlFixer-absent comment
- `workspace/docs/state/CURRENT_STATE.md` — updated
- `feature_tracker.md` — created

**Open questions:** None. All resolved in feature.md.

---
Previous: Strategy parameter fixes applied (2026-06-21). All 5 seeded strategies updated with industry-standard defaults per StrategyResearch.md. Golden master snapshots were STALE after this change.

> **Resolved 2026-06-21:** the golden baseline was re-established and the five-strategy comparison passed (boundary suite 20/20) — see `workspace/docs/state/CURRENT_STATE.md` → "Verified Baselines". The "must re-baseline" action below is complete.

Changes made:
- MicroScalper: EMA 2/3→9/21, ATR 5→14, atr_multiplier 0.0→1.2 (gate enabled), sl 0.3→1.5, tp 0.5→2.0, MIN_WARMUP 10→25
- AdaptiveTrend: trend EMA 50→200, slope_lookback 1→5, entry EMA 3/10→21/55, ATR 5→14, atr_floor_mult 0.0→1.0, sl 0.5→2.0, trail 0.5→3.0, tp_r_mult 0.5→0.0 (pure trailing), MIN_WARMUP 55→210
- BestSupertrend: SMA 2/3→7/20, Supertrend pd 2→10, factor 1.0→3.0, risk model SignalExitRiskModel→AtrBracketRiskModel (adds hard SL), added sl_atr_mult=2.0 and atr_period=14 params
- MicroMacroRSIDivergence: rsi 2→14, micro_pivot 1→3, macro_pivot 2→5, confluence_window 200→20, ATR 5→14, sl 0.5→1.5, enable_rsi_level_filter 0→1, MIN_WARMUP 20→30
- MultiDivergence: piv_len 2→4, min_confluence 1→3, sl 0.5→1.5, tp 0.5→2.0, ATR 5→14, RSI/MFI/Stoch 2→14, ADX 5→14, MACD 2/5/2→12/26/9, Z-Score 5→20

Next: Re-run golden master to establish new baseline:
  docker compose exec engine python -m scripts.golden_master run --label baseline
Then run boundary tests:
  docker compose exec engine python -m pytest tests/test_boundaries.py -q