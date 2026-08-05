# Evolving Cook — public origin report

## Published FE origin (CORS — primary)

| Role | Value |
| --- | --- |
| **CORS origin** | `https://evolvingcook.grok.me` |
| Host | `evolvingcook.grok.me` |
| API base | `https://api.apidiscoverysolution.uk/api/v1` |

**Verified 2026-08-04:** API preflight and GET `/version` return  
`access-control-allow-origin: https://evolvingcook.grok.me`  
Grok FE can call the API from this origin.

## Live sandbox preview (dev / agent)

| Role | Value |
| --- | --- |
| Preview proxy host | `https://{port_id}.grok-code-wild.hades-www.grok-sandbox.com` |
| Current port_id | `hds-otdpoodpe0a2-6014-s7k3u` |
| Agent QA | `http://127.0.0.1:8080` |

## Vite allowedHosts

Must include (Vite 8 host gate → blank UI if missing):

- `evolvingcook.grok.me`
- `.grok.me`
- `.grok-sandbox.com`
- `localhost` / `127.0.0.1`

## API contract

- Built against: **0.1.12**
- Auth: Bearer in `Authorization`; `credentials: omit` (never cookies)
