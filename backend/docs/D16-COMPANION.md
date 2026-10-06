# Decision D16 — Kitchen companion (chat + daily brief)

| Field | Value |
|-------|--------|
| What | Context-aware assistant on the FE dashboard: free chat + cached daily tips |
| Transport | Reuses the **D10 Mistral gateway** (`catalog/llm_provider.py`); no SDK, no new env |
| Model | `COMPANION_MODEL` (default **`mistral-large-latest`** — flagship, companion only); ingest keeps `LLM_MODEL` (vision) |
| Context | Read-only snapshot per call: day status, per-section done/open/86 (+ 86'd dish names), open station-log lines (≤10/section), pending proposal count |
| Writes | **Never.** Advice text only — the companion cannot touch boards, orders or logs |
| Cache | `assist.CompanionBrief` — one row per service date; regenerate only with `refresh=true` |
| Contract | **0.1.19** |

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
// out 200
{ "service_date": "2026-10-06", "generated_at": "…", "model": "…",
  "tips": [{ "title": "…", "body": "…" }] }   // 3–5 tips
```

Cached per date; `refresh=true` regenerates (falls back to the cached brief if
the provider errors).

### Errors (both)

`503 llm_unconfigured` — `MISTRAL_API_KEY` unset. `503 llm_error` — provider /
parse failure. FE treats any 4xx/5xx as "companion offline" and stays usable.

## Prompting

One system prompt (chef-speak, MEP-first, show working, HACCP flags, advice
only, ≤180 words unless a recipe/plan is asked). JSON mode both ways:
chat → `{"reply"}`; brief → `{"tips":[{"title","body"}]}`.
