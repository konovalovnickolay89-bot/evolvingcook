# Decision D16 — Kitchen companion (chat + daily brief)

| Field | Value |
|-------|--------|
| What | Context-aware assistant on the FE dashboard: free chat + cached daily tips |
| Transport | Reuses the **D10 Mistral gateway** (`catalog/llm_provider.py`); no SDK, no new env |
| Model | `COMPANION_MODEL` (default **`mistral-large-latest`** — flagship, companion only); ingest keeps `LLM_MODEL` (vision) |
| Context | Read-only snapshot per call: day status, per-section done/open/86 (+ 86'd dish names), open station-log lines (≤10/section), pending proposal count, live menu from active dish templates (`menu`: section → category → "Dish — notes \| component; component"; `menu_changes`: names whose notes open with a NEW / CHANGED tag; `off_menu`: inactive template names) |
| Writes | **Never.** Advice text only — the companion cannot touch boards, orders or logs |
| Cache | `assist.CompanionBrief` — **manual only**. Standing tips on `service_date=1970-01-01` plus any other row with `payload.mode=manual`. Unresolved tips (`resolved_at` null) show on every service date. `refresh=true` does not call the model and does not overwrite tips. |
| Contract | **0.1.20** (brief shape extended; old clients still read `title` / `body`) |

## Endpoints (Bearer, `/api/v1/assist/*`)

### `POST /assist/chat`

```jsonc
// in
{ "messages": [{ "role": "user" | "assistant", "content": "…" }],
  "service_date": "2026-10-06" }          // optional, default today (Europe/London)
// out 200
{ "reply": "…", "model": "mistral-medium-latest" }
```

Last message must be `user`. Server keeps the last 12 messages, 2000 chars each.
`400 bad_request` on an empty/assistant-last conversation.

### `GET /assist/daily-brief?service_date=&refresh=`

```jsonc
// out 200 — stored tips only. Empty list is valid. Never calls the model.
{ "service_date": "2026-10-24", "generated_at": "…", "model": "",
  "mode": "manual",
  "tips": [{ "id": "…", "title": "…", "body": "…",
             "source": "typed" | "voice" | "banto",
             "created_at": "…", "resolved_at": null }] }
```

`refresh=true` is accepted for the existing dashboard poll and is a no-op:
it does not overwrite manual tips and does not suggest new ones (no Suggest
into the brief in this version). Menu NEW/CHANGED tags, invoice uploads,
`AssistProposal`, and `CatalogIngestProposal` never become tips.

Open tips carry across days. They live until `POST /assist/daily-brief/clear`
(resolves every open tip) or `POST /assist/daily-brief/tips/{id}/resolve`
or `DELETE`. Midnight does not wipe them. `PUT /assist/companion-profile`
does not delete the brief — that used to force a model refill on the next poll.

### Write tips

```jsonc
POST /assist/daily-brief/tips
{ "title": "…", "body": "…", "source": "typed" | "voice" | "banto" }

PATCH /assist/daily-brief/tips/{id}
{ "title": "…", "body": "…" }          // either field optional

DELETE /assist/daily-brief/tips/{id}
POST   /assist/daily-brief/tips/{id}/resolve
POST   /assist/daily-brief/clear
```

**Persistence.** One standing `CompanionBrief` row (`service_date` 1970-01-01,
not a service day) holds new tips in `payload.tips`. Any other row whose
payload is `mode=manual` also contributes tips with `resolved_at` null, so a
tip written onto a real service date still shows the next day. Rows without
`mode=manual` are old model caches: they are not returned and not regenerated.
The 2026-10-24 London row is migrated to `mode=manual` and `tips=[]`.

### `GET | PUT /assist/companion-profile`

```jsonc
// out 200 (GET and PUT)
{ "text": "chef's standing rules…", "updated_at": "…" | null }
// PUT in
{ "text": "…" }                      // trimmed, capped 4000 chars
```

The profile rides into every chat prompt as `house_profile`
(authoritative unless it conflicts with food safety). It does not rewrite
the daily brief. Saving it leaves manual tips where they are.

### Kitchen notes (not the brief)

```jsonc
GET  /assist/kitchen-notes?include_resolved=
POST /assist/kitchen-notes
{ "title": "…", "body": "…", "source": "typed" | "voice" | "banto" }
POST /assist/kitchen-notes/{id}/resolve

GET  /assist/kitchen-inbox
POST /assist/kitchen-inbox/{id}/resolve
```

`KitchenNote` is the dictation store (Bantō appends with `source=banto`).
`KitchenInboxItem` points at an `AssistProposal` or a `CatalogIngestProposal`
when those rows are created. Resolving an inbox item does not accept or
reject the proposal. Neither table is copied into brief tips.

### Invoice upload (raw until asked)

```jsonc
POST /assist/invoice-uploads
{ "raw_text": "…", "source_kind": "text" | "csv" }   // no model call

POST /assist/invoice-uploads/{id}/propose            // explicit ask only
```

### Errors (chat and recipe draft)

`503 llm_unconfigured` — `MISTRAL_API_KEY` unset. `503 llm_error` — provider /
parse failure (invalid JSON is retried once first). FE treats any 4xx/5xx as
"companion offline" and stays usable. The daily brief does not use this path:
a poll with no tips is `200` and `tips: []`.

## Prompting

One system prompt for chat and recipe draft (chef-speak, MEP-first, show
working, HACCP flags, advice only, ≤180 words unless a recipe/plan is asked;
menu answers come from the snapshot menu, which beats earlier chat turns).
JSON mode: chat → `{"reply"}`. The daily brief is not prompted.

The menu comes from templates, not the day's board lines, so a menu change
reaches the companion even on a board opened before it. Caps: 150 dishes per
section, 20 components per dish, 200-char notes. The NEW / CHANGED tag (and
its "… menu" label) moves out of the notes into `menu_changes`: left inline,
the model missed tags and read "Oct 26 menu" as 26 October.
