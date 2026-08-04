# Evolving Cook — public origin report

Report to API orchestrator for CORS allowlist. Update on any change.

## Sandbox (live preview / agent QA)

| Role | Origin |
| --- | --- |
| Agent browser / Playwright | `http://127.0.0.1:8080` |
| Container bind | `http://0.0.0.0:8080` (not a browser origin) |
| Container LAN | `http://172.16.0.2:8080` |
| Grok preview proxy session | `session_id=7d26bddb-7da6-5180-9fcd-2d932c9813f0` |
| Grok preview port_id | `hds-bu8y1d7nljoy-6014-exwiy` |

**Browser origin as seen by the API is whatever hosts the page.**
In the Grok live preview that is the **preview proxy host** (not `127.0.0.1`).
Login screen surfaces `window.location.origin` for exact allowlist value.

## Published

| Role | Origin |
| --- | --- |
| Vercel / platform publish | Not yet published — will report `https://{VITE_PUBLIC_HOSTNAME}` when available |

## API

- Base: `https://api.apidiscoverysolution.uk/api/v1`
- Contract version built against: `0.1.5`
- Auth: Bearer in `Authorization` header; `credentials: omit`

## CORS status (2026-08-03 refreshed 18:28 UTC)

Preflight from `http://127.0.0.1:8080` → **allowlisted**.
`Access-Control-Allow-Origin: http://127.0.0.1:8080`
`Access-Control-Allow-Headers: accept, authorization, content-type, ...`
`Access-Control-Max-Age: 86400`
Browser fetch `/version` 200; bad login returns 401 JSON (not opaque CORS failure).
Still need: preview-proxy browser origin + published origin when known; real credentials for phone login gate.


## Contract refresh 2026-08-03 18:46 UTC

- Live `contract_version`: **0.1.5**
- Board endpoints available under `/boards/*`
- Client `EXPECTED_CONTRACT_VERSION` bumped to `0.1.5`
- Phase 1.5 UI wired; live board data still needs auth credentials
