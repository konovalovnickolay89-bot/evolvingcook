# Decision D11 — Hermes A2A assist loop (async + signed webhook)

| Field | Value |
|-------|--------|
| Decision | **Hermes Agent (A2A v1.0)** for Phase 5 assist tasks; **no polling** for completion |
| Transport in | JSON-RPC A2A on **loopback only** (`127.0.0.1`) |
| Transport out | **A2A task push notification** (signed webhook) → Django internal receiver |
| Domain writes | **Never from webhook.** Webhook → `AssistProposal` / job status only; accept handler writes domain |
| Catalogue ingest | Unchanged — remains **D10 Mistral** via django-q2 (not Hermes) |
| Phase | **5** (do not start before 2–4 gates) |

Everything below is a lock for implementers. Prefer this doc over chat paraphrases.

---

## 1. Shape (locked)

```
django-q2 job (or admin action)
    │  2a. A2A v1.0 JSON-RPC SendMessage
    │      http://127.0.0.1:<A2A_PORT>/
    │      Authorization: Bearer <A2A_TOKEN>
    │      + configuration.taskPushNotificationConfig.url
    │           = http://127.0.0.1:8000/api/internal/agent-events
    ▼
Hermes A2A platform (gateway; localhost-only bind)
    │  runs task in live agent session
    │  2b/2c. on terminal state → POST signed push
    ▼
Django  POST /api/internal/agent-events   (loopback URL only)
    │  verify signature → reject unsigned/invalid loudly
    │  completed → upsert AssistProposal (idempotent on task_id)
    │  failed    → mark job failed (visible in admin)
    ▼
Mykola reviews AssistProposal in admin → accept/reject handlers write domain
```

**No completion polling.** `GetTask` is allowed only as a **debug/recovery** tool (e.g. push never arrived, or reply truncated — see §5), not the happy path.

---

## 2. Why A2A push (not generic Hermes outbound hooks)

| Mechanism | Use here? | Why |
|-----------|-----------|-----|
| **A2A push** (`taskPushNotificationConfig`) | **Yes — primary** | Per-task completed/failed; carries `taskId` / `contextId`; designed for long tasks |
| `hooks.outbound` (Hermes lifecycle bus) | No (not for AssistProposal) | Session/tool events, not A2A task terminal states; weak correlation |
| Inbound Hermes webhook platform (`:8644`) | No | Opposite direction (world → Hermes) |
| Polling `GetTask` | No (happy path) | Explicitly rejected by this refinement |

Implementers must **not** wire AssistProposal off `on_session_end` / generic outbound hooks.

---

## 3. Env / secret names

| Role | Env (Django `.env` / unit EnvironmentFile) | Env (Hermes `$HERMES_HOME/.env`) | Notes |
|------|--------------------------------------------|----------------------------------|--------|
| A2A bearer (app → Hermes) | `A2A_TOKEN` | `A2A_BEARER_TOKEN` **or** `A2A_PEER_TOKENS=evolving-cook:<same>` | Prefer peer token so audit identity = `evolving-cook` |
| Push HMAC (Hermes → app) | `WEBHOOK_SECRET` | `A2A_PUSH_SECRET` **= same value** | Must match. If Hermes omits `A2A_PUSH_SECRET`, it falls back to bearer — **do not rely on that**; set push secret explicitly |
| Push callback allowlist | — | `A2A_PUSH_CALLBACK_ALLOWLIST=http://127.0.0.1:8000/api/internal/agent-events` | **Required when `A2A_PEER_TOKENS` is set.** Peer tokens exit “localhost-only” SSRF mode, which otherwise blocks loopback push URLs. Exact URL only — never a public/Cloudflare hostname |
| A2A base | `A2A_BASE_URL=http://127.0.0.1:9900` | `A2A_PORT=9900` (default) | Never public hostname |
| Reply wait (Hermes) | — | `A2A_REPLY_TIMEOUT` (default 300) | Push still fires on terminal; raise if sync waiters matter |

Secrets stay in EnvironmentFile / `.env` only — never in repo, OpenAPI public docs, or admin HTML.

**Hermes platform enable** (`$HERMES_HOME/config.yaml` — default/gateway home that runs the unit):

```yaml
gateway:
  platforms:
    a2a:
      enabled: true
      extra:
        port: 9900
```

No token ⇒ bind stays `127.0.0.1` (required). Do **not** set `A2A_HOST=0.0.0.0` for this integration.

---

## 4. Endpoint placement (Django)

| Path | Public tunnel? | Auth |
|------|----------------|------|
| `POST /api/internal/agent-events` | **No** — must **not** exist on the tunnel-facing `/api/v1/*` router | Signature only (+ optional loopback IP check) |
| `/api/v1/*` AssistProposal list/accept | Yes (Bearer app auth) | Normal API auth |
| `/admin/*` AssistProposal + job | CF Access as today | Staff |

Hard rules:

1. Mount internal routes on a **separate** Django/Ninja entry (or path prefix) that Cloudflare tunnel **does not** route. Prefer binding verification: reject non-loopback `REMOTE_ADDR` / proxy headers in production settings.
2. URL registered with Hermes is always **`http://127.0.0.1:8000/api/internal/agent-events`** — never `api.apidiscoverysolution.uk`.
3. CSRF exempt (machine POST); no session cookie auth.

---

## 5. Wire formats (Hermes truth)

### 5.1 Inbound task (Django → Hermes)

JSON-RPC 2.0 `SendMessage` (v1.0 method name; path-style aliases also accepted by Hermes).

Register push **inline** on the same call:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "<uuid>",
      "role": "ROLE_USER",
      "contextId": "<assist_job_id>",
      "parts": [{ "text": "<task body — see contract file §7>" }]
    },
    "configuration": {
      "taskPushNotificationConfig": {
        "url": "http://127.0.0.1:8000/api/internal/agent-events"
      }
    }
  }
}
```

Headers: `Authorization: Bearer <A2A_TOKEN>`, `Content-Type: application/json`.

Store returned **`taskId`** on the job row before returning from the q2 worker.

### 5.2 Push webhook (Hermes → Django)

- Method: `POST`
- Header: `Content-Type: application/json`
- Header: **`X-A2A-Signature: <hex hmac-sha256>`** when secret set  
  (not GitHub’s `sha256=` prefix; raw hex digest)
- Body: A2A StreamResponse **statusUpdate** shape, e.g.

```json
{
  "statusUpdate": {
    "taskId": "...",
    "contextId": "...",
    "status": {
      "state": "TASK_STATE_COMPLETED",
      "timestamp": "...",
      "message": { "role": "ROLE_AGENT", "parts": [{ "text": "..." }] }
    }
  }
}
```

Terminal states of interest:

| `status.state` | Django action |
|---------------|----------------|
| `TASK_STATE_COMPLETED` | Parse agent text → upsert **AssistProposal**; job = succeeded |
| `TASK_STATE_FAILED` / `TASK_STATE_CANCELED` / `TASK_STATE_REJECTED` | Mark job **failed** (reason from message text); no proposal domain write |

**Signature algorithm (must match Hermes):**

```text
body_for_mac = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
sig = hmac.new(WEBHOOK_SECRET, body_for_mac, sha256).hexdigest()
compare_digest(sig, header_value)
```

Verify **before** JSON business logic that mutates DB. Invalid/missing signature → **401/403**, log loudly, no row write.

**Payload size caveat (Hermes v0.20):** push text is truncated to **~2000 characters** at send time. Task contract must keep the proposal JSON compact, **or** on completed + truncated marker the receiver may one-shot `GetTask` for full artifacts (recovery only). Prefer compact proposals.

**SSRF note:** With **no** peer/bearer tokens, Hermes is in localhost-only mode and allows loopback push callbacks. With **`A2A_PEER_TOKENS` / `A2A_BEARER_TOKEN` set** (required for Cook → Hermes auth), loopback callbacks are **blocked by default** — set Hermes env:

```bash
A2A_PUSH_CALLBACK_ALLOWLIST=http://127.0.0.1:8000/api/internal/agent-events
```

Exact match only (no wildcards). Do **not** put `api.apidiscoverysolution.uk` or any Cloudflare URL here. Restart `hermes-gateway` after changing. Without the allowlist you will see `push notification … blocked — unsafe callback URL` and jobs may finish on Hermes without creating `AssistProposal` via push.

---

## 6. Idempotency (2d)

Webhook redelivery is **normal**.

| Key | Rule |
|-----|------|
| Natural key | A2A **`task_id`** (unique) |
| Completed | `get_or_create` / upsert AssistProposal by `task_id`; second delivery = no-op or refresh non-decided fields only |
| Failed | Job row `status=failed` is idempotent; never create a proposal on fail |
| Accepted/rejected proposals | Later redelivery **must not** clobber `status` / `decided_at` / domain side-effects |

Store `task_id` on both `AssistJob` (or q2 result metadata) and `AssistProposal`.

Suggested uniqueness:

```text
AssistProposal.task_id  unique, nullable only for non-Hermes sources if any
AssistJob.task_id       unique when set
```

---

## 7. Task-type contract file

Ship a versioned contract (separate from OpenAPI public surface), e.g.:

`docs/contracts/assist-tasks-v1.md` (+ optional JSON Schema)

Each task type defines:

- `kind` (maps to `AssistProposal.kind`)
- Input context schema (IDs only — no bulk catalogue dump unless required)
- Output **strict JSON** proposal schema (agent text body = JSON only, no fences)
- Max size budget (fit push 2k or document GetTask recovery)
- Degradation: if Hermes down / timeout / bad JSON → job failed or proposal with `status=pending` + parse_error; **UI still works without assist**

Graceful degradation is non-negotiable: kitchen ops must not depend on A2A being up.

---

## 8. Non-negotiables (carry forward)

1. Loopback only for A2A + agent-events.
2. Proposals only — webhook never writes stock, PO, planner lines, catalogue items.
3. Mistral key / D10 ingest stays with Django; Hermes uses its own model config (not the Mistral kitchen key unless you explicitly choose that later).
4. Contract file for task types before FE/admin verbs proliferate.
5. Evidence gate for the slice: **one signed round-trip**  
   `task in → webhook back → AssistProposal row created` (plus fail-path test: bad signature rejected; redelivery no duplicate).

---

## 9. Implementation split

| Piece | Owner |
|-------|--------|
| Enable A2A on gateway, secrets, loopback bind | host / linux-wiki (+ Vesper gateway config care) |
| Django `AssistProposal` + job model + admin | linux-wiki / `~/src/evolving-cook` |
| `POST /api/internal/agent-events` + HMAC verify + idempotency | linux-wiki |
| q2 client: SendMessage + push URL | linux-wiki |
| Task-type contract + agent prompt pack | Vesper + linux-wiki; culinary meaning with graph-recall if needed |
| FE | Grok — only after OpenAPI for accept/list; internal webhook never FE-facing |

---

## 10. Evidence checklist (gate)

- [ ] `curl http://127.0.0.1:9900/.well-known/agent-card.json` → 200 (gateway up)
- [ ] Signed SendMessage with push URL → Hermes runs → POST hits agent-events
- [ ] Valid signature → exactly one `AssistProposal` for `task_id`
- [ ] Replay same push → still one row
- [ ] Bad signature → 4xx, zero rows
- [ ] Failed task state → job failed in admin, no accepted domain write
- [ ] `curl -sS https://api.apidiscoverysolution.uk/api/internal/agent-events` → **not exposed** (404/blocked)

---

## 11. Explicit non-goals

- Replacing D10 catalogue photo ingest with Hermes
- Exposing A2A or agent-events on the public tunnel
- Auto-accept proposals
- Generic `hooks.outbound` as the AssistProposal bus
