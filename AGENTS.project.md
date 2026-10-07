# Evolving Cook — project instructions for Grok

Read with `AGENTS.md`; where they differ for this project, this file wins.

## What this project is (don't re-scaffold)

- **An existing Vite 8 + React 19 SPA (PWA), hash routing**, hand-written CSS
  (`src/styles/tokens.css` + `app.css`, no Tailwind). It is **not** the
  TanStack Start template `AGENTS.md` describes: no `src/router.tsx`, no
  `src/routes/`, no Better Auth, no Postgres/PGLite, no `migrations/`.
  Don't scaffold any of those in, and don't rewrite or "modernise" the app.
- **Source of truth: GitHub `konovalovnickolay89-bot/evolvingcook`, branch
  `main`.** Features are built there (with Claude Code). Your job on this
  project is to **sync and publish**, not to re-implement features from
  notes — that would fork the code.
- **Backend is separate.** Django API at
  `https://api.apidiscoverysolution.uk/api/v1`, deployed from Nick's own
  server. `backend/` is in this repo for reference only — never run,
  migrate or deploy it from here.
- **Auth:** Bearer token from the API (`/auth/login`, `/auth/refresh`),
  `credentials: "omit"`. No cookies, no `.env` needed for the frontend.

## Never change

- `API_BASE` and `EXPECTED_CONTRACT_VERSION` in `src/contract.ts` (must
  match the server's `/api/v1/version` → `contract_version`).
- `allowedHosts` / port 8080 in `vite.config.ts` (blank published UI if a
  host is missing) and the `VitePWA` block.
- Committed `dist/` is stale — always rebuild, never publish it as-is.

## Publish a new version

1. Sync the workspace to GitHub `main` (latest). Keep `startup.sh`.
2. `npm ci` (fall back to `npm install` only if the lockfile is rejected).
3. `npm run build` — runs `tsc --noEmit` then `vite build` into `dist/`
   (includes `sw.js`). Must exit 0.
4. Publish the same way the current `evolvingcook.grok.me` build was
   published, so the site serves the new `dist/`.
5. Live preview / startup: `npm run dev` on `0.0.0.0:8080` (what
   `startup.sh` already does).

## Current release — 0.1.20 (as of 2026-10-07)

Server is already live on **0.1.20**. The published frontend is an older
build (expects 0.1.19), so it shows the version-skew banner and is missing
the features below. **One rebuild from `main` fixes all of it.**

| In `main`, not yet on evolvingcook.grok.me | Where |
| --- | --- |
| Companion tuner ("Tune" → standing rules) | `src/pages/ChatPage.tsx` |
| Chat scrolls in its own pane; composer stays above nav + keyboard | `ChatPage.tsx`, `src/lib/useViewportFill.ts`, `AppShell` `fill` |
| Quick note (voice or text) → assist inbox | `src/pages/BoardsPage.tsx` |
| Recipes list / card / editor, covers scaling, companion drafting | `src/pages/RecipesPage.tsx`, `RecipePage.tsx`, `src/api/recipes.ts` |
| Stays signed in (silent token refresh) | `src/api/client.ts` |
| Counts / Ordering / Guided prep switch per section | `src/pages/BoardPage.tsx` |
| Honest version banner (server behind ≠ "refresh") | `src/components/VersionBanner.tsx` |

### Check it worked

- `GET https://api.apidiscoverysolution.uk/api/v1/version` →
  `"contract_version": "0.1.20"` (server — already true).
- The published `/assets/index-*.js` contains `0.1.20`, `companion-profile`,
  `/recipes/draft` and `chat-scroll` (the old build contains `0.1.19`).
- Open the app: no version banner; Dashboard shows **Quick note** and a
  **Recipes** button; Chat tab has **Tune**, and a long chat scrolls inside
  the pane with the input bar staying above the bottom nav.
- Phones with the old app installed get the "update available" banner —
  tap it (or close and reopen the app twice).

Endpoints the new screens call (all live, 401 when signed out):
`POST /assist/chat`, `GET /assist/daily-brief`,
`GET|PUT /assist/companion-profile`, `POST /assist/jobs` (quick note),
`GET|POST /recipes`, `GET|PATCH /recipes/{id}`, `POST /recipes/draft`,
`GET /sections/settings`, `PATCH /sections/{section}/settings`,
`POST /auth/refresh`.
