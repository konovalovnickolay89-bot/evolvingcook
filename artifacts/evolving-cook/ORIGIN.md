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
- Contract version built against: `0.0.0`
- Auth: Bearer in `Authorization` header; `credentials: omit`

## CORS status (2026-08-03)

Preflight from `http://127.0.0.1:8080` → **blocked** (no `Access-Control-Allow-Origin`).
Server-side curl to `/auth/login` and `/version` works (200/401 JSON).
